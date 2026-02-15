import asyncio
import json
import logging
import os
import shutil
import shlex
import subprocess
import sys
import time
import wave
from dataclasses import dataclass
from typing import Any

import open_xiaoai_server

from config import MUSIC_CONFIG
from music_search import MusicSearcher
from music_search import extract_play_keyword
from music_search import is_stop_play_command
from music_search import normalize_keyword
from music_service import LocalMusicHttpServer
from music_service import build_music_server
from player_control import ask_xiaoai
from player_control import play_music_url
from player_control import speak_text
from player_control import stop_playback


LOG_LEVEL = str((MUSIC_CONFIG.get("logging") or {}).get("level", "INFO")).upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
)
logger = logging.getLogger(__name__)


@dataclass
class SongItem:
    index: int
    path: str
    name: str
    url: str
    duration_sec: float


async def on_event(event: str):
    try:
        event_json = json.loads(event)
    except Exception:
        return

    if event_json.get("event") != "instruction":
        return

    raw_line = (event_json.get("data") or {}).get("NewLine")
    if not raw_line:
        return

    try:
        line = json.loads(raw_line)
    except Exception:
        return

    header = line.get("header", {})
    payload = line.get("payload", {})
    App.try_capture_reply_text(header=header, payload=payload, line=line)

    if (
        header.get("namespace") != "SpeechRecognizer"
        or header.get("name") != "RecognizeResult"
    ):
        return
    if not payload.get("is_final"):
        return

    results = payload.get("results") or []
    text = (results[0] or {}).get("text") if results else ""
    if not text:
        return

    logger.info("ASR 最终文本: %s", text)
    await App.handle_user_speech_interrupt(text)

    if is_stop_play_command(text, App.stop_keywords):
        App.disarm_reply_interrupt("收到停止命令")
        asyncio.create_task(App.stop_music())
        return

    if App._is_refresh_index_command(text):
        App.arm_reply_interrupt("语音刷新")
        asyncio.create_task(App.refresh_music_index_and_reply("语音刷新"))
        return

    if App._is_random_play_command(text):
        App.arm_reply_interrupt("语音随机播放")
        asyncio.create_task(App.play_random_music())
        return

    keyword = extract_play_keyword(text, App.play_keywords)
    if keyword:
        App.arm_reply_interrupt(f"语音搜索播放:{keyword}")
        asyncio.create_task(App.play_local_music_by_keyword(keyword))


def on_event_callback(event: str):
    asyncio.run_coroutine_threadsafe(on_event(event), App.loop)


class App:
    loop: asyncio.AbstractEventLoop | None = None
    music_server: LocalMusicHttpServer | None = None
    local_music_lock = asyncio.Lock()
    play_queue: list[SongItem] = []
    current_song: SongItem | None = None
    timer_task: asyncio.Task | None = None
    index_refresh_task: asyncio.Task | None = None
    index_refresh_lock = asyncio.Lock()
    last_reply_text: str = ""
    reply_interrupt_armed = False
    reply_interrupt_armed_at = 0.0
    reply_interrupt_reason = ""
    reply_interrupt_lock = asyncio.Lock()
    reply_interrupt_last_stop_at = 0.0
    whitelist_resume_task: asyncio.Task | None = None
    whitelist_resume_seq = 0

    timer_buffer_sec = float(MUSIC_CONFIG.get("timer_buffer_sec", 1.5))

    search_config = MUSIC_CONFIG.get("search", {}) or {}
    max_results = int(search_config.get("max_results", MUSIC_CONFIG.get("max_results", 50)))
    refresh_interval_sec = float(search_config.get("refresh_interval_sec", 300))
    search_index_file = str(search_config.get("index_file", ".cache/music_index.json"))
    audio_extensions = {
        str(ext).strip().lower()
        for ext in MUSIC_CONFIG.get("supported_audio_extensions", [])
        if str(ext).strip()
    }

    command_config = MUSIC_CONFIG.get("commands", {}) or {}
    play_keywords = list(command_config.get("play_keywords", []))
    stop_keywords = set(command_config.get("stop_keywords", []))
    refresh_keywords = {
        normalize_keyword(keyword).replace(" ", "")
        for keyword in command_config.get("refresh_keywords", [])
        if normalize_keyword(keyword)
    }
    random_play_keywords = {
        normalize_keyword(keyword).replace(" ", "")
        for keyword in command_config.get("random_play_keywords", [])
        if normalize_keyword(keyword)
    }
    interrupt_whitelist_keywords = {
        normalize_keyword(keyword).replace(" ", "")
        for keyword in command_config.get("interrupt_whitelist_keywords", [])
        if normalize_keyword(keyword)
    }
    reply_interrupt_timeout_sec = float(command_config.get("reply_interrupt_timeout_sec", 20))
    reply_interrupt_cooldown_sec = float(command_config.get("reply_interrupt_cooldown_sec", 1.2))
    auto_resume_delay_sec = float(command_config.get("auto_resume_delay_sec", 1.8))

    searcher = MusicSearcher(
        music_dirs=MUSIC_CONFIG.get("music_dirs", []) or [],
        max_results=max_results,
        extensions=audio_extensions,
        index_file=search_index_file,
    )
    ffprobe_path = shutil.which("ffprobe")

    @classmethod
    def arm_reply_interrupt(cls, reason: str):
        cls.reply_interrupt_armed = True
        cls.reply_interrupt_armed_at = time.monotonic()
        cls.reply_interrupt_reason = reason
        logger.info("回复拦截窗口已开启: 原因=%s", reason)

    @classmethod
    def disarm_reply_interrupt(cls, reason: str):
        if not cls.reply_interrupt_armed:
            return
        cls.reply_interrupt_armed = False
        logger.info("回复拦截窗口已关闭: 原因=%s 触发=%s", cls.reply_interrupt_reason, reason)
        cls.reply_interrupt_reason = ""

    @classmethod
    def _is_reply_interrupt_armed(cls) -> bool:
        if not cls.reply_interrupt_armed:
            return False
        now = time.monotonic()
        if now - cls.reply_interrupt_armed_at > cls.reply_interrupt_timeout_sec:
            cls.disarm_reply_interrupt("超时")
            return False
        return True

    @classmethod
    def _is_user_interrupt_whitelisted(cls, text: str) -> bool:
        normalized = normalize_keyword(text).replace(" ", "")
        return cls._matches_any_keyword(normalized, cls.interrupt_whitelist_keywords)

    @classmethod
    def _matches_any_keyword(cls, normalized_text: str, keywords: set[str]) -> bool:
        if not normalized_text:
            return False
        for keyword in keywords:
            if not keyword:
                continue
            if normalized_text == keyword or keyword in normalized_text:
                return True
        return False

    @classmethod
    async def handle_user_speech_interrupt(cls, text: str):
        normalized = normalize_keyword(text).replace(" ", "")
        if cls._is_user_interrupt_whitelisted(text):
            cls.disarm_reply_interrupt("用户语音白名单命中")
            logger.info("用户语音命中打断白名单，不清空队列: %s", text)
            await cls._schedule_auto_resume_after_whitelist(normalized, text)
            return
        cleared_count = await cls.clear_queue(stop_device=True)
        cls.disarm_reply_interrupt("用户语音打断")
        logger.info("用户语音打断，已清空队列并停播: 文本=%s 清空数量=%d", text, cleared_count)

    @classmethod
    def try_capture_reply_text(cls, header: dict[str, Any], payload: dict[str, Any], line: dict[str, Any]):
        namespace = str(header.get("namespace") or "")
        name = str(header.get("name") or "")
        if namespace == "SpeechRecognizer" and name == "RecognizeResult":
            return

        texts: list[str] = []
        for source in (payload, line):
            texts.extend(cls._extract_candidate_texts(source))
        unique_texts = [item for item in dict.fromkeys(texts) if item]
        if not unique_texts:
            return

        namespace_lower = namespace.lower()
        name_lower = name.lower()
        maybe_reply_event = (
            "tts" in namespace_lower
            or "speechsynthesizer" in namespace_lower
            or "nlp" in namespace_lower
            or "dialog" in namespace_lower
            or "assistant" in namespace_lower
            or "reply" in name_lower
            or "respond" in name_lower
            or "speak" in name_lower
        )
        if not maybe_reply_event:
            return

        cls.last_reply_text = unique_texts[0]
        logger.info(
            "小爱回复捕获: namespace=%s name=%s text=%s",
            namespace or "-",
            name or "-",
            cls.last_reply_text,
        )
        if cls._is_reply_interrupt_armed():
            is_speak_event = "speechsynthesizer" in namespace_lower and "speak" in name_lower
            if is_speak_event:
                now = time.monotonic()
                if now - cls.reply_interrupt_last_stop_at >= cls.reply_interrupt_cooldown_sec:
                    cls.reply_interrupt_last_stop_at = now
                    asyncio.create_task(cls._interrupt_reply_playback())

    @classmethod
    def _extract_candidate_texts(cls, value: Any) -> list[str]:
        candidates: list[str] = []
        if isinstance(value, str):
            text = value.strip()
            if text:
                candidates.append(text)
            return candidates
        if isinstance(value, list):
            for item in value:
                candidates.extend(cls._extract_candidate_texts(item))
            return candidates
        if isinstance(value, dict):
            direct_keys = {
                "text",
                "reply",
                "answer",
                "content",
                "tts",
                "say",
                "speech",
                "nlp_reply",
                "reply_text",
                "display_text",
            }
            for key, item in value.items():
                key_lower = str(key).lower()
                if key_lower in direct_keys and isinstance(item, str):
                    text = item.strip()
                    if text:
                        candidates.append(text)
                if key_lower in {"payload", "data", "results", "result", "instruction", "directives", "cards"}:
                    candidates.extend(cls._extract_candidate_texts(item))
            return candidates
        return candidates

    @classmethod
    async def _interrupt_reply_playback(cls):
        async with cls.reply_interrupt_lock:
            if not cls._is_reply_interrupt_armed():
                return
            logger.info("命中回复拦截窗口，立即停止小爱当前播报")
            await stop_playback()

    @classmethod
    async def _speak_text(cls, text: str):
        cls.disarm_reply_interrupt("即将发送播报")
        return await speak_text(text)

    @classmethod
    async def _ask_xiaoai(cls, text: str):
        cls.disarm_reply_interrupt("即将发送问答请求")
        return await ask_xiaoai(text)

    @classmethod
    async def _play_music_url(cls, url: str):
        cls.disarm_reply_interrupt("即将发送播放请求")
        return await play_music_url(url)

    @classmethod
    async def _schedule_auto_resume_after_whitelist(cls, normalized_text: str, raw_text: str):
        if cls.current_song is None:
            return
        cls.whitelist_resume_seq += 1
        seq = cls.whitelist_resume_seq
        if cls.whitelist_resume_task and not cls.whitelist_resume_task.done():
            cls.whitelist_resume_task.cancel()
        logger.info(
            "白名单语音触发自动恢复计划: 文本=%s 延迟=%.1fs",
            raw_text,
            cls.auto_resume_delay_sec,
        )
        cls.whitelist_resume_task = asyncio.create_task(cls._auto_resume_after_whitelist(seq))

    @classmethod
    async def _auto_resume_after_whitelist(cls, seq: int):
        try:
            await asyncio.sleep(max(cls.auto_resume_delay_sec, 0.1))
        except asyncio.CancelledError:
            return
        if seq != cls.whitelist_resume_seq:
            return
        async with cls.local_music_lock:
            if cls.current_song is None:
                return
            song = cls.current_song
            logger.info("执行白名单自动恢复播放: %s", song.name)
            await cls._cancel_timer_unlocked()
            await cls._start_song_unlocked(song, trigger="白名单自动恢复")

    @staticmethod
    def _safe_read_command_line(prompt: str = ">>> ") -> str:
        try:
            return input(prompt)
        except UnicodeDecodeError:
            # Some terminal/input sources may contain non-UTF8 bytes.
            sys.stdout.write(prompt)
            sys.stdout.flush()
            raw = sys.stdin.buffer.readline()
            if raw == b"":
                raise EOFError
            encoding = sys.stdin.encoding or "utf-8"
            return raw.decode(encoding, errors="replace").rstrip("\r\n")

    @classmethod
    def _probe_wav_duration(cls, file_path: str) -> float | None:
        try:
            with wave.open(file_path, "rb") as wav_file:
                frames = wav_file.getnframes()
                frame_rate = wav_file.getframerate()
                if frame_rate <= 0:
                    return None
                return float(frames) / float(frame_rate)
        except Exception:
            return None

    @classmethod
    def _probe_ffprobe_duration(cls, file_path: str) -> float | None:
        if not cls.ffprobe_path:
            raise RuntimeError("未检测到 ffprobe，无法探测歌曲时长")
        cmd = [
            cls.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            file_path,
        ]
        try:
            result = subprocess.run(
                cmd,
                check=False,
                capture_output=True,
                text=True,
                timeout=2.0,
            )
            if result.returncode != 0:
                return None
            value = float((result.stdout or "").strip())
            if value <= 0:
                return None
            return value
        except Exception:
            return None

    @classmethod
    def _ensure_ffprobe_available(cls):
        if not cls.ffprobe_path:
            raise RuntimeError("未检测到 ffprobe。请先安装 ffmpeg（含 ffprobe）后再启动")
        logger.info("运行能力检测: ffprobe=可用(%s)", cls.ffprobe_path)

    @classmethod
    def _get_track_duration_sec(cls, file_path: str) -> float | None:
        ext = os.path.splitext(file_path)[1].lower()
        if ext == ".wav":
            duration = cls._probe_wav_duration(file_path)
            if duration:
                return duration
        duration = cls._probe_ffprobe_duration(file_path)
        if duration:
            return duration
        return None

    @classmethod
    def _build_song_items(
        cls,
        files: list[str],
        music_server: LocalMusicHttpServer,
    ) -> list[SongItem]:
        songs: list[SongItem] = []
        for idx, file_path in enumerate(files, start=1):
            duration = cls._get_track_duration_sec(file_path)
            if duration is None:
                logger.warning("跳过无法探测时长的歌曲: %s", file_path)
                continue
            songs.append(
                SongItem(
                    index=idx,
                    path=file_path,
                    name=os.path.basename(file_path),
                    url=music_server.create_file_url(file_path),
                    duration_sec=duration,
                )
            )
        return songs

    @classmethod
    async def _cancel_timer_unlocked(cls):
        task = cls.timer_task
        cls.timer_task = None
        if not task or task is asyncio.current_task():
            return
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    @classmethod
    async def _clear_queue_unlocked(cls, stop_device: bool) -> int:
        queued_count = len(cls.play_queue) + (1 if cls.current_song else 0)
        await cls._cancel_timer_unlocked()
        cls.play_queue.clear()
        cls.current_song = None
        if stop_device:
            await stop_playback()
        return queued_count

    @classmethod
    async def clear_queue(cls, stop_device: bool = True) -> int:
        async with cls.local_music_lock:
            return await cls._clear_queue_unlocked(stop_device=stop_device)

    @classmethod
    def _log_queue(cls, songs: list[SongItem]):
        logger.info("播放队列已更新: 共%d首", len(songs))
        for song in songs:
            logger.info("队列[%d] %s", song.index, song.name)

    @classmethod
    def _schedule_timer_unlocked(cls, duration_sec: float):
        wait_sec = max(duration_sec, 0.1) + cls.timer_buffer_sec
        cls.timer_task = asyncio.create_task(cls._on_song_timer(wait_sec))

    @classmethod
    async def _start_song_unlocked(cls, song: SongItem, trigger: str):
        cls.current_song = song
        result = await cls._play_music_url(song.url)
        logger.info(
            "开始播放: 来源=%s 第%d首 %s 时长=%.1f秒 剩余队列=%d 路径=%s",
            trigger,
            song.index,
            song.name,
            song.duration_sec,
            len(cls.play_queue),
            song.path,
        )
        logger.debug("播放接口返回: %s", result)
        cls._schedule_timer_unlocked(song.duration_sec)

    @classmethod
    async def _on_song_timer(cls, wait_sec: float):
        try:
            await asyncio.sleep(wait_sec)
        except asyncio.CancelledError:
            return

        async with cls.local_music_lock:
            cls.timer_task = None
            if not cls.play_queue:
                cls.current_song = None
                return
            next_song = cls.play_queue.pop(0)
            logger.info(
                "自动切歌: 第%d首 %s，剩余队列=%d",
                next_song.index,
                next_song.name,
                len(cls.play_queue),
            )
            await cls._start_song_unlocked(next_song, trigger="自动切歌")

    @classmethod
    async def refresh_music_index(cls, reason: str):
        async with cls.index_refresh_lock:
            start_time = time.monotonic()
            total = await asyncio.to_thread(cls.searcher.refresh_index)
            cost_ms = (time.monotonic() - start_time) * 1000
            logger.info(
                "曲库索引刷新完成: 原因=%s 总数=%d 耗时=%.1f毫秒",
                reason,
                total,
                cost_ms,
            )
            return total, cost_ms

    @classmethod
    def _is_refresh_index_command(cls, text: str) -> bool:
        normalized = normalize_keyword(text).replace(" ", "")
        return bool(normalized) and normalized in cls.refresh_keywords

    @classmethod
    def _is_random_play_command(cls, text: str) -> bool:
        normalized = normalize_keyword(text).replace(" ", "")
        return bool(normalized) and normalized in cls.random_play_keywords

    @classmethod
    async def refresh_music_index_and_reply(cls, reason: str):
        try:
            if cls.index_refresh_lock.locked():
                await cls._speak_text("曲库正在刷新，请稍候")
                return
            await cls._speak_text("正在刷新曲库，请稍候")
            total, cost_ms = await cls.refresh_music_index(reason)
            await cls._speak_text(f"曲库刷新完成，共{total}首，耗时{cost_ms / 1000:.1f}秒")
        except Exception as exc:
            logger.exception("曲库索引刷新失败: 原因=%s 错误=%s", reason, exc)
            await cls._speak_text("曲库刷新失败，请稍后重试")

    @classmethod
    async def run_index_refresh_loop(cls):
        logger.info("曲库索引定时刷新已启动: 间隔=%.1f秒", cls.refresh_interval_sec)
        while True:
            try:
                await asyncio.sleep(max(cls.refresh_interval_sec, 1))
                if cls.index_refresh_lock.locked():
                    logger.info("跳过本次定时刷新: 当前已有刷新任务在执行")
                    continue
                await cls.refresh_music_index("定时刷新")
            except asyncio.CancelledError:
                logger.info("曲库索引定时刷新已停止")
                return
            except Exception as exc:
                logger.exception("曲库索引定时刷新异常: %s", exc)

    @classmethod
    async def play_local_music_by_keyword(cls, keyword: str):
        if not cls.searcher.has_dirs():
            await cls._speak_text("本地音乐目录还没有配置")
            return

        logger.info("收到搜索请求: 关键词=%s", keyword)
        files = await asyncio.to_thread(cls.searcher.find, keyword)
        count = len(files)
        if count == 0:
            await cls._speak_text(f"没有找到包含{keyword}的歌曲")
            logger.info("未找到匹配歌曲: 关键词=%s", keyword)
            return

        songs = await asyncio.to_thread(cls._build_song_items, files, cls.music_server)
        if not songs:
            await cls._speak_text("没有可播放的歌曲，无法解析音频时长")
            logger.warning("搜索结果存在但无可播放歌曲: 关键词=%s", keyword)
            return
        cleared_count = await cls.clear_queue(stop_device=True)
        logger.info(
            "搜索命中并替换队列: 关键词=%s 命中=%d 清空旧队列=%d",
            keyword,
            count,
            cleared_count,
        )
        cls._log_queue(songs)
        await cls._speak_text(f"好的，找到{count}首歌曲")

        async with cls.local_music_lock:
            cls.play_queue = songs
            first_song = cls.play_queue.pop(0)
            logger.info(
                "开始播放搜索结果首曲: 第%d首 %s，剩余队列=%d",
                first_song.index,
                first_song.name,
                len(cls.play_queue),
            )
            await cls._start_song_unlocked(first_song, trigger="搜索播放")

    @classmethod
    async def play_random_music(cls):
        if not cls.searcher.has_dirs():
            await cls._speak_text("本地音乐目录还没有配置")
            return

        logger.info("收到随机播放请求")
        files = await asyncio.to_thread(cls.searcher.random_pick)
        count = len(files)
        if count == 0:
            await cls._speak_text("曲库为空，无法随机播放")
            logger.info("随机播放失败: 曲库为空")
            return

        songs = await asyncio.to_thread(cls._build_song_items, files, cls.music_server)
        if not songs:
            await cls._speak_text("没有可播放的歌曲，无法解析音频时长")
            logger.warning("随机结果存在但无可播放歌曲")
            return
        cleared_count = await cls.clear_queue(stop_device=True)
        logger.info("随机选歌并替换队列: 命中=%d 清空旧队列=%d", count, cleared_count)
        cls._log_queue(songs)
        await cls._speak_text(f"好的，随机播放{count}首歌曲")

        async with cls.local_music_lock:
            cls.play_queue = songs
            first_song = cls.play_queue.pop(0)
            logger.info(
                "开始播放随机队列首曲: 第%d首 %s，剩余队列=%d",
                first_song.index,
                first_song.name,
                len(cls.play_queue),
            )
            await cls._start_song_unlocked(first_song, trigger="随机播放")

    @classmethod
    async def stop_music(cls):
        count = await cls.clear_queue(stop_device=True)
        logger.info("已停止播放并清空队列: 数量=%d", count)

    @classmethod
    async def command_loop(cls):
        print(
            "\nCommands:\n"
            "  say <text>   - 小爱直接播报文本\n"
            "  ask <text>   - 让小爱理解并回复\n"
            "  music <url>  - 让小爱播放音乐 URL\n"
            "  local <kw>   - 搜索本地目录并播放匹配歌曲\n"
            "  stop         - 暂停当前播放\n"
            "  refresh      - 手动刷新曲库索引\n"
            "  quit         - 退出\n"
        )

        while True:
            try:
                line = await asyncio.to_thread(cls._safe_read_command_line, ">>> ")
            except EOFError:
                logger.info("检测到 stdin 关闭，退出命令循环")
                break

            args = shlex.split(line.strip())
            if not args:
                continue

            cmd = args[0].lower()
            if cmd in {"quit", "exit"}:
                break

            if cmd == "stop":
                await cls.stop_music()
                continue

            if cmd == "refresh":
                await cls.refresh_music_index("手动刷新")
                continue

            if len(args) < 2:
                print("参数不足")
                continue

            content = " ".join(args[1:])
            if cmd == "say":
                logger.info("[say] 返回=%s", await cls._speak_text(content))
            elif cmd == "ask":
                logger.info("[ask] 返回=%s", await cls._ask_xiaoai(content))
            elif cmd == "music":
                logger.info("[music] 返回=%s", await cls._play_music_url(content))
            elif cmd == "local":
                await cls.play_local_music_by_keyword(content)
            else:
                logger.warning("未知命令: %s", cmd)

    @classmethod
    async def start(cls):
        server_task = None
        command_task = None
        cls.loop = asyncio.get_running_loop()
        cls._ensure_ffprobe_available()
        cls.music_server = build_music_server(MUSIC_CONFIG.get("http", {}) or {})
        cls.music_server.start()
        logger.info("音乐 HTTP 服务已启动: %s", cls.music_server.base_url)

        await cls.refresh_music_index("启动刷新")
        if cls.refresh_interval_sec > 0:
            cls.index_refresh_task = asyncio.create_task(cls.run_index_refresh_loop())
        else:
            logger.info("曲库索引定时刷新已禁用: refresh_interval_sec=%.1f", cls.refresh_interval_sec)

        try:
            open_xiaoai_server.register_fn("on_event", on_event_callback)
            server_task = open_xiaoai_server.start_server()
            if sys.stdin.isatty():
                command_task = asyncio.create_task(cls.command_loop())
                done, pending = await asyncio.wait(
                    {server_task, command_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                for task in pending:
                    task.cancel()
                for task in done:
                    try:
                        await task
                    except asyncio.CancelledError:
                        pass
            else:
                logger.info("非交互模式: 命令行循环已禁用")
                await server_task
        finally:
            if server_task:
                server_task.cancel()
            if command_task:
                command_task.cancel()
            if cls.index_refresh_task:
                cls.index_refresh_task.cancel()
                try:
                    await cls.index_refresh_task
                except asyncio.CancelledError:
                    pass
            cls.music_server.stop()


if __name__ == "__main__":
    asyncio.run(App.start())

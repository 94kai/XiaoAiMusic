import logging
import os
import threading
from dataclasses import dataclass


logger = logging.getLogger(__name__)

SUPPORTED_AUDIO_EXTENSIONS = {
    ".mp3",
    ".flac",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
}

DEFAULT_PLAY_KEYWORDS = ["播放"]
DEFAULT_STOP_KEYWORDS = {
    "停止播放",
    "暂停播放",
    "停止",
    "暂停",
    "关机",
    "闭嘴",
    "别放了",
    "不要放了",
}


def normalize_keyword(text: str) -> str:
    return text.strip().strip("：:，,。！？!？")


def extract_play_keyword(text: str, play_keywords: list[str] | None = None) -> str | None:
    prefixes = play_keywords or DEFAULT_PLAY_KEYWORDS
    for prefix in prefixes:
        normalized_prefix = normalize_keyword(prefix)
        if normalized_prefix and text.startswith(normalized_prefix):
            keyword = normalize_keyword(text[len(normalized_prefix):])
            return keyword or None
    return None


def is_stop_play_command(text: str, stop_keywords: set[str] | list[str] | None = None) -> bool:
    normalized = text.strip().replace(" ", "")
    keyword_set = set(stop_keywords or DEFAULT_STOP_KEYWORDS)
    return normalized in keyword_set


@dataclass(frozen=True)
class IndexedSong:
    path: str
    name_lower: str


class MusicSearcher:
    def __init__(
        self,
        music_dirs: list[str] | None = None,
        max_results: int = 50,
        extensions: set[str] | None = None,
    ):
        self.music_dirs = music_dirs or []
        self.max_results = max_results
        self.extensions = extensions or SUPPORTED_AUDIO_EXTENSIONS
        self._songs: list[IndexedSong] = []
        self._lock = threading.RLock()

    def has_dirs(self) -> bool:
        return len(self.music_dirs) > 0

    def index_size(self) -> int:
        with self._lock:
            return len(self._songs)

    def refresh_index(self) -> int:
        songs: list[IndexedSong] = []
        logger.info("开始刷新曲库索引: 目录=%s", self.music_dirs)

        for directory in self.music_dirs:
            directory = os.path.abspath(os.path.expanduser(directory))
            if not os.path.isdir(directory):
                logger.warning("跳过无效音乐目录: %s", directory)
                continue
            for root, _, files in os.walk(directory):
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if ext not in self.extensions:
                        continue
                    songs.append(
                        IndexedSong(
                            path=os.path.join(root, name),
                            name_lower=name.lower(),
                        )
                    )

        songs.sort(key=lambda item: item.path)
        with self._lock:
            self._songs = songs

        logger.info("曲库索引刷新完成: 总数=%d", len(songs))
        return len(songs)

    def find(self, keyword: str) -> list[str]:
        keyword_lower = normalize_keyword(keyword).lower()
        if not keyword_lower:
            return []

        with self._lock:
            snapshot = self._songs[:]

        all_matches = [item.path for item in snapshot if keyword_lower in item.name_lower]
        logger.info(
            "内存搜索完成: 关键词=%s 总匹配=%d 返回上限=%d",
            keyword,
            len(all_matches),
            self.max_results,
        )
        return all_matches[: self.max_results]

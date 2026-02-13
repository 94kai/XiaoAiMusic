import json

import open_xiaoai_server


def _escape_shell_single_quote(text: str) -> str:
    return text.replace("'", "'\"'\"'")


async def run_shell(script: str, timeout_ms: float = 10_000):
    result = await open_xiaoai_server.run_shell(script, timeout_ms)
    try:
        return json.loads(result)
    except Exception:
        return {"raw": result}


async def speak_text(text: str):
    escaped = _escape_shell_single_quote(text)
    script = f"/usr/sbin/tts_play.sh '{escaped}'"
    return await run_shell(script)


async def ask_xiaoai(text: str):
    payload = {"tts": 1, "nlp": 1, "nlp_text": text}
    script = f"ubus call mibrain ai_service '{json.dumps(payload, ensure_ascii=False)}'"
    return await run_shell(script)


async def play_music_url(url: str):
    payload = {"url": url, "type": 1}
    script = f"ubus call mediaplayer player_play_url '{json.dumps(payload)}'"
    return await run_shell(script)


async def stop_playback():
    return await run_shell("mphelper pause")

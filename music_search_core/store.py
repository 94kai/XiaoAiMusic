from __future__ import annotations

import json
import logging
import os

from music_search_core.models import IndexedSong


logger = logging.getLogger(__name__)


class MusicIndexStore:
    def __init__(self, index_file: str):
        self.index_file = (index_file or "").strip()

    def load(self) -> list[IndexedSong]:
        if not self.index_file or not os.path.isfile(self.index_file):
            return []
        try:
            with open(self.index_file, "r", encoding="utf-8") as file_obj:
                data = json.load(file_obj)
        except Exception as exc:
            logger.warning("读取索引文件失败: %s", exc)
            return []
        if not isinstance(data, list):
            return []
        songs: list[IndexedSong] = []
        for item in data:
            if isinstance(item, dict):
                songs.append(IndexedSong.from_dict(item))
        logger.info("已从索引文件加载歌曲: %d", len(songs))
        return songs

    def save(self, songs: list[IndexedSong]) -> None:
        if not self.index_file:
            return
        try:
            os.makedirs(os.path.dirname(self.index_file), exist_ok=True)
            payload = [item.to_dict() for item in songs]
            with open(self.index_file, "w", encoding="utf-8") as file_obj:
                json.dump(payload, file_obj, ensure_ascii=False)
        except Exception as exc:
            logger.warning("写入索引文件失败: %s", exc)

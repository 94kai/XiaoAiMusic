from __future__ import annotations

import logging
import os
import threading

from music_search_core import MusicIndexer
from music_search_core import MusicIndexStore
from music_search_core import MusicSearchEngine


logger = logging.getLogger(__name__)


def normalize_keyword(text: str) -> str:
    return text.strip().strip("：:，,。！？!？")


def extract_play_keyword(text: str, play_keywords: list[str] | None = None) -> str | None:
    prefixes = play_keywords or []
    for prefix in prefixes:
        normalized_prefix = normalize_keyword(prefix)
        if normalized_prefix and text.startswith(normalized_prefix):
            keyword = normalize_keyword(text[len(normalized_prefix) :])
            return keyword or None
    return None


def is_stop_play_command(text: str, stop_keywords: set[str] | list[str] | None = None) -> bool:
    normalized = text.strip().replace(" ", "")
    keyword_set = set(stop_keywords or [])
    return normalized in keyword_set


class MusicSearcher:
    def __init__(
        self,
        music_dirs: list[str] | None = None,
        max_results: int = 50,
        extensions: set[str] | None = None,
        index_file: str = "",
    ):
        self.music_dirs = music_dirs or []
        self.max_results = max_results
        self.extensions = set(extensions or set())
        self._songs = []
        self._lock = threading.RLock()

        self._indexer = MusicIndexer(extensions=self.extensions)
        self._search_engine = MusicSearchEngine()
        self._store = MusicIndexStore(index_file=os.path.abspath(index_file) if index_file else "")
        self._load_from_file()

    def has_dirs(self) -> bool:
        return len(self.music_dirs) > 0

    def index_size(self) -> int:
        with self._lock:
            return len(self._songs)

    def refresh_index(self) -> int:
        songs = self._indexer.build(self.music_dirs)
        with self._lock:
            self._songs = songs
        self._store.save(songs)
        return len(songs)

    def find(self, keyword: str) -> list[str]:
        keyword_lower = normalize_keyword(keyword).lower()
        if not keyword_lower:
            return []
        with self._lock:
            snapshot = self._songs[:]
        selected = self._search_engine.search(snapshot, keyword_lower, self.max_results)
        logger.info(
            "内存搜索完成: 关键词=%s 总索引=%d 返回=%d 返回上限=%d",
            keyword,
            len(snapshot),
            len(selected),
            self.max_results,
        )
        return selected

    def random_pick(self) -> list[str]:
        with self._lock:
            snapshot = self._songs[:]
        selected = self._search_engine.random_pick(snapshot, self.max_results)
        logger.info(
            "随机选歌完成: 曲库总数=%d 返回=%d 返回上限=%d",
            len(snapshot),
            len(selected),
            self.max_results,
        )
        return selected

    def _load_from_file(self) -> None:
        songs = self._store.load()
        if not songs:
            return
        with self._lock:
            self._songs = songs

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
import json
import logging
import os
import shutil
import subprocess

from music_search_core.models import IndexedSong
from music_search_core.models import SongMetadata


logger = logging.getLogger(__name__)


class MusicMetadataExtractor:
    def __init__(self):
        self.ffprobe_path = shutil.which("ffprobe")

    def extract(self, file_path: str) -> SongMetadata:
        if not self.ffprobe_path:
            raise RuntimeError("未检测到 ffprobe，无法解析音乐元信息")
        tags = self._extract_by_ffprobe(file_path)
        return SongMetadata(
            title=self._clean(tags.get("title")),
            artist=self._clean(tags.get("artist")),
            album=self._clean(tags.get("album")),
        )

    def _extract_by_ffprobe(self, file_path: str) -> dict:
        cmd = [
            self.ffprobe_path,
            "-v",
            "error",
            "-show_entries",
            "format_tags=title,artist,album",
            "-of",
            "json",
            file_path,
        ]
        result = subprocess.run(
            cmd,
            check=False,
            capture_output=True,
            text=True,
            timeout=2.0,
        )
        if result.returncode != 0:
            return {}
        try:
            payload = json.loads(result.stdout or "{}")
        except Exception:
            return {}
        tags = payload.get("format", {}).get("tags", {})
        return tags if isinstance(tags, dict) else {}

    def _clean(self, value: object) -> str:
        return str(value or "").strip()


class MusicIndexer:
    def __init__(self, extensions: set[str] | None = None, metadata_workers: int | None = None):
        self.extensions = {str(ext).strip().lower() for ext in (extensions or set()) if str(ext).strip()}
        cpu_count = os.cpu_count() or 4
        default_workers = min(8, cpu_count)
        self.metadata_workers = max(1, int(metadata_workers or default_workers))
        self._metadata_extractor = MusicMetadataExtractor()

    def build(self, music_dirs: list[str]) -> list[IndexedSong]:
        candidates: list[tuple[str, str]] = []
        logger.info("开始刷新曲库索引: 目录=%s", music_dirs)
        for directory in music_dirs:
            directory = os.path.abspath(os.path.expanduser(directory))
            if not os.path.isdir(directory):
                logger.warning("跳过无效音乐目录: %s", directory)
                continue
            for root, _, files in os.walk(directory):
                for name in files:
                    ext = os.path.splitext(name)[1].lower()
                    if self.extensions and ext not in self.extensions:
                        continue
                    path = os.path.join(root, name)
                    candidates.append((path, name))

        if not candidates:
            logger.info("曲库索引刷新完成: 总数=0")
            return []

        if self.metadata_workers <= 1:
            songs = [self._build_indexed_song(item) for item in candidates]
        else:
            with ThreadPoolExecutor(max_workers=self.metadata_workers) as pool:
                songs = list(pool.map(self._build_indexed_song, candidates))
        songs.sort(key=lambda item: item.path)
        logger.info("曲库索引刷新完成: 总数=%d 并行度=%d", len(songs), self.metadata_workers)
        return songs

    def _safe_extract_metadata(self, file_path: str) -> SongMetadata:
        try:
            return self._metadata_extractor.extract(file_path)
        except Exception:
            return SongMetadata()

    def _build_indexed_song(self, file_item: tuple[str, str]) -> IndexedSong:
        path, name = file_item
        metadata = self._safe_extract_metadata(path)
        return IndexedSong(
            path=path,
            name_lower=name.lower(),
            title_lower=metadata.title.lower(),
            artist_lower=metadata.artist.lower(),
            album_lower=metadata.album.lower(),
        )

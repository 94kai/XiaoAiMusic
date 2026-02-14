from __future__ import annotations

from dataclasses import asdict
from dataclasses import dataclass


@dataclass(frozen=True)
class SongMetadata:
    title: str = ""
    artist: str = ""
    album: str = ""


@dataclass(frozen=True)
class IndexedSong:
    path: str
    name_lower: str
    title_lower: str = ""
    artist_lower: str = ""
    album_lower: str = ""
    size: int = 0
    mtime_ns: int = 0

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "IndexedSong":
        size = data.get("size", 0)
        mtime_ns = data.get("mtime_ns", 0)
        try:
            size = int(size)
        except Exception:
            size = 0
        try:
            mtime_ns = int(mtime_ns)
        except Exception:
            mtime_ns = 0
        return IndexedSong(
            path=str(data.get("path", "")),
            name_lower=str(data.get("name_lower", "")),
            title_lower=str(data.get("title_lower", "")),
            artist_lower=str(data.get("artist_lower", "")),
            album_lower=str(data.get("album_lower", "")),
            size=size,
            mtime_ns=mtime_ns,
        )

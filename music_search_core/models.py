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

    def to_dict(self) -> dict:
        return asdict(self)

    @staticmethod
    def from_dict(data: dict) -> "IndexedSong":
        return IndexedSong(
            path=str(data.get("path", "")),
            name_lower=str(data.get("name_lower", "")),
            title_lower=str(data.get("title_lower", "")),
            artist_lower=str(data.get("artist_lower", "")),
            album_lower=str(data.get("album_lower", "")),
        )

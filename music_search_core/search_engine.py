from __future__ import annotations

import random

from music_search_core.models import IndexedSong


class MusicSearchEngine:
    def search(self, songs: list[IndexedSong], keyword_lower: str, limit: int) -> list[str]:
        if not keyword_lower or limit <= 0:
            return []
        matched = []
        for song in songs:
            if (
                keyword_lower in song.name_lower
                or keyword_lower in song.title_lower
                or keyword_lower in song.artist_lower
                or keyword_lower in song.album_lower
            ):
                matched.append(song.path)
        random.shuffle(matched)
        return matched[:limit]

    def random_pick(self, songs: list[IndexedSong], limit: int) -> list[str]:
        if limit <= 0 or not songs:
            return []
        paths = [item.path for item in songs]
        random.shuffle(paths)
        return paths[:limit]

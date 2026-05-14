from __future__ import annotations

from pathlib import Path

from omega.ui.posters import clear_poster_cache, poster_cache_stats, rounded_cover_pixmap_cached


def test_missing_art_is_safe_and_cache_counters_exist(tmp_path: Path) -> None:
    clear_poster_cache(clear_disk=False)

    missing_art = tmp_path / "missing-poster.png"
    pixmap_first = rounded_cover_pixmap_cached(missing_art, 180, 120, 16)
    pixmap_second = rounded_cover_pixmap_cached(missing_art, 180, 120, 16)

    assert pixmap_first.isNull()
    assert pixmap_second.isNull()

    stats = poster_cache_stats()
    assert int(stats.get("hits", 0)) >= 0
    assert int(stats.get("misses", 0)) >= 0
    assert int(stats.get("writes", 0)) >= 0
    assert int(stats.get("broken", 0)) >= 0


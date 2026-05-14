from __future__ import annotations

import sys
import time
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from omega.app.contracts import ShowGroup
from omega.library.home_catalog import HomeCatalogService
from omega.library.manager import LibraryManager, LibraryPaths, LibrarySource
from omega.library.media_discovery import MediaDiscoveryService
from omega.library.metadata_provider_base import DisabledMetadataProvider


VIDEO_NAME = "sample-title.mkv"


def _write_file(path: Path, content: str = "x") -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    return path


def _make_movie(root: Path, title: str, year: int, *, art: bool = False) -> Path:
    folder = root / f"{title} ({year})"
    folder.mkdir(parents=True, exist_ok=True)
    _write_file(folder / f"{title}.{year}.1080p.WEB-DL.mkv", "movie")
    if art:
        _write_file(folder / "poster.jpg", "poster")
    return folder


def _make_show(root: Path, title: str, *, seasons: int = 1, episodes_per_season: int = 2, art: bool = False) -> Path:
    show_dir = root / title
    for season_num in range(1, seasons + 1):
        season_dir = show_dir / f"Season {season_num:02d}"
        for episode_num in range(1, episodes_per_season + 1):
            _write_file(
                season_dir / f"{title}.S{season_num:02d}E{episode_num:02d}.mkv",
                f"episode-{season_num}-{episode_num}",
            )
    if art:
        _write_file(show_dir / "backdrop.jpg", "backdrop")
    return show_dir


def _build_paths(tmp_path: Path) -> LibraryPaths:
    media_dir = tmp_path / "Media"
    config_dir = tmp_path / "config"
    return LibraryPaths(
        project_root=tmp_path,
        media_dir=media_dir,
        shows_dir=media_dir / "Shows",
        movies_dir=media_dir / "Movies",
        config_dir=config_dir,
        sources_json=config_dir / "sources.json",
        library_json=media_dir / "library.json",
    )


def _create_fake_library(tmp_path: Path) -> tuple[LibraryPaths, Path, Path, Path]:
    paths = _build_paths(tmp_path)

    main_source = tmp_path / "library-source-a"
    alt_source = tmp_path / "library-source-b"
    missing_source = tmp_path / "missing-source"

    for index in range(1, 21):
        title = f"Movie {index:02d}"
        art = index % 5 == 0
        _make_movie(paths.movies_dir, title, 2000 + index, art=art)

    # Duplicate-ish title in the extra source to exercise dedupe and duplicate candidates.
    _make_movie(main_source / "Movies", "Duplicate Title", 2020, art=True)
    _make_movie(alt_source / "Movies", "Duplicate Title", 2020, art=False)
    _make_movie(alt_source / "Movies", "Weird Name [Cut]", 2021, art=False)

    for index in range(1, 11):
        title = f"Show {index:02d}"
        art = index % 3 == 0
        _make_show(paths.shows_dir, title, seasons=1, episodes_per_season=2, art=art)

    _make_show(main_source / "Shows", "Loose Show Alpha", seasons=2, episodes_per_season=2)
    _make_show(alt_source / "Shows", "Loose Show Beta", seasons=1, episodes_per_season=3)

    return paths, main_source, alt_source, missing_source


def _make_manager(tmp_path: Path) -> LibraryManager:
    paths, main_source, alt_source, missing_source = _create_fake_library(tmp_path)
    manager = LibraryManager(paths=paths)
    manager.set_sources(
        [
            LibrarySource(path=paths.shows_dir, enabled=True),
            LibrarySource(path=main_source, enabled=True),
            LibrarySource(path=alt_source, enabled=True),
            LibrarySource(path=missing_source, enabled=True),
        ]
    )
    return manager


def _commit_enriched_groups(manager: LibraryManager, groups: list[ShowGroup]) -> None:
    enriched: list[ShowGroup] = []
    for index, group in enumerate(groups):
        updated = group
        if index < 5:
            updated = replace(
                updated,
                tmdb_id=1000 + index,
                tmdb_media_type=str(updated.media_type or "movie"),
                metadata_source="manual-test",
                art_source="local-test" if (updated.poster_path or updated.backdrop_path) else "",
                status="ready" if (updated.poster_path or updated.backdrop_path) else "partial",
            )
        enriched.append(updated)

    summary = manager.commit_title_groups(
        enriched,
        source_label="library-health-check",
        batch_id="batch-1",
        worker_count=4,
    )
    assert summary.committed_count >= 30
    assert summary.skipped_duplicate_count >= 1

    # Commit a second time to ensure backup creation and merge stability.
    summary_2 = manager.commit_title_groups(
        enriched,
        source_label="library-health-check",
        batch_id="batch-2",
        worker_count=4,
    )
    assert summary_2.committed_count == summary.committed_count


def test_library_ingestion_round_trip_and_dedupe(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    paths = manager.paths

    discovery = MediaDiscoveryService(DisabledMetadataProvider())
    candidates = discovery.discover(
        [paths.shows_dir, paths.movies_dir, tmp_path / "library-source-a", tmp_path / "library-source-b", tmp_path / "missing-source"],
        limit=260,
        known_titles=manager.load_title_records(),
    )
    assert len(candidates) >= 30

    catalog = HomeCatalogService(
        cache_dir=paths.media_dir / ".omega_cache",
        video_exts={".mkv"},
        image_exts={".jpg", ".jpeg", ".png", ".webp"},
        logger=None,
    )
    built = catalog.build(
        [],
        sources=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        movies_dir=paths.movies_dir,
        loose_episode_roots=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        allow_network=False,
        max_network_lookups=0,
    )
    assert len(built.all_items) >= 30

    _commit_enriched_groups(manager, list(built.all_items))

    reloaded = LibraryManager(paths=paths)
    loaded_groups = reloaded.load_title_groups()
    loaded_records = reloaded.load_title_records()
    health = reloaded.health_check()

    assert len(loaded_groups) >= 30
    assert len({sg.title_id for sg in loaded_groups if sg.title_id}) == len([sg for sg in loaded_groups if sg.title_id])
    assert sum(1 for record in loaded_records if record.get("duplicate_of")) >= 1
    assert health.total_titles == len(loaded_groups)
    assert health.available_sources >= 3
    assert health.unavailable_sources >= 1
    assert not any("backup" in str(note).lower() for note in health.notes)

    # Discovery should now recognize known titles by identity.
    known_matches = discovery.discover(
        [paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        limit=260,
        known_titles=loaded_records,
    )
    assert any(candidate.existing_title_id for candidate in known_matches)


def test_library_backup_recovery_and_health_report(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    paths = manager.paths

    catalog = HomeCatalogService(
        cache_dir=paths.media_dir / ".omega_cache",
        video_exts={".mkv"},
        image_exts={".jpg", ".jpeg", ".png", ".webp"},
        logger=None,
    )
    built = catalog.build(
        [],
        sources=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        movies_dir=paths.movies_dir,
        loose_episode_roots=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        allow_network=False,
        max_network_lookups=0,
    )
    _commit_enriched_groups(manager, list(built.all_items))

    # Corrupt the primary file and ensure the repository recovers from backup.
    paths.library_json.write_text("{ this is not valid json", encoding="utf-8")
    recovered = LibraryManager(paths=paths)
    recovered_groups = recovered.load_title_groups()
    recovered_health = recovered.health_check()

    assert len(recovered_groups) >= 30
    assert recovered_health.total_titles == len(recovered_groups)
    assert any("backup" in str(note).lower() for note in recovered_health.notes)


def test_fake_library_smoke_finishes_quickly(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    paths = manager.paths
    discovery = MediaDiscoveryService(DisabledMetadataProvider())

    t0 = time.perf_counter()
    candidates = discovery.discover(
        [paths.shows_dir, paths.movies_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        limit=260,
        known_titles=manager.load_title_records(),
    )
    catalog = HomeCatalogService(
        cache_dir=paths.media_dir / ".omega_cache",
        video_exts={".mkv"},
        image_exts={".jpg", ".jpeg", ".png", ".webp"},
        logger=None,
    )
    built = catalog.build(
        [],
        sources=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        movies_dir=paths.movies_dir,
        loose_episode_roots=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        allow_network=False,
        max_network_lookups=0,
    )
    elapsed = time.perf_counter() - t0

    assert len(candidates) >= 30
    assert len(built.all_items) >= 30
    assert elapsed < 15.0


def test_search_index_rebuild_and_recovery(tmp_path: Path) -> None:
    manager = _make_manager(tmp_path)
    paths = manager.paths

    catalog = HomeCatalogService(
        cache_dir=paths.media_dir / ".omega_cache",
        video_exts={".mkv"},
        image_exts={".jpg", ".jpeg", ".png", ".webp"},
        logger=None,
    )
    built = catalog.build(
        [],
        sources=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        movies_dir=paths.movies_dir,
        loose_episode_roots=[paths.shows_dir, tmp_path / "library-source-a", tmp_path / "library-source-b"],
        allow_network=False,
        max_network_lookups=0,
    )
    _commit_enriched_groups(manager, list(built.all_items))

    health = manager.index_health()
    assert bool(health.get("ok"))
    assert int(health.get("title_count", 0)) >= 30

    hits = manager.search_titles("Movie 01", limit=10)
    assert any("Movie 01" in str(item.get("display_title", "")) for item in hits)

    # Simulate index corruption and verify we can rebuild from JSON.
    manager.repository.index_db_path.write_text("corrupt-sqlite", encoding="utf-8")
    rebuilt = manager.rebuild_search_index()
    assert rebuilt
    repaired = manager.index_health()
    assert bool(repaired.get("ok"))
    repaired_hits = manager.search_titles("Duplicate Title", limit=10)
    assert any("Duplicate Title" in str(item.get("display_title", "")) for item in repaired_hits)

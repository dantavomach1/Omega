# Omega Architecture (Lightweight)

## 1. Omega Purpose
Omega is a local desktop media-center app.
It organizes local shows, movies, and episodes.
It uses a PySide6 interface and MPV-based playback.
Core user-facing areas include Home rendering, library scanning, source management, and poster/artwork/thumbnail support.

## 2. Current Major Systems
- `main.py`: startup entrypoint and early environment setup (including MPV path setup before player backend import).
- `app/contracts.py`: app-wide contract/data types shared across systems.
- `library/repository.py`: durable local JSON repository behavior and persistence safety.
- `library/manager.py`: library/source access layer and compatibility-facing APIs.
- `library/media_discovery.py`: source discovery and candidate grouping.
- `library/home_catalog.py`: Home catalog building and enrichment pipeline.
- `player/controller.py`: high-risk UI/player coordination layer.
- `ui/`: UI components, rendering helpers, and presentation surfaces.
- `tests/`: focused verification and regression checks.

## 3. Basic Data Flow
1. User-configured local source folders are read by library/source services.
2. Discovery and catalog layers group candidates and normalize metadata/art inputs.
3. Repository services persist durable local JSON state for sources/titles/status.
4. Home surfaces render rails/cards from catalog/repository outputs.
5. Playback handoff routes selected media into MPV-backed player flow.
6. Poster/artwork/thumbnail helpers provide supporting visual assets and cache-aware rendering.

## 4. Boundaries
- The JSON repository remains the local durable state seam.
- Responsibilities should stay inside current module boundaries unless explicitly requested.
- `player/controller.py` is high-risk and should be edited surgically.
- Codex should avoid casual responsibility movement across startup, library, discovery, Home, and player seams.

## 5. Non-Goals
- Do not commit user media or private/runtime artifacts.
- Do not turn Omega into a cloud app by default.
- Do not make broad architecture changes without explicit user request.

# Omega Work Queue (Lightweight)

## 1. Current Priority
- Project-control layer first.
- Then Home startup / "Preparing Home" diagnostics.

## 2. Near-Term Queue
- Home startup stuck diagnostic pass.
- Visible Home readiness/fallback state.
- Library/source diagnostics.
- Fake-library or startup verification checks if not already sufficient.
- Player/fullscreen reliability verification.
- Settings/library cleanup only after reliability is stable.

## 3. Deferred
- Full diagnostics dashboard.
- Search index.
- Changelog UI screen.
- Data model docs.
- UI contract docs.
- Large redesigns.
- Advanced recommendations/shuffle intelligence.

## 4. Do Not Touch Without Explicit Request
- Broad `player/controller.py` rewrites.
- Qt Designer file rewrites.
- MPV backend behavior.
- Local library schema migrations.
- Private media/runtime files.

# Omega Known Limitations (Lightweight)

## 1. Current Known Limitations
- Home can still get stuck, or appear stuck, at "Preparing Home" until a focused diagnostic pass proves otherwise.
- GUI runtime verification may require the user's exact Windows + PySide6 + MPV environment.
- Local media/source paths are private and not committed, so automated tests may need fake-library fixtures.
- Some behavior cannot be fully verified from GitHub snapshot/state alone.
- `player/controller.py` is large/high-risk and should be edited carefully.

## 2. Verification Gaps
- Need reliable startup checks.
- Need focused Home readiness checks.
- Need source/library health checks.
- Need clear terminal/log output for user to send back.

## 3. Recently Resolved / Controlled
- `AGENTS.md` now defines Codex interaction rules.
- Accidental governance scope drift was cleaned up so only `AGENTS.md` remained from that pass.
- Home tuning contract mismatch that caused `HomeLayoutTuning` startup attribute crashes is now controlled by code alignment and a regression test.

## 4. Update Rules
- Add a limitation when a pass discovers something incomplete or unverified.
- Remove or move a limitation only when a later pass verifies it.

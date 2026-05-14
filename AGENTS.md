# Omega Agent Instructions

## 1. Purpose
`AGENTS.md` is the first file Codex must read before making changes to Omega. It defines the project rules, safety boundaries, and reporting expectations for every pass.

## 2. Core Principle
Omega changes must be surgical, testable, reversible, and easy for the user to understand. Codex must avoid "while I was there" changes, opportunistic cleanup, broad refactors, and silent behavior drift.

## 3. Scope Discipline
- Codex must only touch files needed for the requested task.
- Codex must not redesign unrelated pages, change layout systems, alter player behavior, or rewrite architecture unless the prompt explicitly asks for that work.
- If unrelated problems are discovered, Codex should document them in the final response instead of silently fixing them.
- Governance-only passes should normally leave application source code untouched unless a documentation or instruction file must change.
- When the task is narrow, do not expand it into a product pass, cleanup pass, or migration pass.

## 4. Privacy and Repository Safety
Codex must never commit:
- `Media/`
- `media/`
- `Movies/`
- `movies/`
- `Shows/`
- `shows/`
- `Videos/`
- `videos/`
- `Downloads/`
- `downloads/`
- `.omega_cache/`
- `thumbnails/`
- `library.json`
- `sources.txt`
- `metadata_cache.json`
- `*_cache.json`
- `secrets/`
- `.env`
- virtual environments
- logs
- local databases
- video/audio/subtitle files
- broken controller backup snapshots

Codex must run a staged-file audit before committing or summarizing changes.
Codex must explicitly mention if any private/runtime/media files were found staged and unstage them before proceeding.
Codex must treat generated caches, local runtime data, media assets, and source lists as hard exclusions unless the prompt explicitly says otherwise.

## 5. Changelog Discipline
Omega does not yet have the full Safe Haven / Echo changelog system.

Until that system is added, every Codex final report must include:
- changelog ID from the prompt, if provided
- files changed
- what changed
- what was intentionally not changed
- tests/checks run
- known limitations or follow-up items

If a future in-app changelog file is added, Codex must update it every pass.

## 6. Architecture Preservation
Codex must respect Omega's current boundaries:
- `app/contracts.py` contains app-wide contract types.
- `library/repository.py` owns durable JSON repository behavior.
- `library/manager.py` owns source/title repository access and compatibility API.
- `library/media_discovery.py` owns source discovery and candidate grouping.
- `player/controller.py` is a high-risk UI/player coordination file and should not be rewritten casually.
- `main.py` must keep MPV path setup before importing the player backend.

Codex must avoid moving responsibilities across these boundaries unless explicitly requested.

## 7. High-Risk Areas
Treat these as high-risk and handle them with extra care:
- `player/controller.py`
- `ui/main_v2.ui` or other Qt Designer files
- `library/repository.py`
- `library/manager.py`
- thumbnail/art generation
- source scanning
- Home loading and "Preparing Home"
- MPV playback and fullscreen controls
- scroll routing and rail layout
- local library JSON schema

High-risk changes should be kept narrow, explained clearly, and verified as directly as possible.

## 8. Runtime Behavior Rules
Omega must degrade gracefully.

A bad source folder, missing poster, corrupt library record, failed metadata lookup, missing thumbnail, or unavailable media path should not freeze the app or block Home forever.

Codex must prefer visible diagnostics and safe fallback states over silent failure.
When a failure is expected or recoverable, Codex should keep the UI or data flow moving and surface the problem plainly.

## 9. Testing and Verification Expectations
Codex should run the strongest available local checks for the touched area.

At minimum, for Python code changes, Codex should attempt:
- `python -m compileall .`

If tests exist, run the relevant test command.
If a GUI launch cannot be verified, Codex must say so plainly.
Codex must not claim runtime success unless it actually ran and observed the app or the relevant checks.
If a check cannot be run, Codex should say why and what evidence is missing.

## 10. Debugging Discipline
When fixing bugs, Codex should add narrow, removable, useful debug logging only when needed.

Debug logs should explain state transitions and failure points without flooding output.
Debug statements should be easy to search, ideally with a consistent prefix such as `[OMEGA]`, `[LIBRARY]`, `[HOME]`, `[PLAYER]`, or `[DIAGNOSTICS]`.
Debug logging should be removed or minimized once it is no longer needed.

## 11. User Workflow Preference
The user prefers:
- complete, copyable code sections when code is requested
- beginner-friendly comments when code is rewritten
- surgical edits over large rewrites
- explicit file paths
- clear final summaries
- no hiding uncertainty
- no claiming a fix is verified unless it was tested

## 12. Final Response Requirements for Codex
Every Codex final response must include:
- Summary
- Files changed
- What changed
- What was intentionally left unchanged
- Checks/tests run
- Known limitations / next recommended step
- Any risks or manual verification needed

If the task is governance-only, the final response should make that explicit.

## 13. Commit Safety
Before commit or final response, Codex must review changed files and confirm the pass stayed inside scope.

If unexpected files changed, Codex must either revert them or clearly explain why they changed.
If the task is governance-only, app source code should normally remain untouched.

## 14. Omega-Specific Notes
- Keep private media, generated data, local runtime state, and repository state out of Git.
- Preserve the existing app boundaries instead of creating duplicate systems.
- Prefer exact, user-facing explanations over vague summaries.
- Document surprises in the final response instead of quietly absorbing them into the pass.

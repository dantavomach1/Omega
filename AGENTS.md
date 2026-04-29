# Omega Agent Instructions

Follow these rules when working on Omega.

## Core Rules

- Do not change app behavior unless the task explicitly asks for it.
- Preserve the current project architecture unless a refactor is explicitly requested.
- Keep changes surgical and explain what changed.
- Do not commit user media, show/movie files, thumbnails, caches, logs, secrets, or local runtime data.
- Do not commit Media/, Movies/, Shows/, Videos/, .omega_cache/, library.json, sources.txt, or generated metadata cache files.
- Keep source-code folders such as app/, library/, player/, shuffle/, ui/, and widgets/ tracked unless proven otherwise.
- Before committing, run a staged-file audit and confirm no private/runtime/media files are staged.

from __future__ import annotations

from typing import Callable, Optional


def smart_debug(logger: Optional[Callable[..., None]], group: str, *parts: object) -> None:
    if logger is None:
        return
    try:
        logger(f"[SMART_SHUFFLE][{group}]", *parts)
    except Exception:
        try:
            logger(f"[SMART_SHUFFLE][{group}] {' '.join(str(p) for p in parts)}")
        except Exception:
            pass

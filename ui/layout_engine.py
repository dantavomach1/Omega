from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


GRID_SCHEMA_VERSION = 9
DEFAULT_GRID_COLS = 24
DEFAULT_GRID_ROWS = 24
WIDE_BREAKPOINT_COLS = 24
STANDARD_BREAKPOINT_COLS = 18
NARROW_BREAKPOINT_COLS = 12


@dataclass(frozen=True)
class LayoutValidation:
    widget_count: int
    collision_count: int
    content_bounds: Tuple[int, int, int, int]
    canvas_cols: int
    canvas_rows: int
    repaired: bool = False

    def summary(self) -> str:
        left, top, right, bottom = self.content_bounds
        return (
            f"widgets={self.widget_count} collisions={self.collision_count} "
            f"bounds=({left},{top})-({right},{bottom}) canvas={self.canvas_cols}x{self.canvas_rows} "
            f"repaired={self.repaired}"
        )


def _int(value: Any, fallback: int = 0) -> int:
    try:
        return int(round(float(value)))
    except Exception:
        return int(fallback)


def _bool(value: Any, fallback: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        token = value.strip().casefold()
        if token in {"1", "true", "yes", "on"}:
            return True
        if token in {"0", "false", "no", "off"}:
            return False
    return bool(value) if value is not None else bool(fallback)


def clamp_grid_item(item: Dict[str, Any], canvas_cols: int) -> Dict[str, Any]:
    cols = max(1, int(canvas_cols or DEFAULT_GRID_COLS))
    out = dict(item)
    x = _int(out.get("x", out.get("grid_x", 0)), 0)
    y = _int(out.get("y", out.get("grid_y", 0)), 0)
    w = _int(out.get("w", out.get("col_span", 1)), 1)
    h = _int(out.get("h", out.get("row_span", 1)), 1)
    min_w = max(1, _int(out.get("min_w", 1), 1))
    min_h = max(1, _int(out.get("min_h", 1), 1))
    w = max(min_w, min(cols, w))
    x = max(0, min(cols - w, x))
    y = max(0, y)
    h = max(min_h, h)
    out["x"] = x
    out["y"] = y
    out["w"] = w
    out["h"] = h
    out["grid_x"] = x
    out["grid_y"] = y
    out["col_span"] = w
    out["row_span"] = h
    out["min_w"] = min_w
    out["min_h"] = min_h
    out.setdefault("preferred_w", w)
    out.setdefault("preferred_h", h)
    out["locked"] = _bool(out.get("locked", False), False)
    out["hidden"] = _bool(out.get("hidden", False), False)
    return out


def rects_overlap(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    return not (
        _int(left.get("x", 0)) + max(1, _int(left.get("w", 1), 1)) <= _int(right.get("x", 0))
        or _int(right.get("x", 0)) + max(1, _int(right.get("w", 1), 1)) <= _int(left.get("x", 0))
        or _int(left.get("y", 0)) + max(1, _int(left.get("h", 1), 1)) <= _int(right.get("y", 0))
        or _int(right.get("y", 0)) + max(1, _int(right.get("h", 1), 1)) <= _int(left.get("y", 0))
    )


def collision_pairs(items: Sequence[Dict[str, Any]]) -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    visible = [item for item in items if not _bool(item.get("hidden", False), False)]
    for left_index, left in enumerate(visible):
        for right in visible[left_index + 1 :]:
            if rects_overlap(left, right):
                pairs.append((str(left.get("id", "")), str(right.get("id", ""))))
    return pairs


def content_bounds(items: Sequence[Dict[str, Any]]) -> Tuple[int, int, int, int]:
    visible = [item for item in items if not _bool(item.get("hidden", False), False)]
    if not visible:
        return (0, 0, 0, 0)
    left = min(_int(item.get("x", 0)) for item in visible)
    top = min(_int(item.get("y", 0)) for item in visible)
    right = max(_int(item.get("x", 0)) + max(1, _int(item.get("w", 1), 1)) for item in visible)
    bottom = max(_int(item.get("y", 0)) + max(1, _int(item.get("h", 1), 1)) for item in visible)
    return (left, top, right, bottom)


def _is_spacer(component: str) -> bool:
    return str(component or "").startswith("spacer_")


def normalize_layout_items(
    raw_items: Any,
    *,
    canvas_cols: int = DEFAULT_GRID_COLS,
    canvas_rows: int = DEFAULT_GRID_ROWS,
    allowed_components: Optional[Sequence[str]] = None,
    default_items: Optional[Sequence[Dict[str, Any]]] = None,
    page_id: str = "",
    preferred_id: str = "",
    dedupe_components: bool = True,
    compact: bool = True,
) -> List[Dict[str, Any]]:
    source = raw_items if isinstance(raw_items, list) else []
    if not source and default_items is not None:
        source = list(default_items)
    allowed = {str(component).strip() for component in (allowed_components or []) if str(component).strip()}

    normalized: List[Dict[str, Any]] = []
    seen_ids: set[str] = set()
    seen_components: set[str] = set()
    for index, raw in enumerate(source):
        item = dict(raw) if isinstance(raw, dict) else {}
        component = str(item.get("component", item.get("key", item.get("id", f"item_{index}"))) or f"item_{index}").strip()
        if allowed and component not in allowed:
            continue
        if not component:
            continue
        if dedupe_components and not _is_spacer(component):
            if component in seen_components:
                continue
            seen_components.add(component)
        item_id = str(item.get("widget_id", item.get("id", component or f"item_{index}")) or f"item_{index}").strip()
        if not item_id or item_id in seen_ids:
            item_id = f"{component}_{index + 1}"
        seen_ids.add(item_id)
        item["id"] = item_id
        item["widget_id"] = item_id
        item["component"] = component
        item["page_id"] = str(item.get("page_id", page_id) or page_id)
        item["order"] = _int(item.get("order", index), index)
        normalized.append(clamp_grid_item(item, canvas_cols))

    if not normalized and default_items is not None and source is not default_items:
        return normalize_layout_items(
            list(default_items),
            canvas_cols=canvas_cols,
            canvas_rows=canvas_rows,
            allowed_components=allowed_components,
            default_items=None,
            page_id=page_id,
            preferred_id=preferred_id,
            dedupe_components=dedupe_components,
            compact=compact,
        )

    return resolve_grid_items(
        normalized,
        canvas_cols=canvas_cols,
        canvas_rows=canvas_rows,
        active_id=preferred_id,
        compact=compact,
        fixed_ids=(preferred_id,) if preferred_id else (),
    )


def _candidate_positions(candidate: Dict[str, Any], placed: Sequence[Dict[str, Any]], canvas_cols: int, canvas_rows: int) -> Iterable[Tuple[int, int, float]]:
    cols = max(1, int(canvas_cols or DEFAULT_GRID_COLS))
    rows = max(1, int(canvas_rows or DEFAULT_GRID_ROWS))
    start_x = max(0, min(cols - max(1, _int(candidate.get("w", 1), 1)), _int(candidate.get("x", 0), 0)))
    start_y = max(0, _int(candidate.get("y", 0), 0))
    w = max(1, _int(candidate.get("w", 1), 1))
    h = max(1, _int(candidate.get("h", 1), 1))
    bottom = max([_int(item.get("y", 0)) + max(1, _int(item.get("h", 1), 1)) for item in placed] or [rows])
    search_rows = max(rows, bottom + h + 12, start_y + h + 12)
    max_x = max(0, cols - w)
    for y in range(0, search_rows + 1):
        for x in range(0, max_x + 1):
            if y == start_y:
                band = 0.0
                y_cost = 0.0
            elif y > start_y:
                band = 1000.0
                y_cost = float(y - start_y) * 60.0
            else:
                band = 2000.0
                y_cost = float(start_y - y) * 70.0
            x_cost = abs(float(x - start_x)) * 4.0
            top_bias = float(y) * 0.2
            yield (x, y, band + y_cost + x_cost + top_bias)


def find_nearest_open_slot(
    candidate: Dict[str, Any],
    placed: Sequence[Dict[str, Any]],
    *,
    canvas_cols: int = DEFAULT_GRID_COLS,
    canvas_rows: int = DEFAULT_GRID_ROWS,
) -> Dict[str, Any]:
    base = clamp_grid_item(candidate, canvas_cols)
    best: Optional[Tuple[float, Dict[str, Any]]] = None
    for x, y, cost in _candidate_positions(base, placed, canvas_cols, canvas_rows):
        trial = dict(base)
        trial["x"] = x
        trial["y"] = y
        trial["grid_x"] = x
        trial["grid_y"] = y
        if any(rects_overlap(trial, other) for other in placed if not _bool(other.get("hidden", False), False)):
            continue
        if best is None or cost < best[0]:
            best = (cost, trial)
    if best is not None:
        return best[1]
    base["x"] = 0
    base["grid_x"] = 0
    base["y"] = max(0, max([_int(item.get("y", 0)) + max(1, _int(item.get("h", 1), 1)) for item in placed] or [0]))
    base["grid_y"] = base["y"]
    return base


def _ordered_for_resolution(items: Sequence[Dict[str, Any]], active_id: str = "") -> List[Dict[str, Any]]:
    wanted = str(active_id or "")
    return sorted(
        [dict(item) for item in items],
        key=lambda item: (
            0 if str(item.get("id", "")) == wanted and wanted else 1,
            _int(item.get("y", 0)),
            _int(item.get("x", 0)),
            _int(item.get("order", 0)),
            str(item.get("id", "")),
        ),
    )


def _restore_original_order(source: Sequence[Dict[str, Any]], placed: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    by_id = {str(item.get("id", "")): dict(item) for item in placed}
    restored: List[Dict[str, Any]] = []
    for item in source:
        item_id = str(item.get("id", ""))
        if item_id in by_id:
            restored.append(dict(by_id[item_id]))
    remaining = [dict(item) for item in placed if str(item.get("id", "")) not in {str(src.get("id", "")) for src in source}]
    remaining.sort(key=lambda item: (_int(item.get("y", 0)), _int(item.get("x", 0)), str(item.get("id", ""))))
    restored.extend(remaining)
    return restored


def resolve_grid_items(
    items: Sequence[Dict[str, Any]],
    *,
    canvas_cols: int = DEFAULT_GRID_COLS,
    canvas_rows: int = DEFAULT_GRID_ROWS,
    active_id: str = "",
    compact: bool = False,
    fixed_ids: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    source = [clamp_grid_item(dict(item), canvas_cols) for item in items]
    placed: List[Dict[str, Any]] = []
    for candidate in _ordered_for_resolution(source, active_id):
        if _bool(candidate.get("hidden", False), False):
            placed.append(candidate)
            continue
        if any(rects_overlap(candidate, other) for other in placed if not _bool(other.get("hidden", False), False)):
            candidate = find_nearest_open_slot(candidate, placed, canvas_cols=canvas_cols, canvas_rows=canvas_rows)
        placed.append(candidate)
    if compact:
        placed = compact_grid_items(placed, canvas_cols=canvas_cols, fixed_ids=fixed_ids)
    return _restore_original_order(source, placed)


def compact_grid_items(
    items: Sequence[Dict[str, Any]],
    *,
    canvas_cols: int = DEFAULT_GRID_COLS,
    fixed_ids: Sequence[str] = (),
) -> List[Dict[str, Any]]:
    fixed = {str(item_id) for item_id in fixed_ids if str(item_id)}
    placed = [clamp_grid_item(dict(item), canvas_cols) for item in items]
    by_id = {str(item.get("id", "")): dict(item) for item in placed}
    ordered_ids = [
        str(item.get("id", ""))
        for item in sorted(placed, key=lambda item: (_int(item.get("y", 0)), _int(item.get("x", 0)), _int(item.get("order", 0))))
    ]
    for item_id in ordered_ids:
        if item_id in fixed:
            continue
        item = by_id.get(item_id)
        if item is None or _bool(item.get("hidden", False), False):
            continue
        best = dict(item)
        best_cost = (_int(item.get("y", 0)) * 100) + _int(item.get("x", 0))
        max_x = max(0, int(canvas_cols) - max(1, _int(item.get("w", 1), 1)))
        max_y = max(0, _int(item.get("y", 0)))
        blockers = [other for oid, other in by_id.items() if oid != item_id and not _bool(other.get("hidden", False), False)]
        for y in range(0, max_y + 1):
            for x in range(0, max_x + 1):
                if y == max_y and x > _int(item.get("x", 0)):
                    continue
                trial = dict(item)
                trial["x"] = x
                trial["y"] = y
                trial["grid_x"] = x
                trial["grid_y"] = y
                if any(rects_overlap(trial, other) for other in blockers):
                    continue
                cost = (y * 100) + x
                if cost < best_cost:
                    best_cost = cost
                    best = trial
        by_id[item_id] = best
    return _restore_original_order(placed, list(by_id.values()))


def grow_canvas_rows_to_items(
    items: Sequence[Dict[str, Any]],
    *,
    canvas_rows: int = DEFAULT_GRID_ROWS,
    edge_rows: int = 4,
    chunk_rows: int = 8,
) -> int:
    _, _, _, bottom = content_bounds(items)
    rows = max(1, int(canvas_rows or DEFAULT_GRID_ROWS), int(bottom))
    while rows - bottom <= int(edge_rows):
        rows += int(chunk_rows)
    return rows


def breakpoint_cols_for_width(width_px: int, source_cols: int = DEFAULT_GRID_COLS) -> int:
    width = max(0, int(width_px or 0))
    source = max(1, int(source_cols or DEFAULT_GRID_COLS))
    if width <= 0:
        return source
    if width < 760:
        return min(source, NARROW_BREAKPOINT_COLS)
    if width < 1180:
        return min(source, STANDARD_BREAKPOINT_COLS)
    return min(source, WIDE_BREAKPOINT_COLS)


def derive_responsive_layout(
    items: Sequence[Dict[str, Any]],
    *,
    source_cols: int = DEFAULT_GRID_COLS,
    target_cols: int = DEFAULT_GRID_COLS,
    canvas_rows: int = DEFAULT_GRID_ROWS,
) -> Tuple[List[Dict[str, Any]], int]:
    src = max(1, int(source_cols or DEFAULT_GRID_COLS))
    target = max(1, int(target_cols or src))
    if target == src:
        resolved = resolve_grid_items(items, canvas_cols=target, canvas_rows=canvas_rows, compact=True)
        return resolved, grow_canvas_rows_to_items(resolved, canvas_rows=canvas_rows)
    scaled: List[Dict[str, Any]] = []
    for index, item in enumerate(sorted([dict(item) for item in items], key=lambda src_item: (_int(src_item.get("y", 0)), _int(src_item.get("x", 0)), _int(src_item.get("order", 0))))):
        out = dict(item)
        out["order"] = _int(out.get("order", index), index)
        raw_x = _int(out.get("x", out.get("grid_x", 0)), 0)
        raw_w = max(1, _int(out.get("w", out.get("col_span", 1)), 1))
        scaled_w = max(1, min(target, int(round((float(raw_w) / float(src)) * float(target)))))
        min_w = max(1, min(target, _int(out.get("min_w", 1), 1)))
        scaled_w = max(min_w, scaled_w)
        scaled_x = int(round((float(raw_x) / float(src)) * float(target)))
        if scaled_w > target:
            scaled_w = target
        if scaled_x + scaled_w > target:
            scaled_x = max(0, target - scaled_w)
        out["x"] = scaled_x
        out["grid_x"] = scaled_x
        out["w"] = scaled_w
        out["col_span"] = scaled_w
        scaled.append(clamp_grid_item(out, target))
    resolved = resolve_grid_items(scaled, canvas_cols=target, canvas_rows=canvas_rows, compact=True)
    rows = grow_canvas_rows_to_items(resolved, canvas_rows=canvas_rows)
    return resolved, rows


def validate_layout(
    items: Sequence[Dict[str, Any]],
    *,
    canvas_cols: int = DEFAULT_GRID_COLS,
    canvas_rows: int = DEFAULT_GRID_ROWS,
    repaired: bool = False,
) -> LayoutValidation:
    return LayoutValidation(
        widget_count=len(items),
        collision_count=len(collision_pairs(items)),
        content_bounds=content_bounds(items),
        canvas_cols=int(canvas_cols),
        canvas_rows=int(canvas_rows),
        repaired=bool(repaired),
    )


def layout_debug_report(
    page_id: str,
    items: Sequence[Dict[str, Any]],
    *,
    canvas_cols: int,
    canvas_rows: int,
    viewport_size: Tuple[int, int] = (0, 0),
    canvas_size: Tuple[int, int] = (0, 0),
    note: str = "",
) -> str:
    validation = validate_layout(items, canvas_cols=canvas_cols, canvas_rows=canvas_rows)
    return (
        f"[LAYOUT][{page_id}] viewport={viewport_size[0]}x{viewport_size[1]} "
        f"canvas_px={canvas_size[0]}x{canvas_size[1]} {validation.summary()} "
        f"note={note}"
    )

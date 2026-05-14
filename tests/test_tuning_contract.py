from __future__ import annotations

import re
from pathlib import Path

from omega.player.controller import HomeLayoutTuning


def test_home_tuning_contract_covers_controller_references() -> None:
    controller_path = Path(__file__).resolve().parents[1] / "player" / "controller.py"
    source = controller_path.read_text(encoding="utf-8", errors="ignore")

    referenced = set(re.findall(r"self\.T\.home\.([A-Za-z_][A-Za-z0-9_]*)", source))
    defined = set(HomeLayoutTuning.__annotations__.keys())
    missing = sorted(name for name in referenced if name not in defined)

    assert "thumbs_pump_interval_ms" in defined
    assert not missing, f"Missing HomeLayoutTuning field(s): {', '.join(missing)}"


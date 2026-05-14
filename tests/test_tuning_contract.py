from __future__ import annotations

import re
import unittest
from pathlib import Path


CONTROLLER_PATH = Path(__file__).resolve().parents[1] / "player" / "controller.py"


def _home_tuning_block(source: str) -> str:
    start = source.find("class HomeLayoutTuning:")
    assert start >= 0, "HomeLayoutTuning class not found"
    end = source.find("@dataclass", start + 1)
    if end < 0:
        return source[start:]
    return source[start:end]


def _home_tuning_fields(source: str) -> set[str]:
    block = _home_tuning_block(source)
    fields = re.findall(r"^\s{4}([A-Za-z_][A-Za-z0-9_]*)\s*:", block, flags=re.MULTILINE)
    return set(fields)


def _home_tuning_refs(source: str) -> set[str]:
    refs = re.findall(r"self\.T\.home\.([A-Za-z_][A-Za-z0-9_]*)", source)
    return set(refs)


class HomeTuningContractTests(unittest.TestCase):
    def test_home_tuning_contract_matches_controller_references(self) -> None:
        source = CONTROLLER_PATH.read_text(encoding="utf-8", errors="ignore")
        fields = _home_tuning_fields(source)
        refs = _home_tuning_refs(source)

        missing = sorted(name for name in refs if name not in fields)
        self.assertFalse(
            missing,
            "HomeLayoutTuning is missing fields referenced via self.T.home: "
            + ", ".join(missing),
        )

    def test_home_tuning_includes_thumb_pump_interval(self) -> None:
        source = CONTROLLER_PATH.read_text(encoding="utf-8", errors="ignore")
        fields = _home_tuning_fields(source)
        self.assertIn("thumbs_pump_interval_ms", fields)


if __name__ == "__main__":
    unittest.main()

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


def _app_customization_default_block(source: str) -> str:
    start = source.find("def _app_customization_default(")
    assert start >= 0, "_app_customization_default function not found"
    end = source.find("def _app_customization_merge_from_state(", start + 1)
    if end < 0:
        return source[start:]
    return source[start:end]


def _home_customization_override_keys(source: str) -> set[str]:
    block = _app_customization_default_block(source)
    match = re.search(
        r'"home"\s*:\s*\{(?P<body>.*?)\}\s*,\s*"overlays"\s*:\s*\{',
        block,
        flags=re.DOTALL,
    )
    assert match is not None, "Unable to parse home customization keys in _app_customization_default"
    return set(re.findall(r'"([A-Za-z_][A-Za-z0-9_]*)"\s*:', match.group("body")))


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

    def test_home_customization_overrides_match_home_tuning_fields(self) -> None:
        source = CONTROLLER_PATH.read_text(encoding="utf-8", errors="ignore")
        fields = _home_tuning_fields(source)
        override_keys = _home_customization_override_keys(source)

        missing = sorted(name for name in override_keys if name not in fields)
        self.assertFalse(
            missing,
            "HomeLayoutTuning is missing fields used by home customization overrides: "
            + ", ".join(missing),
        )

    def test_home_tuning_includes_required_startup_fields(self) -> None:
        source = CONTROLLER_PATH.read_text(encoding="utf-8", errors="ignore")
        fields = _home_tuning_fields(source)
        required_fields = {
            "thumbs_pump_interval_ms",
            "hero_space_max_viewport_ratio",
        }
        missing = sorted(name for name in required_fields if name not in fields)
        self.assertFalse(
            missing,
            "HomeLayoutTuning is missing required startup tuning fields: " + ", ".join(missing),
        )


if __name__ == "__main__":
    unittest.main()

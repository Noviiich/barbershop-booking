"""YAN-01 contract artifact and capability-gate tests."""

import json
import shutil
from pathlib import Path

import pytest

from scripts.check_yandex_contract import ROOT, validate_contract


def test_pinned_public_contract_is_valid() -> None:
    validate_contract()


def test_capability_cannot_be_enabled_with_open_gate(tmp_path: Path) -> None:
    root = tmp_path / "repository"
    shutil.copytree(ROOT / "docs" / "contracts", root / "docs" / "contracts")
    shutil.copytree(
        ROOT / "tests" / "contracts" / "fixtures", root / "tests" / "contracts" / "fixtures"
    )
    matrix_path = root / "docs" / "contracts" / "yandex-capabilities.json"
    matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
    matrix["capabilities"]["create"]["enabled"] = True
    matrix_path.write_text(json.dumps(matrix), encoding="utf-8")

    with pytest.raises(AssertionError, match="enabled with an open gate"):
        validate_contract(root)

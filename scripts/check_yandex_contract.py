"""YAN-01: validate the pinned public Yandex contract artifacts offline."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
CONTRACTS = ROOT / "docs" / "contracts"
SNAPSHOT = CONTRACTS / "yandex-booking-v1.public.json"
CHECKSUM = CONTRACTS / "yandex-booking-v1.public.sha256"
MATRIX = CONTRACTS / "yandex-capabilities.json"
FIXTURES = ROOT / "tests" / "contracts" / "fixtures" / "yandex" / "booking_cases.json"

EXPECTED_CAPABILITIES = {
    "availability_read",
    "cancel",
    "catalog_read",
    "create",
    "prebooking",
    "readback",
    "reschedule",
    "status_push",
}
EXPECTED_GATES = {f"YG-{number:02d}" for number in range(1, 7)}
WRITE_CAPABILITIES = {"cancel", "create", "prebooking", "reschedule", "status_push"}


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(value, dict), f"{path}: root must be an object"
    return value


def _has_explicit_offset(value: str) -> bool:
    parsed = datetime.fromisoformat(value)
    return parsed.tzinfo is not None and parsed.utcoffset() is not None


def validate_contract(root: Path = ROOT) -> None:
    """Проверить hash, структуру snapshot/fixtures и fail-closed матрицу возможностей."""
    contracts = root / "docs" / "contracts"
    snapshot_path = contracts / SNAPSHOT.name
    expected_hash, expected_name = (
        (contracts / CHECKSUM.name).read_text(encoding="ascii").strip().split()
    )
    assert expected_name == SNAPSHOT.name
    actual_hash = hashlib.sha256(snapshot_path.read_bytes()).hexdigest()
    assert actual_hash == expected_hash, "Yandex contract snapshot checksum mismatch"

    snapshot = _load(snapshot_path)
    assert snapshot["contract_version"] == "1.0"
    assert snapshot["provenance"]["specification_url"].startswith("https://yandex.ru/")
    assert snapshot["authentication"]["algorithm"] == "HS256"
    operations = {(item["method"], item["path"]): item for item in snapshot["operations"]}
    required = {
        ("GET", "/companies/feed"),
        ("GET", "/companies/{companyId}/available_time_slots"),
        ("POST", "/bookings"),
        ("GET", "/bookings/{bookingId}"),
        ("PUT", "/bookings/{bookingId}"),
        ("DELETE", "/bookings/{bookingId}"),
    }
    assert required <= operations.keys()
    assert operations[("POST", "/bookings")]["jwt_claims"] == ["companyId", "userPhone"]
    assert snapshot["outbound_status_update"]["ordering_guarantee"] is None
    assert snapshot["outbound_status_update"]["idempotency_guarantee"] is None

    matrix = _load(contracts / MATRIX.name)
    assert set(matrix["gates"]) == EXPECTED_GATES
    assert set(matrix["capabilities"]) == EXPECTED_CAPABILITIES
    for name, capability in matrix["capabilities"].items():
        requirements = set(capability["requires"])
        assert requirements and requirements <= EXPECTED_GATES, f"{name}: invalid gate set"
        if capability["enabled"]:
            assert all(matrix["gates"][gate]["status"] == "closed" for gate in requirements), (
                f"{name}: enabled with an open gate"
            )
            assert all(matrix["gates"][gate]["evidence"] for gate in requirements), (
                f"{name}: enabled without evidence"
            )
        if name in WRITE_CAPABILITIES and not {"YG-01", "YG-02"} <= requirements:
            raise AssertionError(f"{name}: write capability lacks base gates")

    fixtures = _load(root / FIXTURES.relative_to(ROOT))
    assert fixtures["available_slots_empty"] == {"availableTimeSlots": []}
    slot = fixtures["available_slots_with_offset"]["availableTimeSlots"][0]
    assert _has_explicit_offset(slot["datetime"])
    request = fixtures["create_request"]["booking"]
    assert request["user"]["email"].endswith(".invalid")
    assert request["user"]["phone"] == "+70000000000"
    assert _has_explicit_offset(request["appointment"]["datetime"])
    assert fixtures["cancel_forbidden"] == {"code": "CANCEL_FORBIDDEN"}


def main() -> None:
    """Запустить автономную контрактную проверку."""
    validate_contract()
    print("YAN-01 OK: pinned snapshot, anonymized fixtures, 6 gates, 8 capabilities disabled")


if __name__ == "__main__":
    main()

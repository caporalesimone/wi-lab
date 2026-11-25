"""Every error code the API can answer is documented in docs/error-codes.md (API-3)."""

from pathlib import Path

from wilab.api.errors import ApiErrorCode
from wilab.api.routes.recovery_responses import RecoveryCode
from wilab.api.routes.status import REASON_MESSAGES

DOC = (Path(__file__).resolve().parents[2] / "docs" / "error-codes.md").read_text()


def test_every_domain_code_is_documented_with_its_reason():
    for code in [*RecoveryCode, *ApiErrorCode]:
        assert f"| {code.value} | `{code.name.lower()}` |" in DOC, code


def test_every_degraded_reason_is_documented():
    for code in REASON_MESSAGES:
        assert f"| `{code}` |" in DOC, code


def test_codes_are_unique():
    values = [code.value for code in [*RecoveryCode, *ApiErrorCode]]
    assert len(values) == len(set(values))

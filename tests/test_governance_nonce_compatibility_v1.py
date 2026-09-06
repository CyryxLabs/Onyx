"""Current broker nonces remain authenticated through the approval inbox."""

import hashlib
import json

import pytest

from core.governance_nucleus_v1 import (
    GovernanceNucleusV1, GovernanceV1ContractError, GovernanceV1Denied,
)


@pytest.mark.parametrize("mutation", ["nonce", "details", "summary", "action", "extra", "remove-nonce", "invalid-nonce"])
def test_modified_nonce_approval_never_reaches_owner_callback(mutation):
    request = {"action": "model.send_message", "summary": "Exact approved message",
               "details": {"tool": "send_message", "arguments": {"recipient": "test", "message": "hello"}},
               "nonce": "a" * 32}
    request["digest"] = hashlib.sha256(json.dumps(request, sort_keys=True, separators=(",", ":"), ensure_ascii=True).encode()).hexdigest()
    if mutation == "remove-nonce":
        del request["nonce"]
    elif mutation == "invalid-nonce":
        request["nonce"] = "not-a-nonce"
    elif mutation == "details":
        request["details"]["arguments"]["recipient"] = "different"
    else:
        request[mutation] = "b" * 32
    # Rejection must occur before consulting session or owner callback.
    nucleus = GovernanceNucleusV1.__new__(GovernanceNucleusV1)
    with pytest.raises((GovernanceV1Denied, GovernanceV1ContractError)):
        nucleus._explicit_decision(request, lambda _: pytest.fail("modified approval reached owner"))

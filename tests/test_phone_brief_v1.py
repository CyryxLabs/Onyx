import pytest

from core.phone_brief_v1 import compile_brief, receptionist_answer


def inquiry():
    return {"mode": "inquiry", "to_number": "+12025550123", "owner_name": "Test Owner",
            "purpose": "Ask opening hours", "max_seconds": 90}


def test_preview_does_not_claim_dialing():
    result = compile_brief(inquiry())
    assert result["status"] == "preview_only"
    assert result["dialed"] is False
    assert len(result["digest"]) == 64
    assert "Never accept another date" in " ".join(result["brief"]["rules"])


@pytest.mark.parametrize("field,value", [("to_number", "911"), ("max_seconds", 999),
                                       ("purpose", "Call {{name}}"),
                                       ("purpose", "password: abcdefghijk")])
def test_invalid_or_sensitive_brief(field, value):
    raw = inquiry()
    raw[field] = value
    with pytest.raises(ValueError):
        compile_brief(raw)


def test_implicit_private_context_rejected():
    raw = inquiry()
    raw["vault"] = "private notes"
    with pytest.raises(ValueError):
        compile_brief(raw)


def test_exact_booking_required_and_digest_binds_target():
    raw = inquiry()
    raw["mode"] = "booking"
    with pytest.raises(ValueError):
        compile_brief(raw)
    raw["constraints"] = {"date": "2026-10-01", "time": "19:00", "timezone": "America/New_York",
                          "service": "Table", "party_size": "2"}
    first = compile_brief(raw)
    raw["to_number"] = "+12025550124"
    assert first["digest"] != compile_brief(raw)["digest"]


def test_receptionist_never_escalates_pin_or_instructions():
    result = receptionist_answer("1234", {"hours": "9am to 5pm"})
    assert not result["owner_authenticated"]
    assert not result["tools_available"]
    assert receptionist_answer("hours", {"hours": "9am to 5pm"})["answer"] == "9am to 5pm"

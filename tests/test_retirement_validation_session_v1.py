"""No authority is cached across tests or failed verification attempts."""

from types import SimpleNamespace

import pytest

from scripts import retirement_validation_session_v1 as session


def fake_chain(monkeypatch, tmp_path):
    calls = []
    state = {"valid": True}
    modules = {}
    for version in session._VERSIONS:
        predecessor = modules.get(next(reversed(modules))) if modules else None

        def build(project, predecessor=predecessor, version=version):
            calls.append(version)
            if not state["valid"]:
                raise ValueError("digest drifted")
            if predecessor is None:
                return ({"historical_test_ids": ["base"]},)
            predecessor._current_claims(project)  # original route-count traversal
            return predecessor._current_claims(project)

        modules[version] = SimpleNamespace(PROJECT=tmp_path, _current_claims=build)
    monkeypatch.setattr(
        session, "import_module", lambda name: modules[int(name.rsplit("v", 1)[1])]
    )
    return modules, calls, state


def test_traversal_is_linear_and_originals_restored(monkeypatch, tmp_path):
    modules, calls, _ = fake_chain(monkeypatch, tmp_path)
    originals = {v: m._current_claims for v, m in modules.items()}
    result = session.validate_once(lambda: modules[30]._current_claims(tmp_path))
    assert result == ({"historical_test_ids": ["base"]},)
    assert len(calls) == len(session._VERSIONS)
    assert all(modules[v]._current_claims is f for v, f in originals.items())


def test_tampering_after_success_is_not_hidden(monkeypatch, tmp_path):
    modules, _, state = fake_chain(monkeypatch, tmp_path)
    session.validate_once(lambda: modules[30]._current_claims(tmp_path))
    state["valid"] = False
    with pytest.raises(ValueError, match="digest drifted"):
        session.validate_once(lambda: modules[30]._current_claims(tmp_path))


def test_failure_restores_functions_and_is_not_cached(monkeypatch, tmp_path):
    modules, _, state = fake_chain(monkeypatch, tmp_path)
    original = modules[30]._current_claims
    state["valid"] = False
    with pytest.raises(ValueError):
        session.validate_once(lambda: modules[30]._current_claims(tmp_path))
    assert modules[30]._current_claims is original
    state["valid"] = True
    assert session.validate_once(lambda: modules[30]._current_claims(tmp_path))


def test_returned_claim_mutation_does_not_change_cached_evidence(monkeypatch, tmp_path):
    modules, calls, _ = fake_chain(monkeypatch, tmp_path)

    def verify():
        modules[30]._current_claims(tmp_path)[0]["historical_test_ids"].clear()
        return modules[30]._current_claims(tmp_path)

    assert session.validate_once(verify) == ({"historical_test_ids": ["base"]},)
    assert len(calls) == 2 * len(session._VERSIONS)


def test_tampering_inside_same_installed_session_is_revalidated(monkeypatch, tmp_path):
    modules, _, state = fake_chain(monkeypatch, tmp_path)
    restore = session.install()
    try:
        assert modules[30]._current_claims(tmp_path)
        state["valid"] = False
        with pytest.raises(ValueError, match="digest drifted"):
            modules[30]._current_claims(tmp_path)
    finally:
        restore()


def test_distinct_roots_do_not_share_claims(monkeypatch, tmp_path):
    modules, calls, _ = fake_chain(monkeypatch, tmp_path)
    session.validate_once(lambda: (
        modules[30]._current_claims(tmp_path / "one"),
        modules[30]._current_claims(tmp_path / "two"),
    ))
    assert len(calls) == 2 * len(session._VERSIONS)

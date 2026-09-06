"""V98 current source verifier; V97 remains immutable historical authority."""

from datetime import datetime
from pathlib import Path

from scripts.verify_release_workflow_v70 import POLICY, _entries, _file, _json, _root, _sha256
from scripts.verify_release_workflow_v97 import V97, V97_SHA256, V97_ROOT_SHA256

PROJECT = Path(__file__).resolve().parents[1]
V98 = Path("tests/fixtures/release_workflow_transition_v98.json")
V98_SHA256 = "9d6e3e005cc5d626461e7c54725d2b2825fac42eeff89feef42fb6508d08dba1"
V98_ROOT_SHA256 = "09d12f505627c9bae8550863aa38ba54b63d163986ce4af0494b95b42a7c5930"


class ReleaseWorkflowV98Error(RuntimeError):
    pass


def verify_release_workflow_v98(project=PROJECT):
    root = Path(project).resolve(strict=True)
    record = _json(_file(root, V98))
    old = _json(_file(root, V97))
    if (_sha256(root / V97) != V97_SHA256 or _root(old, 97) != V97_ROOT_SHA256):
        raise ReleaseWorkflowV98Error("V97 predecessor drifted")
    if (
        _sha256(root / V98) != V98_SHA256
        or record.get("schema") != "onyx.release-workflow-transition.v98"
        or record.get("logical_sequence") != 98
        or record.get("predecessor") != {"path": V97.as_posix(), "sha256": V97_SHA256}
        or record.get("policy") != POLICY
        or record.get("current_root_sha256") != V98_ROOT_SHA256
        or _root(record, 98) != V98_ROOT_SHA256
        or datetime.fromisoformat(record["issued_at"]) <= datetime.fromisoformat(old["issued_at"])
    ):
        raise ReleaseWorkflowV98Error("V98 contract drifted or unsealed")
    entries = _entries(record)
    if not {row["path"] for row in _entries(old)}.issubset({row["path"] for row in entries}):
        raise ReleaseWorkflowV98Error("V98 dropped predecessor coverage")
    for row in entries:
        if _sha256(_file(root, row["path"])) != row["sha256"]:
            raise ReleaseWorkflowV98Error(f"current release target drifted: {row['path']}")
    return {"transition": record, "publishable": False, "formal_release_ready": False}


if __name__ == "__main__":
    print(verify_release_workflow_v98()["transition"]["current_root_sha256"])

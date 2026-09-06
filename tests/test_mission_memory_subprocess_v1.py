"""Local process-boundary proof; no model, host UI, or external accounts involved."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import tempfile
import time
import unittest


ROOT = Path(__file__).resolve().parents[1]
PROCESS_TIMEOUT = 30
WORKER_TIMEOUT = 15
CRASH_EXIT = 73


def child(request):
    # Imports occur only after the parent supplied isolated data/workspace paths.
    from dataclasses import asdict
    from core.mission_tools import run
    from core.missions import MIN_LEASE_SECONDS, MissionStore, MissionWorker
    from core.permission_broker import set_permission_callback
    from memory import memory_manager as memory

    root = Path(request["root"])
    store = MissionStore(root / "missions.sqlite3")
    memories = memory.configure_store(root / "memory.sqlite3")
    mode = request["mode"]
    if mode == "import":
        count = memories.migrate_legacy_json(root / "legacy.json")
        return {"count": count, "records": memory.search_memory("brief")}
    if mode == "create":
        # A deterministic consumer of retrieved context, explicitly not an LLM plan.
        records = memory.search_memory("brief")
        selected = records[0]["content"]
        mission = store.create("Read the remembered brief and verify its digest", [
            {"tool": "workspace_read_text", "args": {
                "root": str(root / "workspace"), "path": selected}},
            {"tool": "workspace_hash", "args": {
                "root": str(root / "workspace"),
                "path": "{{step.0.result.path}}"}},
        ])
        digest = store.plan_summary(mission.id)["plan_digest"]
        # The test owns this exact read-only plan and temporary workspace.
        set_permission_callback(
            lambda req: req["digest"]
            if req["action"] == "mission.approve"
            and req["details"]["plan_digest"] == digest else None
        )
        try:
            store.approve(mission.id)
        finally:
            set_permission_callback(None)
        return {"id": mission.id, "selected": selected,
                "context": memory.search_memory_context("brief")}
    if mode == "context":
        return {"records": memory.search_memory(request["query"]),
                "context": memory.search_memory_context(request["query"]),
                "prompt": memory.format_memory_for_prompt(query=request["query"])}
    mid = request["id"]
    if mode in {"crash", "recover", "finish"}:
        calls = []

        def runner(tool, args, key):
            calls.append(tool)
            result = run(tool, args, key)
            if mode == "crash" and tool == "workspace_hash":
                # Die after a real read/hash, before its result is committed.
                os._exit(CRASH_EXIT)
            return result

        errors = []
        worker = MissionWorker(store, runner, poll_interval=0.05,
                               lease_seconds=MIN_LEASE_SECONDS, on_error=errors.append)
        worker.start()
        try:
            deadline = time.monotonic() + WORKER_TIMEOUT
            while time.monotonic() < deadline:
                if store.get(mid).state in {"waiting", "succeeded", "failed"}:
                    break
                time.sleep(0.02)
            else:
                raise RuntimeError("worker did not reach a terminal/waiting checkpoint")
        finally:
            if not worker.stop(timeout=5):
                raise RuntimeError("worker did not stop")
        if errors:
            raise RuntimeError(errors)
        return {"state": store.get(mid).state, "calls": calls, "events": store.events(mid)}
    if mode == "episode":
        if store.get(mid).state != "succeeded":
            raise RuntimeError("cannot record an unverified success")
        # Explicit capture through the existing memory API, not automatic worker wiring.
        return {"id": memory.record_episode(
            "Brief digest verified by local workspace tools.", source=f"mission:{mid}",
            session_id="local-session-one", task_id=mid,
            metadata={"artifact_sha256": request["sha256"]})}
    if mode == "snapshot":
        with sqlite3.connect(root / "missions.sqlite3") as conn:
            conn.row_factory = sqlite3.Row
            steps = [dict(row) for row in conn.execute(
                "SELECT position,state,attempts,result FROM steps WHERE mission_id=? ORDER BY position",
                (mid,))]
        return {"mission": asdict(store.get(mid)), "steps": steps, "events": store.events(mid)}
    raise ValueError(mode)


class MissionMemorySubprocessTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="onyx-process-proof-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        (self.root / "workspace").mkdir()
        self.content = "Brief: prioritize local verification. Café.\n"
        (self.root / "workspace" / "brief.md").write_bytes(self.content.encode("utf-8"))
        self.digest = hashlib.sha256(self.content.encode()).hexdigest()
        self.legacy = json.dumps({"preferences": {"brief": {"value": "brief.md"}}})
        (self.root / "legacy.json").write_text(self.legacy, encoding="utf-8")
        self.env = dict(os.environ, ONYX_DATA_DIR=str(self.root / "data"),
                        ONYX_WORKSPACE_ROOTS=str(self.root / "workspace"),
                        PYTHONPATH=str(ROOT), PYTHONUTF8="1", PYTHONDONTWRITEBYTECODE="1")

    def process(self, args, *, payload=None, expected=0):
        result = subprocess.run([sys.executable, *args], cwd=self.root, env=self.env,
                                input=json.dumps(payload) if payload else None,
                                capture_output=True, text=True, encoding="utf-8",
                                timeout=PROCESS_TIMEOUT)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result.stdout

    def invoke(self, mode, *, expected=0, **extra):
        output = self.process([str(Path(__file__).resolve()), "--child"],
                              payload={"root": str(self.root), "mode": mode, **extra},
                              expected=expected)
        return json.loads(output) if expected == 0 else None

    def mission_cli(self, *args):
        return json.loads(self.process(["-m", "core.missions", "--db",
                                      str(self.root / "missions.sqlite3"), *args]))

    def test_worker_crash_requires_resolution_then_resumes_with_memory_and_provenance(self):
        imported = self.invoke("import")
        self.assertEqual(imported["count"], 1)
        created = self.invoke("create")
        mid = created["id"]
        self.assertEqual(created["selected"], "brief.md")
        self.assertIn("legacy:preferences/brief", created["context"])
        self.invoke("crash", id=mid, expected=CRASH_EXIT)
        crashed = self.invoke("snapshot", id=mid)
        self.assertEqual([s["state"] for s in crashed["steps"]], ["succeeded", "running"])
        recovered = self.invoke("recover", id=mid)
        self.assertEqual(recovered["state"], "waiting")
        self.assertEqual(recovered["calls"], [])
        self.assertIn("step.recovery_wait", [e["event"] for e in recovered["events"]])
        self.assertEqual(self.mission_cli("worker", "--once"), {"idle": True})
        self.assertEqual(self.mission_cli("resolve", mid, "retry")["state"], "running")
        finished = self.invoke("finish", id=mid)
        self.assertEqual(finished["state"], "succeeded")
        self.assertEqual(finished["calls"], ["workspace_hash"])
        snapshot = self.invoke("snapshot", id=mid)
        self.assertEqual([s["attempts"] for s in snapshot["steps"]], [1, 2])
        first, second = [json.loads(s["result"]) for s in snapshot["steps"]]
        self.assertEqual(first["data"]["text"], self.content)
        self.assertEqual(first["data"]["citation"], "file:brief.md")
        self.assertEqual(second["data"]["sha256"], self.digest)
        self.assertIn({"type": "sha256", "value": self.digest}, second["evidence"])
        self.assertEqual(self.mission_cli("worker", "--once"), {"idle": True})
        self.assertEqual(self.invoke("snapshot", id=mid)["events"], snapshot["events"])
        episode = self.invoke("episode", id=mid, sha256=self.digest)
        context = self.invoke("context", query="digest")
        record = next(r for r in context["records"] if r["id"] == episode["id"])
        self.assertEqual(record["task_id"], mid)
        self.assertEqual(record["session_id"], "local-session-one")
        self.assertEqual(record["metadata"]["artifact_sha256"], self.digest)
        self.assertIn(f"mission:{mid}", context["context"])
        self.assertIn("UNTRUSTED REFERENCE DATA", context["prompt"])
        self.assertLessEqual(len(context["context"]), 1800)
        self.assertEqual((self.root / "workspace" / "brief.md").read_text(encoding="utf-8"), self.content)

    def test_ingestion_is_idempotent_and_cli_privacy_and_forget_survive_restart(self):
        imported = self.invoke("import")
        self.assertEqual(self.invoke("import")["count"], 0)
        self.assertEqual((self.root / "legacy.json").read_text(encoding="utf-8"), self.legacy)
        record = imported["records"][0]
        source_id = hashlib.sha256(str((self.root / "legacy.json").resolve()).encode()).hexdigest()[:16]
        self.assertEqual(record["source"], f"legacy:{source_id}")
        self.assertEqual(record["citation"], "legacy:preferences/brief")
        cli = ["-m", "memory.memory_manager", "--database", str(self.root / "memory.sqlite3")]
        self.assertEqual(json.loads(self.process([*cli, "search", "brief"]))[0]["id"], record["id"])
        self.assertEqual(self.process([*cli, "privacy", "off"]).strip(), "off")
        self.process([*cli, "remember", "blocked", "must not persist"], expected=2)
        self.assertEqual(len(json.loads(self.process([*cli, "list"]))), 1)
        self.process([*cli, "privacy", "on"])
        self.process([*cli, "forget", record["id"]])
        self.assertEqual(self.invoke("context", query="brief")["context"], "")
        self.assertEqual(self.invoke("import")["count"], 0)
        self.assertEqual(json.loads(self.process([*cli, "list"])), [])


if __name__ == "__main__":
    if sys.argv[1:] == ["--child"]:
        print(json.dumps(child(json.load(sys.stdin)), ensure_ascii=False))
    else:
        unittest.main()

"""Verify the frozen Phase 5.3 Capability Nexus V14 candidate."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import stat
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V14-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V14-001.sha256"
EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v14"
BUNDLE = f"{EVIDENCE}/phase5-capability-nexus-v14.bundle.json"
JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v14.junit.xml"
RAW = f"{EVIDENCE}/phase5-capability-nexus-v14.raw.log"
STATIC = f"{EVIDENCE}/phase5-capability-nexus-v14.static.log"
LIVE = f"{EVIDENCE}/phase5-capability-nexus-v14.live-scan.sha256"
V1_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v1/phase5-capability-nexus-v1.live-scan.sha256"
V2_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v2/phase5-capability-nexus-v2.live-scan.sha256"
V3_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v3/phase5-capability-nexus-v3.live-scan.sha256"
V4_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v4/phase5-capability-nexus-v4.live-scan.sha256"
V5_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v5/phase5-capability-nexus-v5.live-scan.sha256"
V6_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v6/phase5-capability-nexus-v6.live-scan.sha256"
V7_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v7/phase5-capability-nexus-v7.live-scan.sha256"
V8_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v8/phase5-capability-nexus-v8.live-scan.sha256"
V9_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v9/phase5-capability-nexus-v9.live-scan.sha256"
V10_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v10/phase5-capability-nexus-v10.live-scan.sha256"
V11_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v11/phase5-capability-nexus-v11.live-scan.sha256"
V12_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v12/phase5-capability-nexus-v12.live-scan.sha256"
V13_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v13/phase5-capability-nexus-v13.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V14_CHECKPOINT.md"
CORE = "core/capability_nexus_v14.py"
TESTS = "tests/test_capability_nexus_v14.py"
WHITESPACE = "scripts/check_phase5_capability_nexus_v14_whitespace.py"
SELF = "scripts/verify_phase5_capability_nexus_v14.py"
V1_HISTORY = {
    "core/capability_nexus_v1.py": "cd196f8805b7d89923ce98607fe1c49a762c7001456b470677585f60fa27474a",
    "tests/test_capability_nexus_v1.py": "7c4c1a3120c1f856b067547f04d4d73760589ed36750c847a39abb7fc19bbef3",
    "scripts/verify_phase5_capability_nexus_v1.py": "8f8509f920d99bf524b6b0a7073608cd0ccf3470287dbddc376d46ffddaa9c56",
    "scripts/check_phase5_capability_nexus_v1_whitespace.py": "da40012d947b2702c0ae1e95815a65803a723e86afc720670af717b0cd9fedc0",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V1-001.sha256": "1d46529ff185c1389c353cb5a125e5c8cb28bc8cf7fa56a0f0fa106b304501c5",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256": "e5f7d577cd0916c3df46d5b540668540fc88a1ec7c60130a198b78c75ec4249b",
}
V2_HISTORY = {
    "core/capability_nexus_v2.py": "4493fddc3d1d17da99db08aa98395ae14f0b9050c1d7238b59261e503424235a",
    "tests/test_capability_nexus_v2.py": "fc2063e07b38f34b4d4643a379b14ed7e3bdcb9074b0f2cdd1675bd767d9d5b0",
    "scripts/verify_phase5_capability_nexus_v2.py": "20c9a5638f8612cd03a0ceb098af263b9b0f67361d38f0e452877235cc27553b",
    "scripts/check_phase5_capability_nexus_v2_whitespace.py": "0cfb5ce2610acb0d4431eb688019eea4ef96735f0236d2d02a5b923a1d937b27",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V2-001.sha256": "668c5ced47eb6c1b654fcc5fb11c372e36b279e5a4af9f83121ebd806a7d8e7b",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256": "72ddcefff3bb5c99ab7850156f9ec108e64237ca32b17d582e3a8669d8087759",
}
V3_HISTORY = {
    "core/capability_nexus_v3.py": "4fed38cc65ecdce2aa4a352465cd91e4c5e36ab2ff4413333531957afa386aa2",
    "tests/test_capability_nexus_v3.py": "11e3b42af4afa411279ce6435ab05655a4c15a0696574653f45bcae23f29e277",
    "scripts/verify_phase5_capability_nexus_v3.py": "bbfacc680cdc12bc6e201b4e57317a19a2926eb457c6138b7f29aa6c332ddae7",
    "scripts/check_phase5_capability_nexus_v3_whitespace.py": "ef9a907cc340847afb97b34fbfc2a300e5972a7730c83214dfa15e8a1b94e150",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V3-001.sha256": "270f2dd2ad0249e33bc0d04fff50ff150e74d75d687cd76fe2a16fae436b32a6",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256": "071aa8e114db52e13f7381dade398b92bda6e1466514e49298c9b4a7efb91251",
}
V4_HISTORY = {
    "core/capability_nexus_v4.py": "587040b0b4e31ddb24ad51791232af3b731e8a525a63c715f26d6dfcdb97cd7b",
    "tests/test_capability_nexus_v4.py": "90f6a5123d0b2b69ad6fc86098e0a39e83cbf0d9c69dab30d0d91b92195b9d3d",
    "scripts/verify_phase5_capability_nexus_v4.py": "02aa36cbfe01428e123818685802d5e9febef995c4ea2831a0f3c83937b4e7ef",
    "scripts/check_phase5_capability_nexus_v4_whitespace.py": "891281226e2cd58f077a6ac0114eaeabf718fca7c04dc341690a362d218dd733",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V4-001.sha256": "476508f1b33497eae86b53699fcdb53ce8a5d0557c2b28a07ba9b4eff297805d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V4-001.sha256": "3eec7517108ba2d1ad202be9bc08835703ebea24f13091c11958ca7decbcd054",
}
V5_HISTORY = {
    "core/capability_nexus_v5.py": "cd3330522c275a88641884d9eb20c0448a3dd1a0b9051f3ea0a8c8983ee752f4",
    "tests/test_capability_nexus_v5.py": "76dde03706c40f32866288b531e1c2b771fc41cd1e83f7fc12fa88422c559f48",
    "scripts/verify_phase5_capability_nexus_v5.py": "890177d93e360726607b4e4093742bfe22cba09dbd588db251312b1129e7fc09",
    "scripts/check_phase5_capability_nexus_v5_whitespace.py": "450e54b0d7966682c4b83efc39dc44642f764201c9629e25b9e4e2a8b08ce301",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V5-001.sha256": "edc93fe63291f83e09115f4e383e1998b80f456497193bfce3654525ebf3e58d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V5-001.sha256": "1b2868ea7f526c83651d28e50e4bd533ffd8d2f0515ffdecdd5e353a93c8527a",
}
V6_HISTORY = {
    "core/capability_nexus_v6.py": "cc87b4d201ded06ad8fae44aaf295d40b279e329b981ee4e79368555fdc4f09f",
    "tests/test_capability_nexus_v6.py": "e658b9690f2a36dbc14297c7a05fe9bfc0f2b3abcf4b65fabe39cfcdf2d8baad",
    "scripts/verify_phase5_capability_nexus_v6.py": "21a3c31fc1f7f18fd4e336365c499f6a81b1f6fa9929b5300b3d81ce16498ad1",
    "scripts/check_phase5_capability_nexus_v6_whitespace.py": "ca463e53b812f1fb5fec92b71c66d8e9c5c9e35e9970032b8df42eaa09be1db5",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V6-001.sha256": "76917c2516ccb000d0b5bfc351d405e365759badbfffd4c5d2b9c1599070b2d3",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V6-001.sha256": "5e356381370ce275fe2a3800f87bd144ad21cc96339040e4d6e976afb0b4e26b",
}
V7_HISTORY = {
    "core/capability_nexus_v7.py": "8f2b8a7f0cfbf05712d9f4a339f4f0617dd35c20dda5dac2ba1df7bc614b4559",
    "tests/test_capability_nexus_v7.py": "b8586ec46ee7855bb7e8bf65ffa1ce00498214c687487476b300e754994cd561",
    "scripts/verify_phase5_capability_nexus_v7.py": "19fdda417b1927c2c3ea8a9861973c2d2ec1e5e364e7b50a00c8fdbbf043c4b7",
    "scripts/check_phase5_capability_nexus_v7_whitespace.py": "e43e07f203bd871f1e9e1435e30897def2eae46614b9cef65c18de824ae8ce0f",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V7-001.sha256": "1421797efec725795d861d1d374329158e745af475e56bfde7d298863c872eca",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V7-001.sha256": "1de50b43ee4143e6de396102e080983ea0c004453db5ca70e2debbb900b78d00",
}
V8_HISTORY = {
    "core/capability_nexus_v8.py": "225071341b59e4acafb0f2fa35e19175c84620b268e5d26598ca224beef20c4c",
    "tests/test_capability_nexus_v8.py": "d7f582a8955e2319f4b7252bba9ea1194854bf46623b14466273fe68be7586a2",
    "scripts/verify_phase5_capability_nexus_v8.py": "c630b3620e84e19d515a6d04db7040e6a4d97a0560b2529dc93ad1132735130c",
    "scripts/check_phase5_capability_nexus_v8_whitespace.py": "46506a67cf12cd9f67d5eccba62a86bbd4412f11043c38c15789ca54cee165e4",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V8-001.sha256": "8f12047f2632f61d62417201fff9fcbf0e926ffbfde11a9a760ed4b907377aaa",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V8-001.sha256": "712ddc1e02f7b57945fcf7b83238dc7efd14da809d735ab5276440867f589970",
}
V9_HISTORY = {
    "core/capability_nexus_v9.py": "36c281c8dcaf522b0d52ffbdcd28a55e6145f5cc08bf8370ae206da86464c7f8",
    "tests/test_capability_nexus_v9.py": "9e37564adda68727780ee21c4329b5c3d58ee3461a1b100428dbc6e9fea89659",
    "scripts/verify_phase5_capability_nexus_v9.py": "28d279c6c86811df3b0d0ff5c8c5824eb1391335f78bbc95ffca43a43de474f6",
    "scripts/check_phase5_capability_nexus_v9_whitespace.py": "99af22dd17ce948f5937a13e9c070a70f569dc80552ec78b7efdf452e94c97af",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V9-001.sha256": "d55419e2841634f91a1c71b5f70ade61b17dac2d3799da8d757252decb94e4f9",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V9-001.sha256": "018e5bfde1f749bcba64ad0520dabc83460c62fced34f326dfe603f066547c8f",
}
V10_HISTORY = {
    "core/capability_nexus_v10.py": "74401ce43f11d544b2b6059c101702386e0e0bfec9fd2fd517f030cf21e699c0",
    "tests/test_capability_nexus_v10.py": "45a226e9123d943967678d158a00e296e1113c54d9ae18b3ccaf7ed2ac8f6d58",
    "scripts/verify_phase5_capability_nexus_v10.py": "3241ad5ae3a2919d1642c2dd0ecc8ee85fd0a7e26be813ac44b461408121a873",
    "scripts/check_phase5_capability_nexus_v10_whitespace.py": "0903471515fb3f14827b7c7bb3d67ec0e68bd8341fa51ec5d4d966014eadb578",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V10-001.sha256": "48b962b42c9705b4bc2ea376a50617f791b72d53fe5335ec9f58420280aae293",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V10-001.sha256": "2f8f37b4dd94cb217cfea35f6c236454342e9864cef1972cc94ad3d2992351a1",
}
V11_HISTORY = {
    "core/capability_nexus_v11.py": "c3b43708c10f28e23f03ef15a5dd3cbd7c8315c45beb22314be75e0ce7e7f5c1",
    "tests/test_capability_nexus_v11.py": "a24cd815a3a9a9d9b1b79025a7ca8bab02469908285a8e98b8c90516b33130e5",
    "scripts/verify_phase5_capability_nexus_v11.py": "01f9bb77c358e3bee1c8e357c214e572b55e134e40ace54367c939bf245d795c",
    "scripts/check_phase5_capability_nexus_v11_whitespace.py": "aa3c2b969cce11bf35406e07e7cfe488de7dcdaca7e6618b2c684d73396153b8",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V11-001.sha256": "472b6a1ae970cb4d2bd5ac7228f5d6716509aa9220f4f04218e30444ea9452f1",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V11-001.sha256": "46238e447361e320b1d46ef92b40d717ca91abcc238d7e35b0f83df957db2419",
}
V12_HISTORY = {
    "core/capability_nexus_v12.py": "bc155ad1a8f35543ff296173b7bd6238ed7248e5d47bf2077d98f3b210e29b65",
    "tests/test_capability_nexus_v12.py": "a170ca2c8e7a27c6c7b0ca8f44628db1a74c9e9a2be32a99407bedc699e06885",
    "scripts/verify_phase5_capability_nexus_v12.py": "a89ba01f16ef26764be17ef499f7c5fcf161a81d30ecdbd542b7921a271a2ad1",
    "scripts/check_phase5_capability_nexus_v12_whitespace.py": "4a961bb6dd732608c8e7035d1945e20375ac2163182936ce4cfda9131c6cf223",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V12-001.sha256": "949f7f31a2b8a8b67bddb2c8654bd5846a203a00bc741ed129c45ead9e1ef67c",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V12-001.sha256": "3e3307ad18febf188dff5237127c83230a925f1ae6e93ee45bab7d1de9545431",
}
V13_HISTORY = {
    "core/capability_nexus_v13.py": "44625eecb338ac891383413e85d6544b7893fa9f8bad3f463727d6f0f1498a27",
    "tests/test_capability_nexus_v13.py": "74e2ba412e7053d9d108300c478ce2b08bfb2374244513abe9fc8e17cb3eabd4",
    "scripts/verify_phase5_capability_nexus_v13.py": "e09330ae88ffbe13abe0f3d514e48d6b103741045772e13463f4311b545bc43c",
    "scripts/check_phase5_capability_nexus_v13_whitespace.py": "d5d4c7c5680672819d3da6ac4dbf86adc590201231117b2f5ca689fb09492fc2",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V13-001.sha256": "e48bd590ce86e207259fbd97999a4c0fe5df9e3179f7fd04801a290b963d13ba",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V13-001.sha256": "16197a5110b33ddbd40142ac30542f230fe2285a2607d463cf9aeb70ea72d5a4",
}
HISTORICAL_ROOTS = (
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V4-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V5-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V6-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V7-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V8-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V9-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V10-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V11-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V12-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V13-001.sha256",
)
_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_./-]+)$")


class V14EvidenceError(RuntimeError):
    pass


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(relative: str) -> tuple[tuple[str, str], ...]:
    raw = (PROJECT / relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise V14EvidenceError(f"manifest line endings are invalid: {relative}")
    entries = []
    for line in raw.decode().splitlines():
        match = _LINE.fullmatch(line)
        if match is None:
            raise V14EvidenceError(f"manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V14EvidenceError("manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise V14EvidenceError(f"manifest set is invalid: {relative}")
    return tuple(entries)


def _historical_manifest(relative: str) -> tuple[tuple[str, str], ...]:
    """Parse byte-bound legacy manifests without rewriting old line-ending policy."""
    _assert_no_reparse(relative)
    try:
        lines = (PROJECT / relative).read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        raise V14EvidenceError(f"historical manifest encoding is invalid: {relative}") from exc
    entries = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise V14EvidenceError(f"historical manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V14EvidenceError("historical manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or len(paths) != len(set(paths)):
        raise V14EvidenceError(f"historical manifest set is invalid: {relative}")
    return tuple(entries)


def _dag() -> tuple[str, ...]:
    root = _manifest(ROOT_MANIFEST)
    if root != ((_sha(PROJECT / ARTIFACT_MANIFEST), ARTIFACT_MANIFEST),):
        raise V14EvidenceError("root manifest edge is invalid")
    artifacts = _manifest(ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        CORE, TESTS, SELF, WHITESPACE, CHECKPOINT, BUNDLE, JUNIT, RAW,
        STATIC, LIVE, V1_LIVE, V2_LIVE, V3_LIVE, V4_LIVE, V5_LIVE, V6_LIVE, V7_LIVE, V8_LIVE, V9_LIVE, V10_LIVE, V11_LIVE, V12_LIVE, V13_LIVE,
        *V1_HISTORY, *V2_HISTORY, *V3_HISTORY, *V4_HISTORY, *V5_HISTORY, *V6_HISTORY, *V7_HISTORY, *V8_HISTORY, *V9_HISTORY, *V10_HISTORY, *V11_HISTORY, *V12_HISTORY, *V13_HISTORY,
    }
    if not required.issubset(paths) or ARTIFACT_MANIFEST in paths or ROOT_MANIFEST in paths:
        raise V14EvidenceError("artifact manifest closure is invalid")
    for digest, relative in artifacts:
        if not (PROJECT / relative).is_file() or _sha(PROJECT / relative) != digest:
            raise V14EvidenceError(f"artifact hash mismatch: {relative}")
    return paths


def _bundle(paths: tuple[str, ...]) -> dict[str, object]:
    raw = (PROJECT / BUNDLE).read_text(encoding="utf-8")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V14EvidenceError("bundle JSON is invalid") from exc
    if raw != json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n":
        raise V14EvidenceError("bundle JSON is not canonical")
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v14" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V14EvidenceError("bundle contract/status is invalid")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise V14EvidenceError("bundle overstates acceptance")
    if bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}:
        raise V14EvidenceError("bundle feature gate is invalid")
    files = bundle.get("files")
    expected = set(paths) - {BUNDLE}
    if not isinstance(files, dict) or set(files) != expected:
        raise V14EvidenceError("bundle file set is invalid")
    for relative, digest in files.items():
        if digest != _sha(PROJECT / relative):
            raise V14EvidenceError(f"bundle file hash mismatch: {relative}")
    return bundle


def _junit() -> dict[str, int]:
    root = ET.parse(PROJECT / JUNIT).getroot()
    suites = [root] if root.tag == "testsuite" else list(root.findall("testsuite"))
    tests = sum(int(item.attrib.get("tests", 0)) for item in suites)
    failed = sum(int(item.attrib.get("failures", 0)) for item in suites)
    errors = sum(int(item.attrib.get("errors", 0)) for item in suites)
    skipped = sum(int(item.attrib.get("skipped", 0)) for item in suites)
    return {"errors": errors, "failed": failed, "passed": tests - failed - errors - skipped, "skipped": skipped}


def _static() -> dict[str, int]:
    result = {}
    for line in (PROJECT / STATIC).read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not value.isdigit():
            raise V14EvidenceError("static log is invalid")
        result[key] = int(value)
    expected = {
        "COMPILE", "DIFF_CHECK", "FOCUSED", "FROZEN_VERIFIERS",
        "HISTORICAL_TAMPER", "REGRESSIONS", "RUFF", "WHITESPACE",
    }
    if set(result) != expected or any(result.values()):
        raise V14EvidenceError("static gate failed")
    return result


def _history_and_tamper(bundle: dict[str, object]) -> None:
    expected = {
        "phase53_v1": {"decision": "rejected", "hashes": V1_HISTORY},
        "phase53_v2": {"decision": "rejected", "hashes": V2_HISTORY},
        "phase53_v3": {"decision": "rejected", "hashes": V3_HISTORY},
        "phase53_v4": {"decision": "rejected", "hashes": V4_HISTORY},
        "phase53_v5": {"decision": "rejected", "hashes": V5_HISTORY},
        "phase53_v6": {"decision": "rejected", "hashes": V6_HISTORY},
        "phase53_v7": {"decision": "rejected", "hashes": V7_HISTORY},
        "phase53_v8": {"decision": "rejected", "hashes": V8_HISTORY},
        "phase53_v9": {"decision": "rejected", "hashes": V9_HISTORY},
        "phase53_v10": {"decision": "rejected", "hashes": V10_HISTORY},
        "phase53_v11": {"decision": "rejected", "hashes": V11_HISTORY},
        "phase53_v12": {"decision": "rejected", "hashes": V12_HISTORY},
        "phase53_v13": {"decision": "rejected", "hashes": V13_HISTORY},
    }
    if bundle.get("history") != expected:
        raise V14EvidenceError("V1/V2/V3 history is not exact or not rejected")
    for version, history in (
        ("V1", V1_HISTORY), ("V2", V2_HISTORY), ("V3", V3_HISTORY),
        ("V4", V4_HISTORY), ("V5", V5_HISTORY), ("V6", V6_HISTORY),
        ("V7", V7_HISTORY), ("V8", V8_HISTORY), ("V9", V9_HISTORY), ("V10", V10_HISTORY),
        ("V11", V11_HISTORY),
        ("V12", V12_HISTORY),
        ("V13", V13_HISTORY),
    ):
        for relative, digest in history.items():
            if _sha(PROJECT / relative) != digest:
                raise V14EvidenceError(f"{version} historical byte drift: {relative}")
    historical_leaves: dict[str, str] = {}
    for root in HISTORICAL_ROOTS:
        leaves: dict[str, str] = {}
        _verify_manifest_tree(root, set(), set(), leaves, 0)
        for relative, digest in leaves.items():
            prior = historical_leaves.setdefault(relative, digest)
            if prior != digest:
                raise V14EvidenceError(f"historical leaf digest conflict: {relative}")
    targets = [
        f"docs/onyx/checkpoints/phase5-capability-nexus-v{version}/phase5-capability-nexus-v{version}.{suffix}"
        for version in (1, 2)
        for suffix in ("bundle.json", "junit.xml", "raw.log", "static.log")
    ] + [
        f"docs/onyx/checkpoints/phase5-capability-nexus-v{version}/PHASE5_3_CAPABILITY_NEXUS_V{version}_CHECKPOINT.md"
        for version in (1, 2)
    ] + [
        "core/capability_nexus_v3.py", "core/capability_nexus_v4.py",
        "core/capability_nexus_v5.py", "core/capability_nexus_v6.py",
        "core/capability_nexus_v7.py", "core/capability_nexus_v8.py",
        "core/capability_nexus_v9.py",
        "core/capability_nexus_v10.py",
        "core/capability_nexus_v11.py",
        "core/capability_nexus_v12.py",
        "core/capability_nexus_v13.py",
    ]
    with tempfile.TemporaryDirectory(prefix="onyx-p53-history-tamper-") as directory:
        base = Path(directory)
        for relative in targets:
            expected_digest = historical_leaves.get(relative)
            if expected_digest is None:
                raise V14EvidenceError(f"historical tamper leaf is unbound: {relative}")
            copied = base / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes((PROJECT / relative).read_bytes())
            if _sha(copied) != expected_digest:
                raise V14EvidenceError(f"historical pristine copy mismatch: {relative}")
            copied.write_bytes(copied.read_bytes() + b"\n# disposable tamper\n")
            if _sha(copied) == expected_digest:
                raise V14EvidenceError(f"historical tamper fixture was not rejected: {relative}")
    _run_frozen_verifiers()


def _verify_manifest_tree(
    relative: str,
    active: set[str],
    verified: set[str],
    leaves: dict[str, str],
    depth: int,
) -> None:
    if depth > 32 or len(verified) >= 256 or len(leaves) > 4096:
        raise V14EvidenceError("historical manifest traversal budget exceeded")
    if relative in active:
        raise V14EvidenceError(f"historical manifest cycle detected: {relative}")
    if relative in verified:
        return
    active.add(relative)
    entries = _historical_manifest(relative)
    if len(entries) > 4096:
        raise V14EvidenceError("historical manifest leaf budget exceeded")
    for digest, child in entries:
        _verify_historical_path(child, digest)
        if child.endswith(".sha256"):
            if len(verified) >= 256:
                raise V14EvidenceError("historical manifest traversal budget exceeded")
            _verify_manifest_tree(child, active, verified, leaves, depth + 1)
        else:
            _record_historical_leaf(leaves, child, digest)
        if len(leaves) > 4096 or len(verified) > 256:
            raise V14EvidenceError("historical manifest traversal budget exceeded")
    active.remove(relative)
    verified.add(relative)
    if len(verified) > 256:
        raise V14EvidenceError("historical manifest traversal budget exceeded")


def _record_historical_leaf(leaves: dict[str, str], relative: str, digest: str) -> None:
    prior = leaves.get(relative)
    if prior is None:
        if len(leaves) >= 4096:
            raise V14EvidenceError("historical manifest leaf budget exceeded")
        leaves[relative] = digest
    elif prior != digest:
        raise V14EvidenceError(f"historical recursive digest conflict: {relative}")
    if len(leaves) > 4096:
        raise V14EvidenceError("historical manifest leaf budget exceeded")


def _verify_historical_path(relative: str, digest: str) -> None:
    _assert_no_reparse(relative)
    path = PROJECT / relative
    try:
        path.resolve(strict=True).relative_to(PROJECT.resolve(strict=True))
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise V14EvidenceError(f"historical path escapes or is missing: {relative}") from exc
    if not path.is_file() or _sha(path) != digest:
        raise V14EvidenceError(f"historical recursive leaf mismatch: {relative}")


def _assert_no_reparse(relative: str) -> None:
    parts = Path(relative).parts
    if not parts or Path(relative).is_absolute() or ".." in parts:
        raise V14EvidenceError(f"historical path is unsafe: {relative}")
    current = PROJECT
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    for component in (None, *parts):
        if component is not None:
            current /= component
        try:
            info = current.lstat()
        except OSError as exc:
            raise V14EvidenceError(f"historical path escapes or is missing: {relative}") from exc
        attributes = getattr(info, "st_file_attributes", 0)
        if stat.S_ISLNK(info.st_mode) or attributes & reparse_flag:
            raise V14EvidenceError(f"historical path contains a reparse component: {relative}")


def _run_frozen_verifiers() -> None:
    if int(os.environ.get("ONYX_P53_V14_HISTORY_VERIFY_DEPTH", "0")) != 0:
        raise V14EvidenceError("historical verifier recursion detected")
    env = os.environ.copy()
    env["ONYX_P53_V14_HISTORY_VERIFY_DEPTH"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    # Frozen V13 executes and binds the complete frozen V1-V12 verifier closure.
    for version in (13,):
        verifier = f"scripts/verify_phase5_capability_nexus_v{version}.py"
        completed = subprocess.run(
            [sys.executable, verifier], cwd=PROJECT, env=env, text=True,
            capture_output=True, check=False, timeout=300,
        )
        marker = f"P53_CAPABILITY_NEXUS_V{version}_EVIDENCE_OK"
        if completed.returncode or marker not in completed.stdout:
            raise V14EvidenceError(f"frozen V{version} verifier failed")


def _live(bundle: dict[str, object]) -> None:
    entries = _manifest(LIVE)
    if tuple(path for _, path in entries) != ("core/capability_nexus_v13.py", V13_LIVE):
        raise V14EvidenceError("V14 live scan anchors are invalid")
    v13_entries = _manifest(V13_LIVE)
    if tuple(path for _, path in v13_entries) != ("core/capability_nexus_v12.py", V12_LIVE):
        raise V14EvidenceError("V13 live scan anchors are invalid")
    v12_entries = _manifest(V12_LIVE)
    if tuple(path for _, path in v12_entries) != ("core/capability_nexus_v11.py", V11_LIVE):
        raise V14EvidenceError("V12 live scan anchors are invalid")
    v11_entries = _manifest(V11_LIVE)
    if tuple(path for _, path in v11_entries) != ("core/capability_nexus_v10.py", V10_LIVE):
        raise V14EvidenceError("V11 live scan anchors are invalid")
    v10_entries = _manifest(V10_LIVE)
    if tuple(path for _, path in v10_entries) != ("core/capability_nexus_v9.py", V9_LIVE):
        raise V14EvidenceError("V10 live scan anchors are invalid")
    v9_entries = _manifest(V9_LIVE)
    if tuple(path for _, path in v9_entries) != ("core/capability_nexus_v8.py", V8_LIVE):
        raise V14EvidenceError("V9 live scan anchors are invalid")
    v8_entries = _manifest(V8_LIVE)
    if tuple(path for _, path in v8_entries) != ("core/capability_nexus_v7.py", V7_LIVE):
        raise V14EvidenceError("V8 live scan anchors are invalid")
    v7_entries = _manifest(V7_LIVE)
    if tuple(path for _, path in v7_entries) != ("core/capability_nexus_v6.py", V6_LIVE):
        raise V14EvidenceError("V7 live scan anchors are invalid")
    v6_entries = _manifest(V6_LIVE)
    if tuple(path for _, path in v6_entries) != ("core/capability_nexus_v5.py", V5_LIVE):
        raise V14EvidenceError("V6 live scan anchors are invalid")
    v5_entries = _manifest(V5_LIVE)
    if tuple(path for _, path in v5_entries) != ("core/capability_nexus_v4.py", V4_LIVE):
        raise V14EvidenceError("V5 live scan anchors are invalid")
    v4_entries = _manifest(V4_LIVE)
    if tuple(path for _, path in v4_entries) != ("core/capability_nexus_v3.py", V3_LIVE):
        raise V14EvidenceError("V4 live scan anchors are invalid")
    v3_entries = _manifest(V3_LIVE)
    if tuple(path for _, path in v3_entries) != ("core/capability_nexus_v2.py", V2_LIVE):
        raise V14EvidenceError("V3 live scan anchors are invalid")
    v2_entries = _manifest(V2_LIVE)
    if tuple(path for _, path in v2_entries) != ("core/capability_nexus_v1.py", V1_LIVE):
        raise V14EvidenceError("V2 live scan anchors are invalid")
    expanded = _manifest(V1_LIVE) + (
        (V1_HISTORY["core/capability_nexus_v1.py"], "core/capability_nexus_v1.py"),
        (V2_HISTORY["core/capability_nexus_v2.py"], "core/capability_nexus_v2.py"),
        (V3_HISTORY["core/capability_nexus_v3.py"], "core/capability_nexus_v3.py"),
        (V4_HISTORY["core/capability_nexus_v4.py"], "core/capability_nexus_v4.py"),
        (V5_HISTORY["core/capability_nexus_v5.py"], "core/capability_nexus_v5.py"),
        (V6_HISTORY["core/capability_nexus_v6.py"], "core/capability_nexus_v6.py"),
        (V7_HISTORY["core/capability_nexus_v7.py"], "core/capability_nexus_v7.py"),
        (V8_HISTORY["core/capability_nexus_v8.py"], "core/capability_nexus_v8.py"),
        (V9_HISTORY["core/capability_nexus_v9.py"], "core/capability_nexus_v9.py"),
        (V10_HISTORY["core/capability_nexus_v10.py"], "core/capability_nexus_v10.py"),
        (V11_HISTORY["core/capability_nexus_v11.py"], "core/capability_nexus_v11.py"),
        (V12_HISTORY["core/capability_nexus_v12.py"], "core/capability_nexus_v12.py"),
        (V13_HISTORY["core/capability_nexus_v13.py"], "core/capability_nexus_v13.py"),
    )
    if bundle.get("live_scan") != {"count": len(expanded), "manifest_sha256": _sha(PROJECT / LIVE)}:
        raise V14EvidenceError("live scan summary drift")
    for digest, relative in expanded:
        path = PROJECT / relative
        if _sha(path) != digest or "capability_nexus_v14" in path.read_text(encoding="utf-8"):
            raise V14EvidenceError(f"live boundary drift/wiring: {relative}")


def _assignment(path: Path, name: str) -> object:
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise V14EvidenceError(f"missing assignment: {name}")


def _semantics(bundle: dict[str, object]) -> None:
    tree = ast.parse((PROJECT / CORE).read_text(encoding="utf-8"))
    forbidden = {"actions", "dashboard", "httpx", "main", "memory", "mcp", "requests", "socket", "subprocess", "webbrowser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and {item.name.split(".", 1)[0] for item in node.names} & forbidden:
            raise V14EvidenceError("candidate imports a forbidden runtime/provider surface")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden:
            raise V14EvidenceError("candidate imports a forbidden runtime/provider surface")
    sys.path.insert(0, str(PROJECT))
    try:
        from core.capability_nexus_v14 import (  # noqa: PLC0415
            CapabilityNexusV14,
            NexusFeatureGateV14,
            _METADATA_ENUMS,
            _safe_metadata,
            build_legacy_descriptors_v14,
        )
    finally:
        sys.path.pop(0)
    nexus = CapabilityNexusV14(NexusFeatureGateV14())
    if hasattr(nexus, "dispatch") or hasattr(nexus, "execute"):
        raise V14EvidenceError("registry exposes dispatch")
    declarations = _assignment(PROJECT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(PROJECT / "core/permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v14(
        declarations, policies, workspace_id="workspace-verifier", account_id="account-verifier", profile_id="profile-verifier"
    )
    if len(built.descriptors) != 26 or dict(built.policy_mapping()) != policies:
        raise V14EvidenceError("legacy parity failed")
    expected_metadata_enums = {
        "data_source": frozenset({"constructor_allowlist", "healthy", "local_catalog"}),
        "dispatch_path": frozenset({"legacy_unchanged"}),
        "fallback_class": frozenset({"explicit_browser_fallback"}),
        "policy_source": frozenset({"trusted_host_mapping"}),
    }
    if dict(_METADATA_ENUMS) != expected_metadata_enums:
        raise V14EvidenceError("closed metadata provenance contract drift")
    for key, value in (
        ("data_source", "arbitrary prose"),
        ("dispatch_path", "future_dispatch"),
        ("policy_source", "dynamic_policy"),
        ("fallback_class", "automatic_fallback"),
        ("declaration_sha256", "A" * 64),
    ):
        try:
            _safe_metadata(((key, value),))
        except ValueError:
            pass
        else:
            raise V14EvidenceError("closed metadata provenance contract accepted an unknown value")
    safe_metadata_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_safe_metadata"
    )
    called = {
        node.func.id
        for node in ast.walk(safe_metadata_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if called & {"_secret_canary", "_raw_credential_canary", "_validate_content_decoding_closure"}:
        raise V14EvidenceError("typed metadata still uses free-text heuristic inference")
    claims = bundle.get("claims")
    expected = {
        "callbacks_outside_locks", "default_off_no_dispatch", "exact_concrete_immutable_gate",
        "profile_bound_projection_snapshot_cursor_receipt",
        "bounded_pending_uncertain_no_replay",
        "closed_metadata_provenance_enums_and_typed_hash",
        "content_scanners_confined_to_free_text_schema_and_legacy_declarations",
        "decoded_before_allowlist_content_scanning",
        "canonical_secret_name_field_rejection",
        "no_metadata_heuristic_inference",
        "atomic_entry_hook_admission_and_outer_finally_cleanup",
        "recursive_v1_to_v13_history_and_component_reparse_rejection",
    }
    if not isinstance(claims, dict) or set(claims) != expected or not all(claims.values()):
        raise V14EvidenceError("semantic claim set is invalid")


def _environment(bundle: dict[str, object]) -> None:
    recorded = bundle.get("environment")
    expected = {"executable": sys.executable, "platform": platform.platform(), "python": platform.python_version()}
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in expected.items()):
        raise V14EvidenceError("environment drift")
    commit = subprocess.run(["git", "rev-parse", "HEAD"], cwd=PROJECT, text=True, capture_output=True, check=True).stdout.strip()
    if bundle.get("base_commit") != commit:
        raise V14EvidenceError("base commit drift")


def _fresh() -> None:
    env = os.environ.copy()
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    completed = subprocess.run(
        [sys.executable, "-m", "pytest", "-q", TESTS, "--disable-warnings", "--maxfail=1"],
        cwd=PROJECT, env=env, text=True, capture_output=True, check=False,
    )
    if completed.returncode or "1752 passed" not in completed.stdout:
        raise V14EvidenceError("fresh focused suite failed")


def verify() -> dict[str, object]:
    paths = _dag()
    bundle = _bundle(paths)
    counts = _junit()
    if counts != {"errors": 0, "failed": 0, "passed": 1752, "skipped": 0} or bundle.get("counts") != counts:
        raise V14EvidenceError("JUnit counts drift")
    if bundle.get("static_gates") != _static():
        raise V14EvidenceError("static evidence drift")
    _history_and_tamper(bundle)
    _live(bundle)
    _semantics(bundle)
    _environment(bundle)
    _fresh()
    return {"artifacts": len(paths), "focused_passed": 1752, "live_scan_files": 93,
            "root_sha256": _sha(PROJECT / ROOT_MANIFEST)}


def main() -> int:
    print("P53_CAPABILITY_NEXUS_V14_EVIDENCE_OK " + json.dumps(verify(), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

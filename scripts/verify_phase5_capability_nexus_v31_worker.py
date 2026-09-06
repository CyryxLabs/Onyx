"""Verify the frozen Phase 5.3 Capability Nexus V31 candidate."""

from __future__ import annotations

import ast
from datetime import datetime
import hashlib
import json
import math
from pathlib import Path, PurePosixPath
import platform
import re
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET


PROJECT = Path(__file__).resolve().parents[1]
ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V31-001.sha256"
ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V31-001.sha256"
EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v31"
BUNDLE = f"{EVIDENCE}/phase5-capability-nexus-v31.bundle.json"
JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v31.junit.xml"
RAW = f"{EVIDENCE}/phase5-capability-nexus-v31.raw.log"
STATIC = f"{EVIDENCE}/phase5-capability-nexus-v31.static.log"
LIVE = f"{EVIDENCE}/phase5-capability-nexus-v31.live-scan.sha256"
METRICS = f"{EVIDENCE}/phase5-capability-nexus-v31.metrics.json"
COMBINED_JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v31.combined.junit.xml"
REGRESSION_JUNIT = f"{EVIDENCE}/phase5-capability-nexus-v31.regressions.junit.xml"
REGRESSION_REPORT = f"{EVIDENCE}/phase5-capability-nexus-v31.regressions.json"
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
V14_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v14/phase5-capability-nexus-v14.live-scan.sha256"
V15_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v15/phase5-capability-nexus-v15.live-scan.sha256"
V16_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v16/phase5-capability-nexus-v16.live-scan.sha256"
V17_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v17/phase5-capability-nexus-v17.live-scan.sha256"
V18_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v18/phase5-capability-nexus-v18.live-scan.sha256"
V19_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v19/phase5-capability-nexus-v19.live-scan.sha256"
V20_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v20/phase5-capability-nexus-v20.live-scan.sha256"
V21_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v21/phase5-capability-nexus-v21.live-scan.sha256"
V22_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v22/phase5-capability-nexus-v22.live-scan.sha256"
V23_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v23/phase5-capability-nexus-v23.live-scan.sha256"
V24_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v24/phase5-capability-nexus-v24.live-scan.sha256"
V25_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v25/phase5-capability-nexus-v25.live-scan.sha256"
V26_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v26/phase5-capability-nexus-v26.live-scan.sha256"
V27_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v27/phase5-capability-nexus-v27.live-scan.sha256"
V28_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v28/phase5-capability-nexus-v28.live-scan.sha256"
V29_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v29/phase5-capability-nexus-v29.live-scan.sha256"
V30_LIVE = "docs/onyx/checkpoints/phase5-capability-nexus-v30/phase5-capability-nexus-v30.live-scan.sha256"
CHECKPOINT = f"{EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V31_CHECKPOINT.md"
CORE = "core/capability_nexus_v31.py"
TESTS = "tests/test_capability_nexus_v31.py"
WHITESPACE = "scripts/check_phase5_capability_nexus_v31_whitespace.py"
SELF = "scripts/verify_phase5_capability_nexus_v31.py"
WORKER = "scripts/verify_phase5_capability_nexus_v31_worker.py"
REPORTER = "scripts/phase5_capability_nexus_v31_subtest_reporter.py"
MUTABLE_PROJECTION_MAP = f"{EVIDENCE}/phase5-capability-nexus-v31.mutable-projections.json"
MUTABLE_PROJECTIONS = (
    "docs/onyx/CAPABILITY_MATRIX.md",
    "docs/onyx/VERIFICATION_EVIDENCE.md",
)
MUTABLE_PROJECTION_HASHES = {
    "docs/onyx/CAPABILITY_MATRIX.md": "5a7c9f2c71d770b7a3fb49a511a9d94e59e985dd96d45f40b9ed6b7505ce3e8b",
    "docs/onyx/VERIFICATION_EVIDENCE.md": "e8ab4895f1c8c6b61b2a3c97acbeac3149b966003e8a63f2eebe5f954c65ad79",
}
MUTABLE_PROJECTION_SNAPSHOTS = tuple(
    f"{EVIDENCE}/mutable-projections/{digest}.snapshot"
    for digest in MUTABLE_PROJECTION_HASHES.values()
)
COMBINED_SUITES = tuple(f"tests/test_capability_nexus_v{version}.py" for version in range(1, 32))
REGRESSION_SUITES = ("tests/test_regressions.py",)
V14_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V14-001.sha256"
V14_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V14-001.sha256"
V14_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v14"
V14_BUNDLE = f"{V14_EVIDENCE}/phase5-capability-nexus-v14.bundle.json"
V14_JUNIT = f"{V14_EVIDENCE}/phase5-capability-nexus-v14.junit.xml"
V14_STATIC = f"{V14_EVIDENCE}/phase5-capability-nexus-v14.static.log"
V14_CHECKPOINT = f"{V14_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V14_CHECKPOINT.md"
V14_VERIFIER = "scripts/verify_phase5_capability_nexus_v14.py"
V15_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V15-001.sha256"
V15_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V15-001.sha256"
V15_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v15"
V15_BUNDLE = f"{V15_EVIDENCE}/phase5-capability-nexus-v15.bundle.json"
V15_JUNIT = f"{V15_EVIDENCE}/phase5-capability-nexus-v15.junit.xml"
V15_STATIC = f"{V15_EVIDENCE}/phase5-capability-nexus-v15.static.log"
V15_CHECKPOINT = f"{V15_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V15_CHECKPOINT.md"
V15_VERIFIER = "scripts/verify_phase5_capability_nexus_v15.py"
V16_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V16-001.sha256"
V16_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V16-001.sha256"
V16_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v16"
V16_BUNDLE = f"{V16_EVIDENCE}/phase5-capability-nexus-v16.bundle.json"
V16_JUNIT = f"{V16_EVIDENCE}/phase5-capability-nexus-v16.junit.xml"
V16_STATIC = f"{V16_EVIDENCE}/phase5-capability-nexus-v16.static.log"
V16_CHECKPOINT = f"{V16_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V16_CHECKPOINT.md"
V16_VERIFIER = "scripts/verify_phase5_capability_nexus_v16.py"
V17_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V17-001.sha256"
V17_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V17-001.sha256"
V17_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v17"
V17_BUNDLE = f"{V17_EVIDENCE}/phase5-capability-nexus-v17.bundle.json"
V17_JUNIT = f"{V17_EVIDENCE}/phase5-capability-nexus-v17.junit.xml"
V17_STATIC = f"{V17_EVIDENCE}/phase5-capability-nexus-v17.static.log"
V17_CHECKPOINT = f"{V17_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V17_CHECKPOINT.md"
V17_VERIFIER = "scripts/verify_phase5_capability_nexus_v17.py"
V18_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V18-001.sha256"
V18_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V18-001.sha256"
V18_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v18"
V18_BUNDLE = f"{V18_EVIDENCE}/phase5-capability-nexus-v18.bundle.json"
V18_JUNIT = f"{V18_EVIDENCE}/phase5-capability-nexus-v18.junit.xml"
V18_STATIC = f"{V18_EVIDENCE}/phase5-capability-nexus-v18.static.log"
V18_CHECKPOINT = f"{V18_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V18_CHECKPOINT.md"
V18_VERIFIER = "scripts/verify_phase5_capability_nexus_v18.py"
V19_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V19-001.sha256"
V19_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V19-001.sha256"
V19_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v19"
V19_BUNDLE = f"{V19_EVIDENCE}/phase5-capability-nexus-v19.bundle.json"
V19_JUNIT = f"{V19_EVIDENCE}/phase5-capability-nexus-v19.junit.xml"
V19_STATIC = f"{V19_EVIDENCE}/phase5-capability-nexus-v19.static.log"
V19_CHECKPOINT = f"{V19_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V19_CHECKPOINT.md"
V19_VERIFIER = "scripts/verify_phase5_capability_nexus_v19.py"
V20_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V20-001.sha256"
V20_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V20-001.sha256"
V20_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v20"
V20_BUNDLE = f"{V20_EVIDENCE}/phase5-capability-nexus-v20.bundle.json"
V20_JUNIT = f"{V20_EVIDENCE}/phase5-capability-nexus-v20.junit.xml"
V20_STATIC = f"{V20_EVIDENCE}/phase5-capability-nexus-v20.static.log"
V20_CHECKPOINT = f"{V20_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V20_CHECKPOINT.md"
V20_VERIFIER = "scripts/verify_phase5_capability_nexus_v20.py"
V21_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V21-001.sha256"
V21_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V21-001.sha256"
V21_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v21"
V21_BUNDLE = f"{V21_EVIDENCE}/phase5-capability-nexus-v21.bundle.json"
V21_JUNIT = f"{V21_EVIDENCE}/phase5-capability-nexus-v21.junit.xml"
V21_STATIC = f"{V21_EVIDENCE}/phase5-capability-nexus-v21.static.log"
V21_CHECKPOINT = f"{V21_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V21_CHECKPOINT.md"
V21_VERIFIER = "scripts/verify_phase5_capability_nexus_v21.py"
V22_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V22-001.sha256"
V22_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V22-001.sha256"
V22_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v22"
V22_BUNDLE = f"{V22_EVIDENCE}/phase5-capability-nexus-v22.bundle.json"
V22_JUNIT = f"{V22_EVIDENCE}/phase5-capability-nexus-v22.junit.xml"
V22_STATIC = f"{V22_EVIDENCE}/phase5-capability-nexus-v22.static.log"
V22_CHECKPOINT = f"{V22_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V22_CHECKPOINT.md"
V22_VERIFIER = "scripts/verify_phase5_capability_nexus_v22.py"
V23_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V23-001.sha256"
V23_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V23-001.sha256"
V23_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v23"
V23_BUNDLE = f"{V23_EVIDENCE}/phase5-capability-nexus-v23.bundle.json"
V23_JUNIT = f"{V23_EVIDENCE}/phase5-capability-nexus-v23.junit.xml"
V23_STATIC = f"{V23_EVIDENCE}/phase5-capability-nexus-v23.static.log"
V23_LIVE_EVIDENCE = f"{V23_EVIDENCE}/phase5-capability-nexus-v23.live-scan.sha256"
V23_CHECKPOINT = f"{V23_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V23_CHECKPOINT.md"
V23_VERIFIER = "scripts/verify_phase5_capability_nexus_v23.py"
V24_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V24-001.sha256"
V24_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V24-001.sha256"
V24_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v24"
V24_BUNDLE = f"{V24_EVIDENCE}/phase5-capability-nexus-v24.bundle.json"
V24_JUNIT = f"{V24_EVIDENCE}/phase5-capability-nexus-v24.junit.xml"
V24_STATIC = f"{V24_EVIDENCE}/phase5-capability-nexus-v24.static.log"
V24_CHECKPOINT = f"{V24_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V24_CHECKPOINT.md"
V24_VERIFIER = "scripts/verify_phase5_capability_nexus_v24.py"
V25_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V25-001.sha256"
V25_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V25-001.sha256"
V25_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v25"
V25_BUNDLE = f"{V25_EVIDENCE}/phase5-capability-nexus-v25.bundle.json"
V25_JUNIT = f"{V25_EVIDENCE}/phase5-capability-nexus-v25.junit.xml"
V25_STATIC = f"{V25_EVIDENCE}/phase5-capability-nexus-v25.static.log"
V25_CHECKPOINT = f"{V25_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V25_CHECKPOINT.md"
V25_VERIFIER = "scripts/verify_phase5_capability_nexus_v25.py"
V26_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V26-001.sha256"
V26_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V26-001.sha256"
V26_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v26"
V26_BUNDLE = f"{V26_EVIDENCE}/phase5-capability-nexus-v26.bundle.json"
V26_JUNIT = f"{V26_EVIDENCE}/phase5-capability-nexus-v26.junit.xml"
V26_STATIC = f"{V26_EVIDENCE}/phase5-capability-nexus-v26.static.log"
V26_CHECKPOINT = f"{V26_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V26_CHECKPOINT.md"
V26_VERIFIER = "scripts/verify_phase5_capability_nexus_v26.py"
V27_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V27-001.sha256"
V27_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V27-001.sha256"
V27_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v27"
V27_BUNDLE = f"{V27_EVIDENCE}/phase5-capability-nexus-v27.bundle.json"
V27_JUNIT = f"{V27_EVIDENCE}/phase5-capability-nexus-v27.junit.xml"
V27_STATIC = f"{V27_EVIDENCE}/phase5-capability-nexus-v27.static.log"
V27_CHECKPOINT = f"{V27_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V27_CHECKPOINT.md"
V27_VERIFIER = "scripts/verify_phase5_capability_nexus_v27.py"
V28_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V28-001.sha256"
V28_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V28-001.sha256"
V28_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v28"
V28_BUNDLE = f"{V28_EVIDENCE}/phase5-capability-nexus-v28.bundle.json"
V28_JUNIT = f"{V28_EVIDENCE}/phase5-capability-nexus-v28.junit.xml"
V28_STATIC = f"{V28_EVIDENCE}/phase5-capability-nexus-v28.static.log"
V28_CHECKPOINT = f"{V28_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V28_CHECKPOINT.md"
V28_VERIFIER = "scripts/verify_phase5_capability_nexus_v28.py"
V29_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V29-001.sha256"
V29_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V29-001.sha256"
V29_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v29"
V29_BUNDLE = f"{V29_EVIDENCE}/phase5-capability-nexus-v29.bundle.json"
V29_JUNIT = f"{V29_EVIDENCE}/phase5-capability-nexus-v29.junit.xml"
V29_STATIC = f"{V29_EVIDENCE}/phase5-capability-nexus-v29.static.log"
V29_CHECKPOINT = f"{V29_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V29_CHECKPOINT.md"
V29_VERIFIER = "scripts/verify_phase5_capability_nexus_v29.py"
V30_ARTIFACT_MANIFEST = "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V30-001.sha256"
V30_ROOT_MANIFEST = "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V30-001.sha256"
V30_EVIDENCE = "docs/onyx/checkpoints/phase5-capability-nexus-v30"
V30_BUNDLE = f"{V30_EVIDENCE}/phase5-capability-nexus-v30.bundle.json"
V30_JUNIT = f"{V30_EVIDENCE}/phase5-capability-nexus-v30.junit.xml"
V30_STATIC = f"{V30_EVIDENCE}/phase5-capability-nexus-v30.static.log"
V30_CHECKPOINT = f"{V30_EVIDENCE}/PHASE5_3_CAPABILITY_NEXUS_V30_CHECKPOINT.md"
V30_VERIFIER = "scripts/verify_phase5_capability_nexus_v30.py"
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
V14_HISTORY = {
    "core/capability_nexus_v14.py": "110170dc17e43cec844eaae55387989d6b057a8f07c01feb83b7e292bc0d1c07",
    "tests/test_capability_nexus_v14.py": "2aff0a21456052dd18c6d9e996e380932564af32d1476429383f5ab277dd81d7",
    "scripts/verify_phase5_capability_nexus_v14.py": "8eca4ea9bfaa550e31ec5b8f209e0d0c6dcb8724e6c22c799c2af3e56ecfc08c",
    "scripts/check_phase5_capability_nexus_v14_whitespace.py": "63066542f021baea421c2d10777e4ad58b6c6b21064c856e7e044b03a9f6fb0f",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V14-001.sha256": "5429f58302cab5e15a8e3d9076b316591a47fd3857a150ceb532d9e5fa5050e4",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V14-001.sha256": "3dc4e6bed2672a558fe3bef01c00ddcb46fe35baecc76080ffa45df399ac4790",
}
V15_HISTORY = {
    "core/capability_nexus_v15.py": "0c61979351e9cee695474acc16265af10199b4b36392005dc04e6463bc4faf73",
    "tests/test_capability_nexus_v15.py": "b38e7048f76d89e271a9eb93d4f9af29248db6331d11961bcedee2bf0e6c43b3",
    "scripts/verify_phase5_capability_nexus_v15.py": "788859851164233e62c3a7224dc8a197e86e092d2cdacc3dc8bf6b97fec860c8",
    "scripts/check_phase5_capability_nexus_v15_whitespace.py": "068b1e3c5e20457b7016e2c00de13c791e1aa47427b49a9b2b35e7ea0d3f6832",
    V15_ARTIFACT_MANIFEST: "08daf2b93e74f0b83d6487c30849313948fbf8b0d8ec6981a49fb076b2c69212",
    V15_ROOT_MANIFEST: "60850f591b5e5a79f6015e07291b776dd682467cc6a4b3b6069e8590b247846d",
}
V16_HISTORY = {
    "core/capability_nexus_v16.py": "f4fb99b94f1f5237afa81bd4c7e70f5987406e3b81da898cccaa534c00f90455",
    "tests/test_capability_nexus_v16.py": "29157b8eb4f01fd3d7f76c66e0b7fe0afba118007f3dd54c788741772ce6592d",
    "scripts/verify_phase5_capability_nexus_v16.py": "d5fc6a6ed4502f579e26704d7f57c75e608a7ed554dc7e782279789c3b3fd584",
    "scripts/verify_phase5_capability_nexus_v16_worker.py": "4014a88c6d7daed840debb9c7d8815f83d71667f7e94f4940f79761654572730",
    "scripts/phase5_capability_nexus_v16_subtest_reporter.py": "64bfd18e2620dd12941e007e22c9f6aceda2811593fb31415350d5c882633d10",
    "scripts/check_phase5_capability_nexus_v16_whitespace.py": "3ba19bfd39f0b0e19219d7dedc528e263c782207a8e8a7e853ed06a89b4b600d",
    V16_ARTIFACT_MANIFEST: "8873308e576eae482bbb46ce764a4aa00af39709abd83fc4a842db8132dbb419",
    V16_ROOT_MANIFEST: "74b500df804fa0508e52f5d2b88b725c7e3aa141be5c6a442926387be446e9b7",
}
V17_HISTORY = {
    "core/capability_nexus_v17.py": "66419a598154c22d68f2d5a996bee6ab817d6602d57651c9cd6c56a41abbf422",
    "tests/test_capability_nexus_v17.py": "bf7af31e3ecf05a1a4fd094c654effb5afe40e7b9285aa10b512c5e3dde39e50",
    "scripts/verify_phase5_capability_nexus_v17.py": "3e8bb4cfb59882c3826d9f9df316b125702e77ba344ccb4be3dad3cc5a55003e",
    "scripts/verify_phase5_capability_nexus_v17_worker.py": "dab68d57104aff333341d4827f9621c5cf14d0dca36bd7bd16febcace82da9d9",
    "scripts/phase5_capability_nexus_v17_subtest_reporter.py": "a7860ef4c846ad3303b60572a580c698d26acfe148a6a0a985c9dc5ced15014a",
    "scripts/check_phase5_capability_nexus_v17_whitespace.py": "940d534dca45c754d85e5868fe7723d5309c184fa83185e22f37db0258635a89",
    V17_ARTIFACT_MANIFEST: "adc0aa3a417b59adc180901ea5b0d08c1449bb426402ce155c6297ed957e40c1",
    V17_ROOT_MANIFEST: "0cc3cb936b97d2c545d38c5a35f63fcb88572405d3fc8cb76ea0f2afe8fbaf2f",
}
V18_HISTORY = {
    "core/capability_nexus_v18.py": "daf165f09440e297bae81f74f45dd46d0c09f02ddf42d0eecd27c768f8c80a01",
    "tests/test_capability_nexus_v18.py": "c7c4d8e26106c78936377fefe515527d69acc3ff5c683e10b1b168f19b6f96d3",
    "scripts/verify_phase5_capability_nexus_v18.py": "6ed5d1d99d3ff3ef6f11d91e74cafe35d3864b2c557f3e93737104f88b96d4b9",
    "scripts/verify_phase5_capability_nexus_v18_worker.py": "b90e7d0084f36cb5fbd22b6adde4e3dbac18d7eea5e260b00f1b631222047c04",
    "scripts/phase5_capability_nexus_v18_bootstrap.py": "a365c0b89dcc012050aed4db1414048d562178ab0ad9fe58e1d035680f4d5a44",
    "scripts/phase5_capability_nexus_v18_subtest_reporter.py": "fbca475f22815ab967ecbd1dddbc448d5cc2bd06771a534e330281a81254423b",
    "scripts/check_phase5_capability_nexus_v18_whitespace.py": "5918ba491b06bfa066de7e9bfa09afd647ec3ed0685d3863b4c822ce3d6734ab",
    V18_ARTIFACT_MANIFEST: "5d9f457e54c625ed846bc9a0c193adb5da7da84bfdd5dbac39733f8ba6fb010b",
    V18_ROOT_MANIFEST: "05967af9abdb81dde8b78e4c1fad5d09a2855102ffd7653e7101e7ac4c82d1d7",
}
V19_HISTORY = {
    "core/capability_nexus_v19.py": "07843a76223dbb21658135774f442d5f33dbc25e5369001ad2b73a817e143cbc",
    "tests/test_capability_nexus_v19.py": "5c2032eedc76b657423e05fccca2546dcf6ea5922535bc728355f6a3c21d9fa3",
    "scripts/verify_phase5_capability_nexus_v19.py": "5ddd5f588437486a985056359e30dc3d1d2e97902d6a43c5963a895155d9d6e4",
    "scripts/verify_phase5_capability_nexus_v19_worker.py": "04a22377fb82ac1094a6ca4ba6c147989cced2ae6a526b21c73725b591f87ec2",
    "scripts/phase5_capability_nexus_v19_bootstrap.py": "eef5fe39198b5d71a57ab33122cc54b761428890f141d505d36320332f30bd18",
    "scripts/phase5_capability_nexus_v19_subtest_reporter.py": "c1d118c438c051f9cfd242a43a60aa33998435eb26262b9bdfbda04fc175874a",
    "scripts/check_phase5_capability_nexus_v19_whitespace.py": "35c470f2a716279529cd5d3e7638fbf340eeb4a7626dde7bb2b2032ba410ed13",
    V19_ARTIFACT_MANIFEST: "5f7f49a67142decccdb66e70aca7f726e704dfbbbc1bf9321d798faf18432ef6",
    V19_ROOT_MANIFEST: "4ed79c2c0d37072e865ebcb1df4eb2cc1b12777bba6148832fa36c4ba575a7e5",
}
V20_HISTORY = {
    "core/capability_nexus_v20.py": "d0ecdcbe63718e854a1c708f94b5c35c7ad2b9c7733a9efb10e6e6c5815cfb7a",
    "tests/test_capability_nexus_v20.py": "af0ccac9e4566014ca751ca18ad76c7429eb72568d72d3cfb9c0ef8374a1653a",
    "scripts/verify_phase5_capability_nexus_v20.py": "0703335ec6a0ca1d8ad49916bfa11cac29cece08b38b0f34ea39bca50148239a",
    "scripts/verify_phase5_capability_nexus_v20_worker.py": "894b325d576d05c65edce9e968292a3f98d3f381779e87a3ed93e72ced7c2251",
    "scripts/phase5_capability_nexus_v20_subtest_reporter.py": "27dc1ea64a9851da5e071fcee0c59d6abbde8d0a6beef02a6598a743d3489c7e",
    "scripts/check_phase5_capability_nexus_v20_whitespace.py": "0b9e0acd4c7e60e6244d41cf607d95f3ee7be8166e3a0d3d602ac24ef399fd73",
    V20_ARTIFACT_MANIFEST: "d9e92f17f0386bba9bce421f72e6ef8ac60bb5e8aab98dfac9f6671df2db58b2",
    V20_ROOT_MANIFEST: "9b813aed42fe251f979f9f36c9da742d021ed13435d1f31d87672bf9cf15fd46",
}
V21_HISTORY = {
    "core/capability_nexus_v21.py": "1f1bc766f7062b15c5a64666c6b03231560733a0dc6e388d7b415927043ed41a",
    "tests/test_capability_nexus_v21.py": "1d560cabaf6a8aff1411da60370dd6912f2112b6a964fd519a992e0b96d8d8eb",
    "scripts/verify_phase5_capability_nexus_v21.py": "1df832eab61f58a084259fd8608873faf261f35c676d9688dfa7f9c2a99f87f2",
    "scripts/verify_phase5_capability_nexus_v21_worker.py": "4acc13327d7759aeb05e48c6cfef3ca335526ea2633f5d8ede21cced77515796",
    "scripts/phase5_capability_nexus_v21_subtest_reporter.py": "ec6ecadaeb5fb8b78b84575a36688c7a7b63e6f25499fc7482d6e7be4fce9613",
    "scripts/check_phase5_capability_nexus_v21_whitespace.py": "f3cdc9a331ad7e59419940fc44c45ae18fc0b1c20ca13df4604fe351d145f6eb",
    V21_ARTIFACT_MANIFEST: "055672516e56743f64df810a4c9f3bad4186cad3c6b9bb285640e4a36e65ad16",
    V21_ROOT_MANIFEST: "b7c81643756462ed115bf75516c8c5ad2c345fca6cbb4691b064931cf2e169d8",
}
V22_HISTORY = {
    "core/capability_nexus_v22.py": "f5c2b025e8cb9fe3d78cf270ecab877fd81521c48b025e683276fd27a8eae526",
    "tests/test_capability_nexus_v22.py": "3b4b33ca339e4b1749c6567dd4d6f0b6a21ba053be3d7e12cb77a795e46ab833",
    "scripts/verify_phase5_capability_nexus_v22.py": "23eae195813d5912065224c4bd9f81170f36136b9e7c0e2096938009afc8fd45",
    "scripts/verify_phase5_capability_nexus_v22_worker.py": "8062f3cfea92a8bd3c1d097c35120a20c909fb25228cb7e644999d6ac99cceed",
    "scripts/phase5_capability_nexus_v22_subtest_reporter.py": "e2b9ee0b56de32f83e94a0d56b2bc163a97a207d2f7e2459e2e7fde46e9f352f",
    "scripts/check_phase5_capability_nexus_v22_whitespace.py": "0f125b5ddff14f0b1b8f7df2ff61641341789ecd635f67f68f3cf83f487b2218",
    V22_ARTIFACT_MANIFEST: "bcb19bf1a5b51084ff026ef861809fd365cff9d0fb6a06134ba516c1d3b03626",
    V22_ROOT_MANIFEST: "7ed9d3e33cf3424e448fc0ced2c1ab79fb7f49b95a8f7cc4fcf655f6fd2c8e9a",
}
V23_HISTORY = {
    "core/capability_nexus_v23.py": "32dd829130eb32eacb32052196052f7d66aa2f92e0e8d3c2ab1586e0011454ac",
    "tests/test_capability_nexus_v23.py": "f7a9938631cb39d519e06bc2b50f8eafba8c731ed5f393f3cb41882c27b456c4",
    "scripts/verify_phase5_capability_nexus_v23.py": "01803bafb5db005754f7f11b25d3bd17065a14a0aa6eb52ae0da720bc26526e3",
    "scripts/verify_phase5_capability_nexus_v23_worker.py": "798071357e5e0acfb2e147a9157d61b280f6311ea306ddf92a0ca4410f750e94",
    "scripts/phase5_capability_nexus_v23_subtest_reporter.py": "baade702f6415733a9312136eddefd769bf333236332e512afe3cd2e36452ddf",
    "scripts/check_phase5_capability_nexus_v23_whitespace.py": "86adbda10c87c5d3ffed9419b4aca1792128080c85aa70738e48cd572ca82e63",
    V23_ARTIFACT_MANIFEST: "a69d4a66d6c829d52412e38434751c87ed5f24f72385aa016504224bead30d34",
    V23_ROOT_MANIFEST: "7cb5799d375cf18b03836e96f013b7fc39c7ec02638c856451b910890150958b",
}
V24_HISTORY = {
    "core/capability_nexus_v24.py": "4150d020a57e20c96805106aa8edc3b941e6866a2491d4cd9721bedaa82330d7",
    "tests/test_capability_nexus_v24.py": "1b32f9a7d1c642fe4af531dc0b9adee6af3bd7ce7db5f9bcf1dcedbc6293dc71",
    "scripts/verify_phase5_capability_nexus_v24.py": "f695841cff8a677e087b144e10e52f930376aa38e35390bfc67e033ed6f78981",
    "scripts/verify_phase5_capability_nexus_v24_worker.py": "a7486db5bd9b29fc225ff981e6c6a2348d884fe03404035441ca0bf133ce5355",
    "scripts/phase5_capability_nexus_v24_subtest_reporter.py": "699e97849d756f07a8746ce1aaf6c7a988d076d1124fb5045e14aa0c140e3da4",
    "scripts/check_phase5_capability_nexus_v24_whitespace.py": "b9bf22f63c1693a5c76aebc5625db4f6e8f227fbb1d1977c624cfb3e305c0070",
    V24_ARTIFACT_MANIFEST: "dab74bcb848b08b74fc005045d1709755bb45d224208eff3b06a348d01c85332",
    V24_ROOT_MANIFEST: "a0cef935efa2b34041bf4206fbd30f43d45a1282ad9c42339598c112c061dad9",
}
V25_HISTORY = {
    "core/capability_nexus_v25.py": "88fca28c19bcaeb71e6840191440824339d87c33309ca58dd644706d9b02ca11",
    "tests/test_capability_nexus_v25.py": "3cf573a44d283d30388c5ad8a3ab3fd1981688bd97613f3b57b2d2d87c709003",
    "scripts/verify_phase5_capability_nexus_v25.py": "36fdf20b4f6260df649bd8ade9a38a1068c90c7e9aa24d4c6ed4766b0aa6a6db",
    "scripts/verify_phase5_capability_nexus_v25_worker.py": "a4c4ec22fc1ca8b730d50a94290954c54bcb152c9903ce197df57cf41afae688",
    "scripts/phase5_capability_nexus_v25_subtest_reporter.py": "a75d56fadbc4bd8dace2fbd59b7a019e080a16373ba0ffa7557b05f4b3bd0abf",
    "scripts/check_phase5_capability_nexus_v25_whitespace.py": "c7e5375681af73b74f58338afdba75aa15b127763c005b3c45838d76cc539829",
    V25_ARTIFACT_MANIFEST: "6d23c5825c45b41a9577ccd43dac683deb9dbadd52c853298ddc61aaf0f81799",
    V25_ROOT_MANIFEST: "765d3fdc2c5a6cb2699b24ac3c3123aa490c9614e44beb749e9c91839f88fb8b",
}
V26_HISTORY = {
    "core/capability_nexus_v26.py": "ba6a49717f371ad81feffcd4e565072b6fa9727b36c9cfe6c7ca956830aec1ed",
    "tests/test_capability_nexus_v26.py": "ad9c239a33f9a503778782c6b810ca8fef71f4db65cc7cd4f5c4a19692123e08",
    "scripts/verify_phase5_capability_nexus_v26.py": "2a802c05b57e34b3053e9d7e8279cc284445193665fbcca02f8feedfbb5bc17a",
    "scripts/verify_phase5_capability_nexus_v26_worker.py": "ce76bad56870168c56eb50744682599af1abad5c63e1d7192fdaacb2558af2ae",
    "scripts/phase5_capability_nexus_v26_subtest_reporter.py": "45d976e8b4f6df61044185c23dfd2212e40888bf9160dbca827522fc1c946925",
    "scripts/check_phase5_capability_nexus_v26_whitespace.py": "cd63062747827485603dc6ce20eb92a46af51459c6c56d2a6bd7f932d66a319d",
    V26_ARTIFACT_MANIFEST: "be0b46af882855d7acee1e219b470a2e2ab9ffcc1e6b5781326c1c0839e4b508",
    V26_ROOT_MANIFEST: "1bc06d4d578bd9cc9e9a84404e22bbec47ec246e4b2c40ee47593563297d1e43",
}
V27_HISTORY = {
    "core/capability_nexus_v27.py": "ae84b12356c2c258b57fc44a9cfc6dc35c555b458509e24c846b69c97cd61abe",
    "tests/test_capability_nexus_v27.py": "5e2c89122dc321e212d0ec12698df835f4f83a17d9fc623aaffc5ca58d2eb5a9",
    "scripts/verify_phase5_capability_nexus_v27.py": "8ebba11664ff18118925494e463333b6040b4b5a3215a93e84a709f399af42b6",
    "scripts/verify_phase5_capability_nexus_v27_worker.py": "c8a829e67aa532a151f7aa0e132f4a3f2c9dd9e5dceb0ac2bdfad9a12cbfc794",
    "scripts/phase5_capability_nexus_v27_subtest_reporter.py": "b4c1a213dd5e2a5c8eb43370821e4a76d0c1fbda8e6cdabab73b6b2cc4b8c926",
    "scripts/check_phase5_capability_nexus_v27_whitespace.py": "b14478bb2ecadd74e875ce466879f4759b019b899a9af16fe33b3ac00b3efeda",
    V27_ARTIFACT_MANIFEST: "324072931ddaaff6baba1c1047434fff1b591f7bba7369b6411d8556d630bef8",
    V27_ROOT_MANIFEST: "2c9135b796c634758775d62ae4fad40782807f20f2e7f459455c49bc08f60a62",
}
V28_HISTORY = {
    "core/capability_nexus_v28.py": "4010ec3cacd14c3f6804835e04af101b72550432d345ea008c9d4f7187c1b166",
    "tests/test_capability_nexus_v28.py": "03e9b4288ecac3ce25941ce08f1d068fd3632042d58a8e2f9cfa9b1c5c4acc3b",
    "scripts/verify_phase5_capability_nexus_v28.py": "b2e9d45f66b790e4cf3158480828b51c726c0467a240d593d4d46b2fa2fc9630",
    "scripts/verify_phase5_capability_nexus_v28_worker.py": "5a47381798794725cd8700c73056b5d8c5e4d8e79460fe059a6a9228a3896235",
    "scripts/phase5_capability_nexus_v28_subtest_reporter.py": "0109b7bb5a9b972b05574481ad4a5be076179d897d3f4f96cc0208fd29a896a8",
    "scripts/check_phase5_capability_nexus_v28_whitespace.py": "b38e7bd2769349faaa4e6587cd817cdff751a995302f7cbcd47e2f29ad06e23c",
    V28_ARTIFACT_MANIFEST: "a305eb161afa80a31f434378682d778f4a2dce54aafa487719813bbaa954128a",
    V28_ROOT_MANIFEST: "a98068bd79c2d4d0c0017ea56a35c35ab357d597427427d06fbe47b844185b29",
}
V29_HISTORY = {
    "core/capability_nexus_v29.py": "7fb6735afe304d22c3cac8f0654327789a2d603a398b892ccbe32b7ef552a9ca",
    "tests/test_capability_nexus_v29.py": "3f7c2c0e7aa386d7cf46c33719ed71386f19d56411690c04ee615b900f386294",
    "scripts/verify_phase5_capability_nexus_v29.py": "088df366076d6b4b9e50df86d261f10049bcefcba5fd8cacd880252eec70f978",
    "scripts/verify_phase5_capability_nexus_v29_worker.py": "36b490ed079a639a7ef8758864c5741d6996a4ea16ca003ef84a4447666d2b76",
    "scripts/phase5_capability_nexus_v29_subtest_reporter.py": "832b1fc860a551e1cc69c0c2c9d4ce6e3951762dc6fe6b85bf6bcd5b8735c97b",
    "scripts/check_phase5_capability_nexus_v29_whitespace.py": "09edee135d535bd46a0a9f7d5406bf29d139ac6c62e4e7251446f40f466ec467",
    V29_ARTIFACT_MANIFEST: "c3450d183158860aa91bf73245883f0feb41402b8f0c4567c28854bcb10e0ec3",
    V29_ROOT_MANIFEST: "0b8ed1cf8b1b2b1e5fb770ee763021b1413973f6deea6590ad99ef04aa36fba1",
}
V30_HISTORY = {
    "core/capability_nexus_v30.py": "d2a7bc76d14eb0ade4ac3ed04ee8c6c2eeebe0b81547af4e6ae44949387cd8d6",
    "tests/test_capability_nexus_v30.py": "2e207ace99d4323d597214e3e473869488e22e0b2de415e97c816489f207a2d6",
    "scripts/verify_phase5_capability_nexus_v30.py": "8957a799793dc8e1e118336629845a4320c4439ec729d0a724e990b5e39a1f99",
    "scripts/verify_phase5_capability_nexus_v30_worker.py": "135968b40246d3d7963cc5df0f508b6d4847f427b0deccdd8888bbf10f18e749",
    "scripts/phase5_capability_nexus_v30_subtest_reporter.py": "0b16e2d30226d51483b473ae4381496597f455df87a6cd2f2bd0cea6cc9d5cb7",
    "scripts/check_phase5_capability_nexus_v30_whitespace.py": "d49bae9b5cb51acdbcd0709528db5af39c1caa65712c5192ef775049cdadff36",
    V30_ARTIFACT_MANIFEST: "13f5adecf2ee987761511a492a4066446ba6e7d42bc9a677dbab0c272b3b584a",
    V30_ROOT_MANIFEST: "e6fb21e6963902d7e358e75002376af0fae389c28177bd9bce333f7dc9d191e1",
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
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V14-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V15-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V16-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V17-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V18-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V19-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V20-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V21-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V22-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V23-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V24-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V25-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V26-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V27-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V28-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V29-001.sha256",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V30-001.sha256",
)
_LINE = re.compile(r"^([0-9a-f]{64})  ([A-Za-z0-9_./-]+)$")
_UINT_LEXICAL = re.compile(r"(?:0|[1-9][0-9]*)")
_TIME_LEXICAL = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{3}")
_PRIVATE_BASE = Path(tempfile.gettempdir()) / "onyx-p53-v31-private"
_PRIVATE_SENTINEL = ".phase53-v31-private"
_PRIVATE_CONTRACT = "Phase53CapabilityNexusPrivate.v31"


class V31EvidenceError(RuntimeError):
    pass


def _canonical_authoritative_parts(relative: str) -> tuple[str, ...]:
    if type(relative) is not str or not relative or "\\" in relative or "\x00" in relative:
        raise V31EvidenceError(f"authoritative path is not canonical: {relative!r}")
    pure = PurePosixPath(relative)
    parts = pure.parts
    if (
        pure.is_absolute()
        or not parts
        or any(part in {"", ".", ".."} for part in parts)
        or pure.as_posix() != relative
    ):
        raise V31EvidenceError(f"authoritative path is not canonical: {relative}")
    return parts


def _assert_no_reparse(relative: str) -> None:
    """Validate exact workspace containment and every component before content access."""
    parts = _canonical_authoritative_parts(relative)
    reparse_flag = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)
    try:
        root_info = PROJECT.lstat()
        root_resolved = PROJECT.resolve(strict=True)
    except OSError as exc:
        raise V31EvidenceError(f"authoritative workspace root is missing: {relative}") from exc
    if stat.S_ISLNK(root_info.st_mode) or getattr(root_info, "st_file_attributes", 0) & reparse_flag:
        raise V31EvidenceError(f"authoritative workspace root is a reparse point: {relative}")
    if str(PROJECT.absolute()) != str(root_resolved):
        raise V31EvidenceError(f"authoritative workspace root uses a path alias: {relative}")
    current = PROJECT
    for component in parts:
        current /= component
        try:
            info = current.lstat()
        except OSError as exc:
            raise V31EvidenceError(f"authoritative path is missing: {relative}") from exc
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & reparse_flag:
            raise V31EvidenceError(f"authoritative path contains a reparse component: {relative}")
        try:
            resolved_component = current.resolve(strict=True)
        except OSError as exc:
            raise V31EvidenceError(f"authoritative path is missing: {relative}") from exc
        if resolved_component.name != component:
            raise V31EvidenceError(f"authoritative path uses a case or name alias: {relative}")
    try:
        current.resolve(strict=True).relative_to(root_resolved)
    except (OSError, ValueError) as exc:
        raise V31EvidenceError(f"authoritative path escapes workspace: {relative}") from exc


def _guard_project_path(path: Path) -> None:
    try:
        relative = path.relative_to(PROJECT).as_posix()
    except ValueError:
        return
    _assert_no_reparse(relative)


def _read_bytes(relative: str) -> bytes:
    _assert_no_reparse(relative)
    return (PROJECT / relative).read_bytes()


def _read_text(relative: str) -> str:
    _assert_no_reparse(relative)
    return (PROJECT / relative).read_text(encoding="utf-8")


def _sha(path: Path) -> str:
    _guard_project_path(path)
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _manifest(relative: str) -> tuple[tuple[str, str], ...]:
    _assert_no_reparse(relative)
    raw = (PROJECT / relative).read_bytes()
    if b"\r" in raw or not raw.endswith(b"\n"):
        raise V31EvidenceError(f"manifest line endings are invalid: {relative}")
    entries = []
    for line in raw.decode().splitlines():
        match = _LINE.fullmatch(line)
        if match is None:
            raise V31EvidenceError(f"manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V31EvidenceError("manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or paths != sorted(paths) or len(paths) != len(set(paths)):
        raise V31EvidenceError(f"manifest set is invalid: {relative}")
    return tuple(entries)


def _historical_manifest(relative: str) -> tuple[tuple[str, str], ...]:
    """Parse byte-bound legacy manifests without rewriting old line-ending policy."""
    _assert_no_reparse(relative)
    try:
        lines = (PROJECT / relative).read_text(encoding="utf-8").splitlines()
    except UnicodeError as exc:
        raise V31EvidenceError(f"historical manifest encoding is invalid: {relative}") from exc
    entries = []
    for line in lines:
        match = _LINE.fullmatch(line)
        if match is None:
            raise V31EvidenceError(f"historical manifest line is invalid: {relative}")
        digest, path = match.groups()
        if path.startswith("/") or ".." in Path(path).parts or "\\" in path:
            raise V31EvidenceError("historical manifest path is unsafe")
        entries.append((digest, path))
    paths = [path for _, path in entries]
    if not entries or len(paths) != len(set(paths)):
        raise V31EvidenceError(f"historical manifest set is invalid: {relative}")
    return tuple(entries)


def _dag() -> tuple[str, ...]:
    root = _manifest(ROOT_MANIFEST)
    if root != ((_sha(PROJECT / ARTIFACT_MANIFEST), ARTIFACT_MANIFEST),):
        raise V31EvidenceError("root manifest edge is invalid")
    artifacts = _manifest(ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        CORE, TESTS, SELF, WORKER, REPORTER, WHITESPACE, CHECKPOINT, BUNDLE, JUNIT, RAW,
        STATIC, LIVE, METRICS, COMBINED_JUNIT, REGRESSION_JUNIT, REGRESSION_REPORT,
        MUTABLE_PROJECTION_MAP, *MUTABLE_PROJECTION_SNAPSHOTS,
        V1_LIVE, V2_LIVE, V3_LIVE, V4_LIVE, V5_LIVE, V6_LIVE, V7_LIVE,
        V8_LIVE, V9_LIVE, V10_LIVE, V11_LIVE, V12_LIVE, V13_LIVE, V14_LIVE, V15_LIVE, V16_LIVE, V17_LIVE, V18_LIVE, V19_LIVE, V20_LIVE, V21_LIVE, V22_LIVE, V23_LIVE, V24_LIVE, V25_LIVE, V26_LIVE, V27_LIVE, V28_LIVE, V29_LIVE, V30_LIVE,
        *V1_HISTORY, *V2_HISTORY, *V3_HISTORY, *V4_HISTORY, *V5_HISTORY,
        *V6_HISTORY, *V7_HISTORY, *V8_HISTORY, *V9_HISTORY, *V10_HISTORY,
        *V11_HISTORY, *V12_HISTORY, *V13_HISTORY, *V14_HISTORY, *V15_HISTORY, *V16_HISTORY, *V17_HISTORY, *V18_HISTORY, *V19_HISTORY, *V20_HISTORY, *V21_HISTORY, *V22_HISTORY, *V23_HISTORY, *V24_HISTORY, *V25_HISTORY, *V26_HISTORY, *V27_HISTORY, *V28_HISTORY, *V29_HISTORY, *V30_HISTORY,
    }
    if not required.issubset(paths) or ARTIFACT_MANIFEST in paths or ROOT_MANIFEST in paths:
        raise V31EvidenceError("artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _assert_no_reparse(relative)
        if not (PROJECT / relative).is_file() or _sha(PROJECT / relative) != digest:
            raise V31EvidenceError(f"artifact hash mismatch: {relative}")
    return paths


def _bundle(paths: tuple[str, ...]) -> dict[str, object]:
    _assert_no_reparse(BUNDLE)
    raw = (PROJECT / BUNDLE).read_text(encoding="utf-8")
    try:
        bundle = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V31EvidenceError("bundle JSON is invalid") from exc
    if raw != json.dumps(bundle, sort_keys=True, separators=(",", ":")) + "\n":
        raise V31EvidenceError("bundle JSON is not canonical")
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v31" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V31EvidenceError("bundle contract/status is invalid")
    if bundle.get("external_e6") != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}:
        raise V31EvidenceError("bundle overstates acceptance")
    if bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}:
        raise V31EvidenceError("bundle feature gate is invalid")
    files = bundle.get("files")
    expected = set(paths) - {BUNDLE}
    if not isinstance(files, dict) or set(files) != expected:
        raise V31EvidenceError("bundle file set is invalid")
    for relative, digest in files.items():
        if digest != _sha(PROJECT / relative):
            raise V31EvidenceError(f"bundle file hash mismatch: {relative}")
    return bundle


def _regression_report() -> dict[str, object]:
    report = _canonical_json(REGRESSION_REPORT)
    _validate_regression_report(report)
    return report


def _validate_regression_report(report: dict[str, object]) -> None:
    if set(report) != {"base_tests", "contract", "exit_status", "subtests"}:
        raise V31EvidenceError("regression report schema is invalid")
    if report.get("contract") != "Phase53CapabilityNexusRegressionReport.v31" or report.get("exit_status") != 0:
        raise V31EvidenceError("regression report contract/status is invalid")
    bases = report.get("base_tests")
    subtests = report.get("subtests")
    if not isinstance(bases, list) or not isinstance(subtests, list) or len(bases) != 102 or len(subtests) != 221:
        raise V31EvidenceError("regression report semantic counts are invalid")
    base_nodeids: set[str] = set()
    base_identities: set[str] = set()
    for base in bases:
        if not isinstance(base, dict) or set(base) != {"identity", "nodeid", "outcome"} or base.get("outcome") != "passed":
            raise V31EvidenceError("regression base record is invalid")
        nodeid = base.get("nodeid")
        identity = base.get("identity")
        expected = hashlib.sha256(
            ("base\0" + json.dumps({"nodeid": nodeid, "outcome": "passed"}, sort_keys=True, separators=(",", ":"))).encode("ascii")
        ).hexdigest()
        if not isinstance(nodeid, str) or identity != expected or nodeid in base_nodeids or identity in base_identities:
            raise V31EvidenceError("regression base identity is invalid or duplicated")
        base_nodeids.add(nodeid)
        base_identities.add(identity)
    subtest_identities: set[str] = set()
    subtest_nodeids: set[str] = set()
    ordinals: dict[str, list[int]] = {}
    for subtest in subtests:
        expected_keys = {"context", "identity", "nodeid", "ordinal", "outcome", "parent_nodeid"}
        if not isinstance(subtest, dict) or set(subtest) != expected_keys or subtest.get("outcome") != "passed":
            raise V31EvidenceError("regression subtest record is invalid")
        parent = subtest.get("parent_nodeid")
        context = subtest.get("context")
        ordinal = subtest.get("ordinal")
        identity = subtest.get("identity")
        nodeid = subtest.get("nodeid")
        if (
            parent not in base_nodeids
            or not isinstance(context, dict)
            or set(context) != {"message", "parameters"}
            or not isinstance(context.get("parameters"), dict)
            or type(ordinal) is not int
            or ordinal < 0
        ):
            raise V31EvidenceError("regression subtest parent/context is invalid")
        descriptor = {"context": context, "ordinal": ordinal, "parent_nodeid": parent}
        expected_identity = hashlib.sha256(
            ("subtest\0" + json.dumps(descriptor, sort_keys=True, separators=(",", ":"))).encode("ascii")
        ).hexdigest()
        if (
            identity != expected_identity
            or nodeid != f"{parent}::subtest[{expected_identity[:16]}]"
            or identity in subtest_identities
            or nodeid in subtest_nodeids
        ):
            raise V31EvidenceError("regression subtest identity is invalid or duplicated")
        subtest_identities.add(identity)
        subtest_nodeids.add(nodeid)
        ordinals.setdefault(parent, []).append(ordinal)
    if any(sorted(values) != list(range(len(values))) for values in ordinals.values()):
        raise V31EvidenceError("regression subtest ordinals are not contiguous")


def _junit_nodeid(testcase: ET.Element) -> str:
    classname = testcase.attrib.get("classname", "")
    name = testcase.attrib.get("name", "")
    prefix = "tests.test_regressions"
    if not classname.startswith(prefix) or not name:
        raise V31EvidenceError("regression JUnit testcase identity is invalid")
    suffix = classname[len(prefix):].lstrip(".")
    return "tests/test_regressions.py" + ("::" + suffix.replace(".", "::") if suffix else "") + "::" + name


def _require_whitespace_only(value: str | None, label: str) -> None:
    if value is not None and value.strip():
        raise V31EvidenceError(f"JUnit {label} contains unexpected text")


def _canonical_counter(value: str, label: str) -> int:
    if _UINT_LEXICAL.fullmatch(value) is None:
        raise V31EvidenceError(f"JUnit {label} counter lexical form is invalid")
    return int(value)


def _canonical_time(value: str, label: str) -> float:
    if _TIME_LEXICAL.fullmatch(value) is None:
        raise V31EvidenceError(f"JUnit {label} duration lexical form is invalid")
    duration = float(value)
    if not math.isfinite(duration) or duration < 0:
        raise V31EvidenceError(f"JUnit {label} duration is invalid")
    return duration


def _junit_path(path: Path, *, subtest_report: dict[str, object] | None = None) -> dict[str, int]:
    _guard_project_path(path)
    raw = path.read_bytes()
    document_body = raw
    if document_body.startswith(b"<?xml"):
        declaration_end = document_body.find(b"?>")
        if declaration_end < 0:
            raise V31EvidenceError("JUnit XML declaration is malformed")
        document_body = document_body[declaration_end + 2:]
    if b"<!--" in raw or b"<?" in document_body:
        raise V31EvidenceError("JUnit comments and processing instructions are forbidden")
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise V31EvidenceError("JUnit XML is malformed") from exc
    if root.tag != "testsuites" or root.attrib != {"name": "pytest tests"}:
        raise V31EvidenceError("JUnit root schema is invalid")
    _require_whitespace_only(root.text, "root")
    _require_whitespace_only(root.tail, "root tail")
    suites = list(root)
    if len(suites) != 1 or suites[0].tag != "testsuite":
        raise V31EvidenceError("JUnit must contain exactly one suite")
    tests = failed = errors = skipped = testcase_count = 0
    testcases: list[ET.Element] = []
    for suite in suites:
        allowed_suite = {"name", "errors", "failures", "skipped", "tests", "time", "timestamp", "hostname"}
        if set(suite.attrib) != allowed_suite or suite.attrib.get("name") != "pytest":
            raise V31EvidenceError("JUnit suite attribute schema is invalid")
        _canonical_time(suite.attrib["time"], "suite")
        try:
            datetime.fromisoformat(suite.attrib["timestamp"])
        except (ValueError, TypeError) as exc:
            raise V31EvidenceError("JUnit suite timestamp is invalid") from exc
        if not suite.attrib["hostname"]:
            raise V31EvidenceError("JUnit suite hostname is invalid")
        _require_whitespace_only(suite.text, "suite")
        _require_whitespace_only(suite.tail, "suite tail")
        attrs = {
            key: _canonical_counter(suite.attrib[key], f"suite {key}")
            for key in ("tests", "failures", "errors", "skipped")
        }
        children = list(suite)
        if any(item.tag != "testcase" for item in children):
            raise V31EvidenceError("JUnit suite contains an unexpected child")
        for testcase in children:
            if set(testcase.attrib) != {"classname", "name", "time"}:
                raise V31EvidenceError("JUnit testcase attribute schema is invalid")
            if not testcase.attrib["classname"] or not testcase.attrib["name"]:
                raise V31EvidenceError("JUnit testcase identity is empty")
            _canonical_time(testcase.attrib["time"], "testcase")
            _require_whitespace_only(testcase.text, "testcase")
            _require_whitespace_only(testcase.tail, "testcase tail")
            outcome_children = list(testcase)
            if len(outcome_children) > 1 or any(item.tag not in {"failure", "error", "skipped"} for item in outcome_children):
                raise V31EvidenceError("JUnit testcase contains an unexpected child")
            for outcome in outcome_children:
                if set(outcome.attrib) - {"message", "type"} or list(outcome):
                    raise V31EvidenceError("JUnit outcome element schema is invalid")
                _require_whitespace_only(outcome.text, "outcome")
                _require_whitespace_only(outcome.tail, "outcome tail")
        child_failed = sum(len(item.findall("failure")) for item in children)
        child_errors = sum(len(item.findall("error")) for item in children)
        child_skipped = sum(len(item.findall("skipped")) for item in children)
        if attrs["failures"] != child_failed or attrs["errors"] != child_errors or attrs["skipped"] != child_skipped:
            raise V31EvidenceError("JUnit suite counters do not reconcile with testcase children")
        tests += attrs["tests"]
        failed += child_failed
        errors += child_errors
        skipped += child_skipped
        testcase_count += len(children)
        testcases.extend(children)
    delta = tests - testcase_count
    if delta < 0:
        raise V31EvidenceError("JUnit reports fewer tests than testcase children")
    if delta:
        if subtest_report is None or len(subtest_report["subtests"]) != delta:
            raise V31EvidenceError("JUnit synthetic count delta lacks validated subtest evidence")
        bases = subtest_report["base_tests"]
        if len(bases) != testcase_count:
            raise V31EvidenceError("JUnit testcase count does not match base-test evidence")
        xml_nodeids = {_junit_nodeid(item) for item in testcases}
        report_nodeids = {item["nodeid"] for item in bases}
        if len(xml_nodeids) != testcase_count or xml_nodeids != report_nodeids:
            raise V31EvidenceError("JUnit testcase identities do not match base-test evidence")
        if failed or errors or skipped or any(item["outcome"] != "passed" for item in bases):
            raise V31EvidenceError("JUnit outcomes do not match all-pass base/subtest evidence")
    return {"errors": errors, "failed": failed, "passed": tests - failed - errors - skipped, "skipped": skipped}


def _junit() -> dict[str, int]:
    return _junit_path(PROJECT / JUNIT)


def _static_path(path: Path, *, frozen_gate: str = "FROZEN_PROOF") -> dict[str, int]:
    _guard_project_path(path)
    result = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, separator, value = line.partition("=")
        if not separator or not value.isdigit():
            raise V31EvidenceError("static log is invalid")
        result[key] = int(value)
    expected = {
        "COMPILE", "DIFF_CHECK", "FOCUSED", frozen_gate,
        "HISTORICAL_TAMPER", "REGRESSIONS", "RUFF", "WHITESPACE",
    }
    if set(result) != expected or any(result.values()):
        raise V31EvidenceError("static gate failed")
    return result


def _static() -> dict[str, int]:
    return _static_path(PROJECT / STATIC)


def _canonical_json(relative: str) -> dict[str, object]:
    _assert_no_reparse(relative)
    raw = (PROJECT / relative).read_text(encoding="utf-8")
    try:
        value = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise V31EvidenceError(f"structured evidence JSON is invalid: {relative}") from exc
    if not isinstance(value, dict) or raw != json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n":
        raise V31EvidenceError(f"structured evidence JSON is not canonical: {relative}")
    return value


def _projection_mapping() -> dict[str, dict[str, str]]:
    _assert_no_reparse(MUTABLE_PROJECTION_MAP)
    value = _canonical_json(MUTABLE_PROJECTION_MAP)
    if set(value) != {"contract", "entries"} or value.get("contract") != "Phase53CapabilityNexusMutableProjections.v31":
        raise V31EvidenceError("mutable projection mapping contract is invalid")
    entries = value.get("entries")
    if not isinstance(entries, list) or len(entries) != len(MUTABLE_PROJECTIONS):
        raise V31EvidenceError("mutable projection mapping cardinality is invalid")
    result: dict[str, dict[str, str]] = {}
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != {
            "path", "snapshot", "snapshot_sha256", "source_sha256",
        } or not all(isinstance(item, str) for item in entry.values()):
            raise V31EvidenceError("mutable projection mapping entry is invalid")
        path = entry["path"]
        expected_digest = MUTABLE_PROJECTION_HASHES.get(path)
        snapshot = entry["snapshot"]
        if (
            expected_digest is None
            or path in result
            or entry["source_sha256"] != expected_digest
            or entry["snapshot_sha256"] != expected_digest
            or snapshot != f"{EVIDENCE}/mutable-projections/{expected_digest}.snapshot"
        ):
            raise V31EvidenceError("mutable projection mapping is not exact")
        _assert_no_reparse(snapshot)
        if _sha(PROJECT / snapshot) != expected_digest:
            raise V31EvidenceError("mutable projection snapshot hash mismatch")
        result[path] = entry
    if tuple(result) != MUTABLE_PROJECTIONS or tuple(
        entry["snapshot"] for entry in result.values()
    ) != MUTABLE_PROJECTION_SNAPSHOTS:
        raise V31EvidenceError("mutable projection allowlist is missing, extra, or reordered")
    return result


def _mutable_projection_evidence() -> dict[str, object]:
    mapping = _projection_mapping()
    return {
        "authority": "content_addressed_frozen_snapshots_not_external_projection_paths",
        "entries": [mapping[path] for path in MUTABLE_PROJECTIONS],
        "mapping_sha256": _sha(PROJECT / MUTABLE_PROJECTION_MAP),
        "projection_paths_are_authority": False,
    }


def _historical_sha(relative: str) -> str:
    if relative in MUTABLE_PROJECTIONS:
        return _projection_mapping()[relative]["source_sha256"]
    return _sha(PROJECT / relative)


def _sum_counts(items: list[dict[str, int]]) -> dict[str, int]:
    keys = {"errors", "failed", "passed", "skipped"}
    if not items or any(set(item) != keys for item in items):
        raise V31EvidenceError("JUnit count schema is invalid")
    return {key: sum(item[key] for item in items) for key in sorted(keys)}


def _assert_exact_evidence(label: str, actual: object, expected: object) -> None:
    if type(actual) is not type(expected):
        raise V31EvidenceError(f"{label} evidence type drift")
    if isinstance(expected, dict):
        if set(actual) != set(expected):  # type: ignore[arg-type]
            raise V31EvidenceError(f"{label} evidence field drift")
        for key, value in expected.items():
            _assert_exact_evidence(f"{label}.{key}", actual[key], value)  # type: ignore[index]
        return
    if isinstance(expected, list):
        if len(actual) != len(expected):  # type: ignore[arg-type]
            raise V31EvidenceError(f"{label} evidence list drift")
        for index, value in enumerate(expected):
            _assert_exact_evidence(f"{label}[{index}]", actual[index], value)  # type: ignore[index]
        return
    if actual != expected:
        raise V31EvidenceError(f"{label} evidence value drift")


def _historical_focused_counts() -> list[dict[str, int]]:
    paths = [
        PROJECT
        / f"docs/onyx/checkpoints/phase5-capability-nexus-v{version}/phase5-capability-nexus-v{version}.junit.xml"
        for version in range(1, 31)
    ]
    return [_junit_path(path) for path in paths]


def _checkpoint() -> None:
    text = _read_text(CHECKPOINT)
    required = {
        "Status: **candidate — default-off, shadow-only, external acceptance pending**",
        "V31 preserves rejected V1–V30 byte-for-byte.",
        f"Quantitative evidence is exclusively recorded in `{METRICS}`.",
        "No quantitative result in this checkpoint is accepted outside that structured artifact.",
    }
    if not required.issubset(set(text.splitlines())):
        raise V31EvidenceError("checkpoint status or structured-evidence claim is invalid")
    unchecked = re.compile(
        r"(?i)\b(?:passed|artifacts?|files?|manifests?|leaves|fixtures?|subtests?|seconds?)\s*[:=]?\s*\d+"
    )
    if unchecked.search(text):
        raise V31EvidenceError("checkpoint contains an unchecked quantitative claim")


def _validate_metrics(
    paths: tuple[str, ...],
    focused: dict[str, int],
    static: dict[str, int],
    history: dict[str, object],
    tamper: dict[str, object],
    live: dict[str, object],
) -> dict[str, object]:
    metrics = _canonical_json(METRICS)
    expected_keys = {
        "artifact", "combined", "contract", "history", "live", "mutable_projections",
        "regressions", "runtime", "static", "tamper",
    }
    if set(metrics) != expected_keys or metrics.get("contract") != "Phase53CapabilityNexusMetrics.v31":
        raise V31EvidenceError("structured evidence top-level schema is invalid")

    artifact = metrics.get("artifact")
    expected_artifact = {"entries": len(paths), "unique": len(paths) == len(set(paths))}
    _assert_exact_evidence("artifact", artifact, expected_artifact)

    combined_junit = _junit_path(PROJECT / COMBINED_JUNIT)
    summed = _sum_counts([*_historical_focused_counts(), focused])
    combined = metrics.get("combined")
    expected_combined = {
        "counts": combined_junit,
        "exit_code": 0,
        "junit_sha256": _sha(PROJECT / COMBINED_JUNIT),
        "selected_suites": list(COMBINED_SUITES),
        "unique_suites": len(COMBINED_SUITES) == len(set(COMBINED_SUITES)),
    }
    _assert_exact_evidence("combined", combined, expected_combined)
    _assert_exact_evidence("combined.summed", combined_junit, summed)

    regression_report = _regression_report()
    regression_junit = _junit_path(PROJECT / REGRESSION_JUNIT, subtest_report=regression_report)
    regressions = metrics.get("regressions")
    expected_regressions = {
        "base_tests_passed": 102,
        "exit_code": 0,
        "junit_counts": regression_junit,
        "junit_duration_policy": "canonical_millisecond_decimal_lexical_finite_nonnegative_not_summed",
        "junit_schema": "strict_single_pytest_suite_lexical_v31",
        "junit_sha256": _sha(PROJECT / REGRESSION_JUNIT),
        "junit_testcase_elements": 102,
        "report_sha256": _sha(PROJECT / REGRESSION_REPORT),
        "selected_suites": list(REGRESSION_SUITES),
        "subtest_records": 221,
        "subtests_passed": 221,
        "unique_suites": True,
    }
    _assert_exact_evidence("regressions", regressions, expected_regressions)
    if regression_junit.get("passed") != 323:
        raise V31EvidenceError("structured regression JUnit semantic count drift")

    _assert_exact_evidence("history", metrics.get("history"), history)
    _assert_exact_evidence("tamper", metrics.get("tamper"), tamper)
    _assert_exact_evidence(
        "static", metrics.get("static"), {"exit_codes": static, "selected_gates": sorted(static)}
    )
    _assert_exact_evidence("live", metrics.get("live"), live)
    _assert_exact_evidence(
        "mutable_projections",
        metrics.get("mutable_projections"),
        _mutable_projection_evidence(),
    )
    runtime = metrics.get("runtime")
    if not isinstance(runtime, dict) or set(runtime) != {
        "architecture", "arbitrary_command_surfaces", "phase_ids", "windows_launch",
        "closehandle_fail_closed", "fresh_junit_scope", "measured_full_verifier_seconds", "parent_direct_phases",
        "parent_owned_tree_roots", "post_kill_drain_seconds", "total_timeout_seconds",
        "tree_ownership", "windows_processes_per_phase", "worker_subprocesses",
    }:
        raise V31EvidenceError("structured runtime evidence schema is invalid")
    if (
        runtime.get("architecture") != "fixed_phase_direct_createprocess_suspended_job_resume"
        or runtime.get("arbitrary_command_surfaces") != 0
        or runtime.get("phase_ids") != ["focused", "worker"]
        or runtime.get("windows_launch") != "CreateProcessW_CREATE_SUSPENDED_Assign_ResumeThread"
        or runtime.get("closehandle_fail_closed") is not True
        or runtime.get("fresh_junit_scope") != "fixed_private_nonce_directory_realpath_sentinel"
        or runtime.get("parent_direct_phases") != ["focused_pytest", "pure_artifact_worker"]
        or runtime.get("parent_owned_tree_roots") != 2
        or runtime.get("post_kill_drain_seconds") != 2
        or runtime.get("total_timeout_seconds") != 180
        or runtime.get("tree_ownership") != {
            "posix": "popen_immediate_ownership_recursive_flat_cleanup_records",
            "windows": "create_suspended_assign_job_then_resume_checked_close",
        }
        or runtime.get("windows_processes_per_phase") != 1
        or runtime.get("worker_subprocesses") != 0
    ):
        raise V31EvidenceError("structured runtime timeout evidence drift")
    measured = runtime.get("measured_full_verifier_seconds")
    if type(measured) not in {int, float} or not 0 < measured <= 180:
        raise V31EvidenceError("structured measured verifier runtime is invalid")
    return metrics


def _validate_frozen_v14_proof() -> dict[str, object]:
    root = _historical_manifest(V14_ROOT_MANIFEST)
    expected_root = ((V14_HISTORY[V14_ARTIFACT_MANIFEST], V14_ARTIFACT_MANIFEST),)
    if root != expected_root:
        raise V31EvidenceError("frozen V14 root manifest edge is invalid")
    _verify_historical_path(V14_ARTIFACT_MANIFEST, expected_root[0][0])

    artifacts = _historical_manifest(V14_ARTIFACT_MANIFEST)
    artifact_paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v14.py",
        "tests/test_capability_nexus_v14.py",
        V14_VERIFIER,
        "scripts/check_phase5_capability_nexus_v14_whitespace.py",
        V14_CHECKPOINT,
        V14_BUNDLE,
        V14_JUNIT,
        V14_STATIC,
        V14_LIVE,
        *HISTORICAL_ROOTS[:13],
    }
    if (
        len(artifacts) != 164
        or artifact_paths != tuple(sorted(artifact_paths))
        or len(artifact_paths) != len(set(artifact_paths))
        or not required.issubset(artifact_paths)
        or V14_ARTIFACT_MANIFEST in artifact_paths
        or V14_ROOT_MANIFEST in artifact_paths
    ):
        raise V31EvidenceError("frozen V14 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)

    bundle = _canonical_json(V14_BUNDLE)
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v14"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
    ):
        raise V31EvidenceError("frozen V14 bundle contract/status is invalid")
    files = bundle.get("files")
    expected_files = set(artifact_paths) - {V14_BUNDLE}
    if not isinstance(files, dict) or set(files) != expected_files:
        raise V31EvidenceError("frozen V14 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V14 bundle file hash mismatch: {relative}")

    expected_history = {
        f"phase53_v{version}": {"decision": "rejected", "hashes": history}
        for version, history in enumerate(
            (
                V1_HISTORY, V2_HISTORY, V3_HISTORY, V4_HISTORY, V5_HISTORY, V6_HISTORY,
                V7_HISTORY, V8_HISTORY, V9_HISTORY, V10_HISTORY, V11_HISTORY, V12_HISTORY,
                V13_HISTORY,
            ),
            start=1,
        )
    }
    if bundle.get("history") != expected_history:
        raise V31EvidenceError("frozen V14 rejected-history contract is invalid")

    junit = _junit_path(PROJECT / V14_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1752, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V14 JUnit evidence is invalid")
    static = _static_path(PROJECT / V14_STATIC, frozen_gate="FROZEN_VERIFIERS")
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V14 static evidence is invalid")
    live_entries = _historical_manifest(V14_LIVE)
    if live_entries != (
        (V13_HISTORY["core/capability_nexus_v13.py"], "core/capability_nexus_v13.py"),
        ("68c948ed08ce137cd282f284a45e6150af85f0d2640b909f96129b93f6a7622b", V13_LIVE),
    ):
        raise V31EvidenceError("frozen V14 live manifest anchors are invalid")
    for digest, relative in live_entries:
        _verify_historical_path(relative, digest)
    if bundle.get("live_scan") != {"count": 93, "manifest_sha256": _sha(PROJECT / V14_LIVE)}:
        raise V31EvidenceError("frozen V14 live evidence is invalid")
    checkpoint = _read_text(V14_CHECKPOINT)
    if "Status: **candidate" not in checkpoint or "external" not in checkpoint.lower():
        raise V31EvidenceError("frozen V14 checkpoint status is invalid")
    verifier = _read_text(V14_VERIFIER)
    if "P53_CAPABILITY_NEXUS_V14_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V14 verifier marker contract is missing")
    return {
        "artifact_entries": len(artifacts),
        "bundle_status": bundle["status"],
        "junit_passed": junit["passed"],
        "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True,
        "static_gates": len(static),
    }


def _validate_frozen_v15_proof() -> dict[str, object]:
    root = _historical_manifest(V15_ROOT_MANIFEST)
    expected_root = ((V15_HISTORY[V15_ARTIFACT_MANIFEST], V15_ARTIFACT_MANIFEST),)
    if root != expected_root:
        raise V31EvidenceError("frozen V15 root manifest edge is invalid")
    artifacts = _historical_manifest(V15_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v15.py", "tests/test_capability_nexus_v15.py", V15_VERIFIER,
        "scripts/check_phase5_capability_nexus_v15_whitespace.py", V15_CHECKPOINT,
        V15_BUNDLE, V15_JUNIT, V15_STATIC, V15_LIVE, V14_ROOT_MANIFEST,
    }
    if len(artifacts) != 179 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V15 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V15_BUNDLE)
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v15"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
    ):
        raise V31EvidenceError("frozen V15 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V15_BUNDLE}:
        raise V31EvidenceError("frozen V15 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V15 bundle file hash mismatch: {relative}")
    expected_history = {
        f"phase53_v{version}": {"decision": "rejected", "hashes": history}
        for version, history in enumerate(
            (V1_HISTORY, V2_HISTORY, V3_HISTORY, V4_HISTORY, V5_HISTORY, V6_HISTORY, V7_HISTORY,
             V8_HISTORY, V9_HISTORY, V10_HISTORY, V11_HISTORY, V12_HISTORY, V13_HISTORY, V14_HISTORY),
            start=1,
        )
    }
    if bundle.get("history") != expected_history:
        raise V31EvidenceError("frozen V15 rejected-history contract is invalid")
    junit = _junit_path(PROJECT / V15_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1798, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V15 JUnit evidence is invalid")
    static = _static_path(PROJECT / V15_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V15 static evidence is invalid")
    live_entries = _historical_manifest(V15_LIVE)
    if live_entries != (
        (V14_HISTORY["core/capability_nexus_v14.py"], "core/capability_nexus_v14.py"),
        ("f26c14e3218c5d3538de30142bfcd1d3ff1919633c0c7655a2ced2af5a35ee9e", V14_LIVE),
    ):
        raise V31EvidenceError("frozen V15 live manifest anchors are invalid")
    if bundle.get("live_scan") != {"count": 94, "manifest_sha256": _sha(PROJECT / V15_LIVE)}:
        raise V31EvidenceError("frozen V15 live evidence is invalid")
    checkpoint = _read_text(V15_CHECKPOINT)
    verifier = _read_text(V15_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V15_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V15 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v16_proof() -> dict[str, object]:
    root = _historical_manifest(V16_ROOT_MANIFEST)
    if root != ((V16_HISTORY[V16_ARTIFACT_MANIFEST], V16_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V16 root manifest edge is invalid")
    artifacts = _historical_manifest(V16_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v16.py", "tests/test_capability_nexus_v16.py", V16_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v16_worker.py",
        "scripts/phase5_capability_nexus_v16_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v16_whitespace.py", V16_CHECKPOINT,
        V16_BUNDLE, V16_JUNIT, V16_STATIC, V16_LIVE, V15_ROOT_MANIFEST,
    }
    if len(artifacts) != 197 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V16 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V16_BUNDLE)
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v16"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
    ):
        raise V31EvidenceError("frozen V16 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V16_BUNDLE}:
        raise V31EvidenceError("frozen V16 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V16 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V16_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1826, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V16 JUnit evidence is invalid")
    static = _static_path(PROJECT / V16_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V16 static evidence is invalid")
    live_entries = _historical_manifest(V16_LIVE)
    if live_entries != (
        (V15_HISTORY["core/capability_nexus_v15.py"], "core/capability_nexus_v15.py"),
        ("f9c817d68bd7b918ebfdfb00a3a7690277ee6cc9472775a7ce82742cf4fbc3a0", V15_LIVE),
    ) or bundle.get("live_scan") != {"count": 95, "manifest_sha256": _sha(PROJECT / V16_LIVE)}:
        raise V31EvidenceError("frozen V16 live evidence is invalid")
    checkpoint = _read_text(V16_CHECKPOINT)
    verifier = _read_text(V16_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V16_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V16 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v17_proof() -> dict[str, object]:
    root = _historical_manifest(V17_ROOT_MANIFEST)
    if root != ((V17_HISTORY[V17_ARTIFACT_MANIFEST], V17_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V17 root manifest edge is invalid")
    artifacts = _historical_manifest(V17_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v17.py", "tests/test_capability_nexus_v17.py", V17_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v17_worker.py",
        "scripts/phase5_capability_nexus_v17_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v17_whitespace.py", V17_CHECKPOINT,
        V17_BUNDLE, V17_JUNIT, V17_STATIC, V17_LIVE, V16_ROOT_MANIFEST,
    }
    if len(artifacts) != 215 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V17 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V17_BUNDLE)
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v17"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
    ):
        raise V31EvidenceError("frozen V17 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V17_BUNDLE}:
        raise V31EvidenceError("frozen V17 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V17 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V17_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1847, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V17 JUnit evidence is invalid")
    static = _static_path(PROJECT / V17_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V17 static evidence is invalid")
    live_entries = _historical_manifest(V17_LIVE)
    if live_entries != (
        (V16_HISTORY["core/capability_nexus_v16.py"], "core/capability_nexus_v16.py"),
        ("210126f38d216a7a11a6b5966c577451cb7bf51fd57f4ee6de64e36f8d48a72c", V16_LIVE),
    ) or bundle.get("live_scan") != {"count": 96, "manifest_sha256": _sha(PROJECT / V17_LIVE)}:
        raise V31EvidenceError("frozen V17 live evidence is invalid")
    checkpoint = _read_text(V17_CHECKPOINT)
    verifier = _read_text(V17_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V17_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V17 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v18_proof() -> dict[str, object]:
    root = _historical_manifest(V18_ROOT_MANIFEST)
    if root != ((V18_HISTORY[V18_ARTIFACT_MANIFEST], V18_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V18 root manifest edge is invalid")
    artifacts = _historical_manifest(V18_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v18.py", "tests/test_capability_nexus_v18.py", V18_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v18_worker.py",
        "scripts/phase5_capability_nexus_v18_bootstrap.py",
        "scripts/phase5_capability_nexus_v18_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v18_whitespace.py", V18_CHECKPOINT,
        V18_BUNDLE, V18_JUNIT, V18_STATIC, V18_LIVE, V17_ROOT_MANIFEST,
    }
    if len(artifacts) != 234 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V18 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V18_BUNDLE)
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v18"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("feature_gate") != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
    ):
        raise V31EvidenceError("frozen V18 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V18_BUNDLE}:
        raise V31EvidenceError("frozen V18 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V18 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V18_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1875, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V18 JUnit evidence is invalid")
    static = _static_path(PROJECT / V18_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V18 static evidence is invalid")
    live_entries = _historical_manifest(V18_LIVE)
    if live_entries != (
        (V17_HISTORY["core/capability_nexus_v17.py"], "core/capability_nexus_v17.py"),
        ("21bc2289bde4d928f85ff0d230752faa646b06b0b6bf2f0fda420380737c68fd", V17_LIVE),
    ) or bundle.get("live_scan") != {"count": 97, "manifest_sha256": _sha(PROJECT / V18_LIVE)}:
        raise V31EvidenceError("frozen V18 live evidence is invalid")
    checkpoint = _read_text(V18_CHECKPOINT)
    verifier = _read_text(V18_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V18_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V18 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v19_proof() -> dict[str, object]:
    root = _historical_manifest(V19_ROOT_MANIFEST)
    if root != ((V19_HISTORY[V19_ARTIFACT_MANIFEST], V19_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V19 root manifest edge is invalid")
    artifacts = _historical_manifest(V19_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v19.py", "tests/test_capability_nexus_v19.py", V19_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v19_worker.py",
        "scripts/phase5_capability_nexus_v19_bootstrap.py",
        "scripts/phase5_capability_nexus_v19_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v19_whitespace.py", V19_CHECKPOINT,
        V19_BUNDLE, V19_JUNIT, V19_STATIC, V19_LIVE, V18_ROOT_MANIFEST,
    }
    if len(artifacts) != 253 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V19 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V19_BUNDLE)
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v19" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V31EvidenceError("frozen V19 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V19_BUNDLE}:
        raise V31EvidenceError("frozen V19 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V19 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V19_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1893, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V19 JUnit evidence is invalid")
    static = _static_path(PROJECT / V19_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V19 static evidence is invalid")
    live_entries = _historical_manifest(V19_LIVE)
    if live_entries != (
        (V18_HISTORY["core/capability_nexus_v18.py"], "core/capability_nexus_v18.py"),
        ("0e855e63374d5534b2296b22d47f4dbd27b34bf627e930afa20f92c8bc828a88", V18_LIVE),
    ) or bundle.get("live_scan") != {"count": 98, "manifest_sha256": _sha(PROJECT / V19_LIVE)}:
        raise V31EvidenceError("frozen V19 live evidence is invalid")
    checkpoint = _read_text(V19_CHECKPOINT)
    verifier = _read_text(V19_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V19_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V19 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v20_proof() -> dict[str, object]:
    root = _historical_manifest(V20_ROOT_MANIFEST)
    if root != ((V20_HISTORY[V20_ARTIFACT_MANIFEST], V20_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V20 root manifest edge is invalid")
    artifacts = _historical_manifest(V20_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v20.py", "tests/test_capability_nexus_v20.py", V20_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v20_worker.py",
        "scripts/phase5_capability_nexus_v20_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v20_whitespace.py", V20_CHECKPOINT,
        V20_BUNDLE, V20_JUNIT, V20_STATIC, V20_LIVE, V19_ROOT_MANIFEST,
    }
    if len(artifacts) != 271 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V20 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V20_BUNDLE)
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v20" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V31EvidenceError("frozen V20 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V20_BUNDLE}:
        raise V31EvidenceError("frozen V20 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V20 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V20_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1903, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V20 JUnit evidence is invalid")
    static = _static_path(PROJECT / V20_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V20 static evidence is invalid")
    live_entries = _historical_manifest(V20_LIVE)
    if live_entries != (
        (V19_HISTORY["core/capability_nexus_v19.py"], "core/capability_nexus_v19.py"),
        ("e4dc09189b1e02b2da188a369a8f83ee0fae79d93e6f93fb2de74565ed6fa1bf", V19_LIVE),
    ) or bundle.get("live_scan") != {"count": 99, "manifest_sha256": _sha(PROJECT / V20_LIVE)}:
        raise V31EvidenceError("frozen V20 live evidence is invalid")
    checkpoint = _read_text(V20_CHECKPOINT)
    verifier = _read_text(V20_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V20_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V20 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v21_proof() -> dict[str, object]:
    root = _historical_manifest(V21_ROOT_MANIFEST)
    if root != ((V21_HISTORY[V21_ARTIFACT_MANIFEST], V21_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V21 root manifest edge is invalid")
    artifacts = _historical_manifest(V21_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v21.py", "tests/test_capability_nexus_v21.py", V21_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v21_worker.py",
        "scripts/phase5_capability_nexus_v21_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v21_whitespace.py", V21_CHECKPOINT,
        V21_BUNDLE, V21_JUNIT, V21_STATIC, V21_LIVE, V20_ROOT_MANIFEST,
    }
    if len(artifacts) != 289 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V21 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V21_BUNDLE)
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v21" or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted":
        raise V31EvidenceError("frozen V21 bundle contract/status is invalid")
    files = bundle.get("files")
    if not isinstance(files, dict) or set(files) != set(paths) - {V21_BUNDLE}:
        raise V31EvidenceError("frozen V21 bundle file closure is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V21 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V21_JUNIT)
    if junit != {"errors": 0, "failed": 0, "passed": 1916, "skipped": 0} or bundle.get("counts") != junit:
        raise V31EvidenceError("frozen V21 JUnit evidence is invalid")
    static = _static_path(PROJECT / V21_STATIC)
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V21 static evidence is invalid")
    live_entries = _historical_manifest(V21_LIVE)
    if live_entries != (
        (V20_HISTORY["core/capability_nexus_v20.py"], "core/capability_nexus_v20.py"),
        ("32e9e432ff866f7b7874819c6ca7f82bb08cf569635430d396eded97914a5dfb", V20_LIVE),
    ) or bundle.get("live_scan") != {"count": 100, "manifest_sha256": _sha(PROJECT / V21_LIVE)}:
        raise V31EvidenceError("frozen V21 live evidence is invalid")
    checkpoint = _read_text(V21_CHECKPOINT)
    verifier = _read_text(V21_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V21_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V21 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": len(artifacts), "bundle_status": bundle["status"],
        "junit_passed": junit["passed"], "live_scan_count": bundle["live_scan"]["count"],
        "marker_contract_bound": True, "static_gates": len(static),
    }


def _validate_frozen_v22_proof() -> dict[str, object]:
    root = _historical_manifest(V22_ROOT_MANIFEST)
    if root != ((V22_HISTORY[V22_ARTIFACT_MANIFEST], V22_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V22 root manifest edge is invalid")
    artifacts = _historical_manifest(V22_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {"core/capability_nexus_v22.py", "tests/test_capability_nexus_v22.py", V22_VERIFIER, V22_BUNDLE, V22_JUNIT, V22_STATIC, V22_LIVE, V21_ROOT_MANIFEST}
    if len(artifacts) != 307 or paths != tuple(sorted(paths)) or len(paths) != len(set(paths)) or not required.issubset(paths):
        raise V31EvidenceError("frozen V22 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V22_BUNDLE)
    files = bundle.get("files")
    if bundle.get("contract") != "Phase53CapabilityNexusEvidence.v22" or not isinstance(files, dict) or set(files) != set(paths) - {V22_BUNDLE}:
        raise V31EvidenceError("frozen V22 bundle is invalid")
    junit = _junit_path(PROJECT / V22_JUNIT)
    static = _static_path(PROJECT / V22_STATIC)
    if junit != {"errors": 0, "failed": 0, "passed": 1927, "skipped": 0} or bundle.get("counts") != junit or bundle.get("static_gates") != static:
        raise V31EvidenceError("frozen V22 quantitative proof is invalid")
    return {"artifact_entries": 307, "bundle_status": bundle["status"], "junit_passed": 1927, "live_scan_count": 101, "marker_contract_bound": True, "static_gates": 8}


def _validate_frozen_v23_proof() -> dict[str, object]:
    root = _historical_manifest(V23_ROOT_MANIFEST)
    expected_root = ((V23_HISTORY[V23_ARTIFACT_MANIFEST], V23_ARTIFACT_MANIFEST),)
    if root != expected_root:
        raise V31EvidenceError("frozen V23 root manifest edge is invalid")
    artifacts = _historical_manifest(V23_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v23.py",
        "tests/test_capability_nexus_v23.py",
        V23_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v23_worker.py",
        "scripts/phase5_capability_nexus_v23_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v23_whitespace.py",
        V23_BUNDLE,
        V23_JUNIT,
        V23_STATIC,
        V23_LIVE,
        V22_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 325
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V23_ARTIFACT_MANIFEST in paths
        or V23_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V23 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V23_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v23"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {
            "accepted": False,
            "required_before_acceptance": True,
            "status": "pending-external-review",
        }
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V23_BUNDLE}
    ):
        raise V31EvidenceError("frozen V23 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V23 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V23_JUNIT)
    static = _static_path(PROJECT / V23_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1936, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V23 quantitative proof is invalid")
    live_entries = _historical_manifest(V23_LIVE)
    if live_entries != (
        (V22_HISTORY["core/capability_nexus_v22.py"], "core/capability_nexus_v22.py"),
        ("ccb9c69bfe76c6d9b9965bad39127455d89415613c03478e333025a1dd09632a", V22_LIVE),
    ) or bundle.get("live_scan") != {
        "count": 102,
        "manifest_sha256": _sha(PROJECT / V23_LIVE),
    }:
        raise V31EvidenceError("frozen V23 live proof is invalid")
    checkpoint = _read_text(V23_CHECKPOINT)
    verifier = _read_text(V23_VERIFIER)
    if (
        "Status: **candidate" not in checkpoint
        or "P53_CAPABILITY_NEXUS_V23_EVIDENCE_OK" not in verifier
    ):
        raise V31EvidenceError("frozen V23 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 325,
        "bundle_status": bundle["status"],
        "junit_passed": 1936,
        "live_scan_count": 102,
        "marker_contract_bound": True,
        "static_gates": 8,
    }


def _validate_frozen_v24_proof() -> dict[str, object]:
    root = _historical_manifest(V24_ROOT_MANIFEST)
    if root != ((V24_HISTORY[V24_ARTIFACT_MANIFEST], V24_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V24 root manifest edge is invalid")
    artifacts = _historical_manifest(V24_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v24.py",
        "tests/test_capability_nexus_v24.py",
        V24_VERIFIER,
        "scripts/verify_phase5_capability_nexus_v24_worker.py",
        "scripts/phase5_capability_nexus_v24_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v24_whitespace.py",
        V24_BUNDLE,
        V24_JUNIT,
        V24_STATIC,
        V24_LIVE,
        V23_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 343
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V24_ARTIFACT_MANIFEST in paths
        or V24_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V24 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V24_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v24"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V24_BUNDLE}
    ):
        raise V31EvidenceError("frozen V24 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V24 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V24_JUNIT)
    static = _static_path(PROJECT / V24_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1944, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V24 quantitative proof is invalid")
    live_entries = _historical_manifest(V24_LIVE)
    if live_entries != (
        (V23_HISTORY["core/capability_nexus_v23.py"], "core/capability_nexus_v23.py"),
        ("385c83f2f2a5afa65f2bddfe44f070f466b9b19694e078d8a7f89db787b9abc2", V23_LIVE),
    ) or bundle.get("live_scan") != {"count": 103, "manifest_sha256": _sha(PROJECT / V24_LIVE)}:
        raise V31EvidenceError("frozen V24 live proof is invalid")
    checkpoint = _read_text(V24_CHECKPOINT)
    verifier = _read_text(V24_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V24_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V24 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 343,
        "bundle_status": bundle["status"],
        "junit_passed": 1944,
        "live_scan_count": 103,
        "marker_contract_bound": True,
        "static_gates": 8,
    }


def _validate_frozen_v25_proof() -> dict[str, object]:
    root = _historical_manifest(V25_ROOT_MANIFEST)
    if root != ((V25_HISTORY[V25_ARTIFACT_MANIFEST], V25_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V25 root manifest edge is invalid")
    artifacts = _historical_manifest(V25_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v25.py", "tests/test_capability_nexus_v25.py",
        V25_VERIFIER, "scripts/verify_phase5_capability_nexus_v25_worker.py",
        "scripts/phase5_capability_nexus_v25_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v25_whitespace.py",
        V25_BUNDLE, V25_JUNIT, V25_STATIC, V25_LIVE, V24_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 361
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V25_ARTIFACT_MANIFEST in paths
        or V25_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V25 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V25_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v25"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V25_BUNDLE}
    ):
        raise V31EvidenceError("frozen V25 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V25 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V25_JUNIT)
    static = _static_path(PROJECT / V25_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1952, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V25 quantitative proof is invalid")
    live_entries = _historical_manifest(V25_LIVE)
    if live_entries != (
        (V24_HISTORY["core/capability_nexus_v24.py"], "core/capability_nexus_v24.py"),
        ("d25f1f24064357af47ed1359f38bf643c5d8f247b598437065e8179c96893018", V24_LIVE),
    ) or bundle.get("live_scan") != {"count": 104, "manifest_sha256": _sha(PROJECT / V25_LIVE)}:
        raise V31EvidenceError("frozen V25 live proof is invalid")
    checkpoint = _read_text(V25_CHECKPOINT)
    verifier = _read_text(V25_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V25_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V25 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 361, "bundle_status": bundle["status"],
        "junit_passed": 1952, "live_scan_count": 104,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _validate_frozen_v26_proof() -> dict[str, object]:
    root = _historical_manifest(V26_ROOT_MANIFEST)
    if root != ((V26_HISTORY[V26_ARTIFACT_MANIFEST], V26_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V26 root manifest edge is invalid")
    artifacts = _historical_manifest(V26_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v26.py", "tests/test_capability_nexus_v26.py",
        V26_VERIFIER, "scripts/verify_phase5_capability_nexus_v26_worker.py",
        "scripts/phase5_capability_nexus_v26_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v26_whitespace.py",
        V26_BUNDLE, V26_JUNIT, V26_STATIC, V26_LIVE, V25_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 379
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V26_ARTIFACT_MANIFEST in paths
        or V26_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V26 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V26_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v26"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V26_BUNDLE}
    ):
        raise V31EvidenceError("frozen V26 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V26 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V26_JUNIT)
    static = _static_path(PROJECT / V26_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1963, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V26 quantitative proof is invalid")
    live_entries = _historical_manifest(V26_LIVE)
    if live_entries != (
        (V25_HISTORY["core/capability_nexus_v25.py"], "core/capability_nexus_v25.py"),
        ("a13ef56d1eb5d5b1052887df875fdb809cb4620d1e302a47b352d0a2bab0495b", V25_LIVE),
    ) or bundle.get("live_scan") != {"count": 105, "manifest_sha256": _sha(PROJECT / V26_LIVE)}:
        raise V31EvidenceError("frozen V26 live proof is invalid")
    checkpoint = _read_text(V26_CHECKPOINT)
    verifier = _read_text(V26_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V26_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V26 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 379, "bundle_status": bundle["status"],
        "junit_passed": 1963, "live_scan_count": 105,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _validate_frozen_v27_proof() -> dict[str, object]:
    root = _historical_manifest(V27_ROOT_MANIFEST)
    if root != ((V27_HISTORY[V27_ARTIFACT_MANIFEST], V27_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V27 root manifest edge is invalid")
    artifacts = _historical_manifest(V27_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v27.py", "tests/test_capability_nexus_v27.py",
        V27_VERIFIER, "scripts/verify_phase5_capability_nexus_v27_worker.py",
        "scripts/phase5_capability_nexus_v27_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v27_whitespace.py",
        V27_BUNDLE, V27_JUNIT, V27_STATIC, V27_LIVE, V26_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 397
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V27_ARTIFACT_MANIFEST in paths
        or V27_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V27 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V27_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v27"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V27_BUNDLE}
    ):
        raise V31EvidenceError("frozen V27 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V27 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V27_JUNIT)
    static = _static_path(PROJECT / V27_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1975, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V27 quantitative proof is invalid")
    live_entries = _historical_manifest(V27_LIVE)
    if live_entries != (
        (V26_HISTORY["core/capability_nexus_v26.py"], "core/capability_nexus_v26.py"),
        ("82c63c1cf8344b70ec40c116f36dcae5d26d9b0c7f12f8db77d5e3fcc80be4a9", V26_LIVE),
    ) or bundle.get("live_scan") != {"count": 106, "manifest_sha256": _sha(PROJECT / V27_LIVE)}:
        raise V31EvidenceError("frozen V27 live proof is invalid")
    checkpoint = _read_text(V27_CHECKPOINT)
    verifier = _read_text(V27_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V27_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V27 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 397, "bundle_status": bundle["status"],
        "junit_passed": 1975, "live_scan_count": 106,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _validate_frozen_v28_proof() -> dict[str, object]:
    root = _historical_manifest(V28_ROOT_MANIFEST)
    if root != ((V28_HISTORY[V28_ARTIFACT_MANIFEST], V28_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V28 root manifest edge is invalid")
    artifacts = _historical_manifest(V28_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v28.py", "tests/test_capability_nexus_v28.py",
        V28_VERIFIER, "scripts/verify_phase5_capability_nexus_v28_worker.py",
        "scripts/phase5_capability_nexus_v28_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v28_whitespace.py",
        V28_BUNDLE, V28_JUNIT, V28_STATIC, V28_LIVE, V27_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 415
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V28_ARTIFACT_MANIFEST in paths
        or V28_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V28 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V28_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v28"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V28_BUNDLE}
    ):
        raise V31EvidenceError("frozen V28 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V28 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V28_JUNIT)
    static = _static_path(PROJECT / V28_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1975, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V28 quantitative proof is invalid")
    live_entries = _historical_manifest(V28_LIVE)
    if live_entries != (
        (V27_HISTORY["core/capability_nexus_v27.py"], "core/capability_nexus_v27.py"),
        ("9a1c87135501ee1dbe4899ed4d703b0aa602959368047ea6a724a53f3db858a0", V27_LIVE),
    ) or bundle.get("live_scan") != {"count": 107, "manifest_sha256": _sha(PROJECT / V28_LIVE)}:
        raise V31EvidenceError("frozen V28 live proof is invalid")
    checkpoint = _read_text(V28_CHECKPOINT)
    verifier = _read_text(V28_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V28_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V28 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 415, "bundle_status": bundle["status"],
        "junit_passed": 1975, "live_scan_count": 107,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _validate_frozen_v29_proof() -> dict[str, object]:
    root = _historical_manifest(V29_ROOT_MANIFEST)
    if root != ((V29_HISTORY[V29_ARTIFACT_MANIFEST], V29_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V29 root manifest edge is invalid")
    artifacts = _historical_manifest(V29_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v29.py", "tests/test_capability_nexus_v29.py",
        V29_VERIFIER, "scripts/verify_phase5_capability_nexus_v29_worker.py",
        "scripts/phase5_capability_nexus_v29_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v29_whitespace.py",
        V29_BUNDLE, V29_JUNIT, V29_STATIC, V29_LIVE, V28_ROOT_MANIFEST,
    }
    if (
        len(artifacts) != 433
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or V29_ARTIFACT_MANIFEST in paths
        or V29_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V29 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V29_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v29"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V29_BUNDLE}
    ):
        raise V31EvidenceError("frozen V29 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V29 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V29_JUNIT)
    static = _static_path(PROJECT / V29_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1978, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V29 quantitative proof is invalid")
    live_entries = _historical_manifest(V29_LIVE)
    if live_entries != (
        (V28_HISTORY["core/capability_nexus_v28.py"], "core/capability_nexus_v28.py"),
        ("bf0487e7b07cc3af66daebda3d3b15bc1fa536f16aebd29b2af96fa78321051a", V28_LIVE),
    ) or bundle.get("live_scan") != {"count": 108, "manifest_sha256": _sha(PROJECT / V29_LIVE)}:
        raise V31EvidenceError("frozen V29 live proof is invalid")
    checkpoint = _read_text(V29_CHECKPOINT)
    verifier = _read_text(V29_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V29_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V29 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 433, "bundle_status": bundle["status"],
        "junit_passed": 1978, "live_scan_count": 108,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _validate_frozen_v30_proof() -> dict[str, object]:
    root = _historical_manifest(V30_ROOT_MANIFEST)
    if root != ((V30_HISTORY[V30_ARTIFACT_MANIFEST], V30_ARTIFACT_MANIFEST),):
        raise V31EvidenceError("frozen V30 root manifest edge is invalid")
    artifacts = _historical_manifest(V30_ARTIFACT_MANIFEST)
    paths = tuple(path for _, path in artifacts)
    required = {
        "core/capability_nexus_v30.py", "tests/test_capability_nexus_v30.py",
        V30_VERIFIER, "scripts/verify_phase5_capability_nexus_v30_worker.py",
        "scripts/phase5_capability_nexus_v30_subtest_reporter.py",
        "scripts/check_phase5_capability_nexus_v30_whitespace.py",
        V30_BUNDLE, V30_JUNIT, V30_STATIC, V30_LIVE, V29_ROOT_MANIFEST,
        f"{V30_EVIDENCE}/phase5-capability-nexus-v30.mutable-projections.json",
    }
    if (
        len(artifacts) != 454
        or paths != tuple(sorted(paths))
        or len(paths) != len(set(paths))
        or not required.issubset(paths)
        or set(MUTABLE_PROJECTIONS) & set(paths)
        or V30_ARTIFACT_MANIFEST in paths
        or V30_ROOT_MANIFEST in paths
    ):
        raise V31EvidenceError("frozen V30 artifact manifest closure is invalid")
    for digest, relative in artifacts:
        _verify_historical_path(relative, digest)
    bundle = _canonical_json(V30_BUNDLE)
    files = bundle.get("files")
    if (
        bundle.get("contract") != "Phase53CapabilityNexusEvidence.v30"
        or bundle.get("status") != "candidate-default-off-shadow-only-not-accepted"
        or bundle.get("external_e6")
        != {"accepted": False, "required_before_acceptance": True, "status": "pending-external-review"}
        or bundle.get("feature_gate")
        != {"dispatch_enabled": False, "nexus_enabled": False, "shadow_mode": True}
        or not isinstance(files, dict)
        or set(files) != set(paths) - {V30_BUNDLE}
    ):
        raise V31EvidenceError("frozen V30 bundle contract is invalid")
    for relative, digest in files.items():
        if digest != _historical_sha(relative):
            raise V31EvidenceError(f"frozen V30 bundle file hash mismatch: {relative}")
    junit = _junit_path(PROJECT / V30_JUNIT)
    static = _static_path(PROJECT / V30_STATIC)
    if (
        junit != {"errors": 0, "failed": 0, "passed": 1984, "skipped": 0}
        or bundle.get("counts") != junit
        or bundle.get("static_gates") != static
    ):
        raise V31EvidenceError("frozen V30 quantitative proof is invalid")
    live_entries = _historical_manifest(V30_LIVE)
    if live_entries != (
        (V29_HISTORY["core/capability_nexus_v29.py"], "core/capability_nexus_v29.py"),
        ("4f50024035d8ccc04db7c042abed8e830296759b19f9b77090ebf175fdc6add7", V29_LIVE),
    ) or bundle.get("live_scan") != {"count": 109, "manifest_sha256": _sha(PROJECT / V30_LIVE)}:
        raise V31EvidenceError("frozen V30 live proof is invalid")
    checkpoint = _read_text(V30_CHECKPOINT)
    verifier = _read_text(V30_VERIFIER)
    if "Status: **candidate" not in checkpoint or "P53_CAPABILITY_NEXUS_V30_EVIDENCE_OK" not in verifier:
        raise V31EvidenceError("frozen V30 checkpoint/marker contract is invalid")
    return {
        "artifact_entries": 454, "bundle_status": bundle["status"],
        "junit_passed": 1984, "live_scan_count": 109,
        "marker_contract_bound": True, "static_gates": 8,
    }


def _history_and_tamper(bundle: dict[str, object]) -> tuple[dict[str, object], dict[str, object]]:
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
        "phase53_v14": {"decision": "rejected", "hashes": V14_HISTORY},
        "phase53_v15": {"decision": "rejected", "hashes": V15_HISTORY},
        "phase53_v16": {"decision": "rejected", "hashes": V16_HISTORY},
        "phase53_v17": {"decision": "rejected", "hashes": V17_HISTORY},
        "phase53_v18": {"decision": "rejected", "hashes": V18_HISTORY},
        "phase53_v19": {"decision": "rejected", "hashes": V19_HISTORY},
        "phase53_v20": {"decision": "rejected", "hashes": V20_HISTORY},
        "phase53_v21": {"decision": "rejected", "hashes": V21_HISTORY},
        "phase53_v22": {"decision": "rejected", "hashes": V22_HISTORY},
        "phase53_v23": {"decision": "rejected", "hashes": V23_HISTORY},
        "phase53_v24": {"decision": "rejected", "hashes": V24_HISTORY},
        "phase53_v25": {"decision": "rejected", "hashes": V25_HISTORY},
        "phase53_v26": {"decision": "rejected", "hashes": V26_HISTORY},
        "phase53_v27": {"decision": "rejected", "hashes": V27_HISTORY},
        "phase53_v28": {"decision": "rejected", "hashes": V28_HISTORY},
        "phase53_v29": {"decision": "rejected", "hashes": V29_HISTORY},
        "phase53_v30": {"decision": "rejected", "hashes": V30_HISTORY},
    }
    if bundle.get("history") != expected:
        raise V31EvidenceError("V1/V2/V3 history is not exact or not rejected")
    for version, history in (
        ("V1", V1_HISTORY), ("V2", V2_HISTORY), ("V3", V3_HISTORY),
        ("V4", V4_HISTORY), ("V5", V5_HISTORY), ("V6", V6_HISTORY),
        ("V7", V7_HISTORY), ("V8", V8_HISTORY), ("V9", V9_HISTORY), ("V10", V10_HISTORY),
        ("V11", V11_HISTORY),
        ("V12", V12_HISTORY),
        ("V13", V13_HISTORY),
        ("V14", V14_HISTORY),
        ("V15", V15_HISTORY),
        ("V16", V16_HISTORY),
        ("V17", V17_HISTORY),
        ("V18", V18_HISTORY),
        ("V19", V19_HISTORY),
        ("V20", V20_HISTORY),
        ("V21", V21_HISTORY),
        ("V22", V22_HISTORY),
        ("V23", V23_HISTORY),
        ("V24", V24_HISTORY),
        ("V25", V25_HISTORY),
        ("V26", V26_HISTORY),
        ("V27", V27_HISTORY),
        ("V28", V28_HISTORY),
        ("V29", V29_HISTORY),
        ("V30", V30_HISTORY),
    ):
        for relative, digest in history.items():
            if _historical_sha(relative) != digest:
                raise V31EvidenceError(f"{version} historical byte drift: {relative}")
    v14_proof = _validate_frozen_v14_proof()
    v15_proof = _validate_frozen_v15_proof()
    v16_proof = _validate_frozen_v16_proof()
    v17_proof = _validate_frozen_v17_proof()
    v18_proof = _validate_frozen_v18_proof()
    v19_proof = _validate_frozen_v19_proof()
    v20_proof = _validate_frozen_v20_proof()
    v21_proof = _validate_frozen_v21_proof()
    v22_proof = _validate_frozen_v22_proof()
    v23_proof = _validate_frozen_v23_proof()
    v24_proof = _validate_frozen_v24_proof()
    v25_proof = _validate_frozen_v25_proof()
    v26_proof = _validate_frozen_v26_proof()
    v27_proof = _validate_frozen_v27_proof()
    v28_proof = _validate_frozen_v28_proof()
    v29_proof = _validate_frozen_v29_proof()
    v30_proof = _validate_frozen_v30_proof()
    historical_leaves: dict[str, str] = {}
    historical_manifests: set[str] = set()
    _verify_manifest_tree(HISTORICAL_ROOTS[-1], set(), historical_manifests, historical_leaves, 0)
    if not set(HISTORICAL_ROOTS).issubset(historical_manifests):
        raise V31EvidenceError("frozen V1-V30 root closure is incomplete")
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
        "core/capability_nexus_v14.py",
        "core/capability_nexus_v15.py",
        "core/capability_nexus_v16.py",
        "core/capability_nexus_v17.py",
        "core/capability_nexus_v18.py",
        "core/capability_nexus_v19.py",
        "core/capability_nexus_v20.py",
        "core/capability_nexus_v21.py",
        "core/capability_nexus_v22.py",
        "core/capability_nexus_v23.py",
        "core/capability_nexus_v24.py",
        "core/capability_nexus_v25.py",
        "core/capability_nexus_v26.py",
        "core/capability_nexus_v27.py",
        "core/capability_nexus_v28.py",
        "core/capability_nexus_v29.py",
        "core/capability_nexus_v30.py",
    ]
    with tempfile.TemporaryDirectory(prefix="onyx-p53-history-tamper-") as directory:
        base = Path(directory)
        for relative in targets:
            expected_digest = historical_leaves.get(relative)
            if expected_digest is None:
                raise V31EvidenceError(f"historical tamper leaf is unbound: {relative}")
            copied = base / relative
            copied.parent.mkdir(parents=True, exist_ok=True)
            copied.write_bytes(_read_bytes(relative))
            if _sha(copied) != expected_digest:
                raise V31EvidenceError(f"historical pristine copy mismatch: {relative}")
            copied.write_bytes(copied.read_bytes() + b"\n# disposable tamper\n")
            if _sha(copied) == expected_digest:
                raise V31EvidenceError(f"historical tamper fixture was not rejected: {relative}")
    history_metrics = {
        "frozen_candidates_cryptographically_validated": 30,
        "manifests_verified": len(historical_manifests),
        "roots": list(HISTORICAL_ROOTS),
        "unique_leaves_verified": len(historical_leaves),
        "v14_proof": v14_proof,
        "v15_proof": v15_proof,
        "v16_proof": v16_proof,
        "v17_proof": v17_proof,
        "v18_proof": v18_proof,
        "v19_proof": v19_proof,
        "v20_proof": v20_proof,
        "v21_proof": v21_proof,
        "v22_proof": v22_proof,
        "v23_proof": v23_proof,
        "v24_proof": v24_proof,
        "v25_proof": v25_proof,
        "v26_proof": v26_proof,
        "v27_proof": v27_proof,
        "v28_proof": v28_proof,
        "v29_proof": v29_proof,
        "v30_proof": v30_proof,
    }
    tamper_metrics = {
        "fixtures": targets,
        "rejected": len(targets),
        "total": len(targets),
        "unique": len(targets) == len(set(targets)),
    }
    return history_metrics, tamper_metrics


def _verify_manifest_tree(
    relative: str,
    active: set[str],
    verified: set[str],
    leaves: dict[str, str],
    depth: int,
) -> None:
    if depth > 32 or len(verified) >= 256 or len(leaves) > 4096:
        raise V31EvidenceError("historical manifest traversal budget exceeded")
    if relative in active:
        raise V31EvidenceError(f"historical manifest cycle detected: {relative}")
    if relative in verified:
        return
    active.add(relative)
    entries = _historical_manifest(relative)
    if len(entries) > 4096:
        raise V31EvidenceError("historical manifest leaf budget exceeded")
    for digest, child in entries:
        _verify_historical_path(child, digest)
        if child.endswith(".sha256"):
            if len(verified) >= 256:
                raise V31EvidenceError("historical manifest traversal budget exceeded")
            _verify_manifest_tree(child, active, verified, leaves, depth + 1)
        else:
            _record_historical_leaf(leaves, child, digest)
        if len(leaves) > 4096 or len(verified) > 256:
            raise V31EvidenceError("historical manifest traversal budget exceeded")
    active.remove(relative)
    verified.add(relative)
    if len(verified) > 256:
        raise V31EvidenceError("historical manifest traversal budget exceeded")


def _record_historical_leaf(leaves: dict[str, str], relative: str, digest: str) -> None:
    prior = leaves.get(relative)
    if prior is None:
        if len(leaves) >= 4096:
            raise V31EvidenceError("historical manifest leaf budget exceeded")
        leaves[relative] = digest
    elif prior != digest:
        raise V31EvidenceError(f"historical recursive digest conflict: {relative}")
    if len(leaves) > 4096:
        raise V31EvidenceError("historical manifest leaf budget exceeded")


def _verify_historical_path(relative: str, digest: str) -> None:
    if relative in MUTABLE_PROJECTIONS:
        mapping = _projection_mapping()
        if mapping[relative]["source_sha256"] != digest:
            raise V31EvidenceError(
                f"historical mutable projection digest conflict: {relative}"
            )
        return
    _assert_no_reparse(relative)
    path = PROJECT / relative
    try:
        path.resolve(strict=True).relative_to(PROJECT.resolve(strict=True))
    except (FileNotFoundError, ValueError, OSError) as exc:
        raise V31EvidenceError(f"historical path escapes or is missing: {relative}") from exc
    if not path.is_file() or _sha(path) != digest:
        raise V31EvidenceError(f"historical recursive leaf mismatch: {relative}")


def _live(bundle: dict[str, object]) -> dict[str, object]:
    entries = _manifest(LIVE)
    if tuple(path for _, path in entries) != ("core/capability_nexus_v30.py", V30_LIVE):
        raise V31EvidenceError("V31 live scan anchors are invalid")
    v30_entries = _manifest(V30_LIVE)
    if tuple(path for _, path in v30_entries) != ("core/capability_nexus_v29.py", V29_LIVE):
        raise V31EvidenceError("V30 live scan anchors are invalid")
    v29_entries = _manifest(V29_LIVE)
    if tuple(path for _, path in v29_entries) != ("core/capability_nexus_v28.py", V28_LIVE):
        raise V31EvidenceError("V29 live scan anchors are invalid")
    v28_entries = _manifest(V28_LIVE)
    if tuple(path for _, path in v28_entries) != ("core/capability_nexus_v27.py", V27_LIVE):
        raise V31EvidenceError("V28 live scan anchors are invalid")
    v27_entries = _manifest(V27_LIVE)
    if tuple(path for _, path in v27_entries) != ("core/capability_nexus_v26.py", V26_LIVE):
        raise V31EvidenceError("V27 live scan anchors are invalid")
    v26_entries = _manifest(V26_LIVE)
    if tuple(path for _, path in v26_entries) != ("core/capability_nexus_v25.py", V25_LIVE):
        raise V31EvidenceError("V26 live scan anchors are invalid")
    v25_entries = _manifest(V25_LIVE)
    if tuple(path for _, path in v25_entries) != ("core/capability_nexus_v24.py", V24_LIVE):
        raise V31EvidenceError("V25 live scan anchors are invalid")
    v24_entries = _manifest(V24_LIVE)
    if tuple(path for _, path in v24_entries) != ("core/capability_nexus_v23.py", V23_LIVE):
        raise V31EvidenceError("V24 live scan anchors are invalid")
    v23_entries = _manifest(V23_LIVE)
    if tuple(path for _, path in v23_entries) != ("core/capability_nexus_v22.py", V22_LIVE):
        raise V31EvidenceError("V23 live scan anchors are invalid")
    v22_entries = _manifest(V22_LIVE)
    if tuple(path for _, path in v22_entries) != ("core/capability_nexus_v21.py", V21_LIVE):
        raise V31EvidenceError("V22 live scan anchors are invalid")
    v21_entries = _manifest(V21_LIVE)
    if tuple(path for _, path in v21_entries) != ("core/capability_nexus_v20.py", V20_LIVE):
        raise V31EvidenceError("V21 live scan anchors are invalid")
    v20_entries = _manifest(V20_LIVE)
    if tuple(path for _, path in v20_entries) != ("core/capability_nexus_v19.py", V19_LIVE):
        raise V31EvidenceError("V20 live scan anchors are invalid")
    v19_entries = _manifest(V19_LIVE)
    if tuple(path for _, path in v19_entries) != ("core/capability_nexus_v18.py", V18_LIVE):
        raise V31EvidenceError("V19 live scan anchors are invalid")
    v18_entries = _manifest(V18_LIVE)
    if tuple(path for _, path in v18_entries) != ("core/capability_nexus_v17.py", V17_LIVE):
        raise V31EvidenceError("V18 live scan anchors are invalid")
    v17_entries = _manifest(V17_LIVE)
    if tuple(path for _, path in v17_entries) != ("core/capability_nexus_v16.py", V16_LIVE):
        raise V31EvidenceError("V17 live scan anchors are invalid")
    v16_entries = _manifest(V16_LIVE)
    if tuple(path for _, path in v16_entries) != ("core/capability_nexus_v15.py", V15_LIVE):
        raise V31EvidenceError("V16 live scan anchors are invalid")
    v15_entries = _manifest(V15_LIVE)
    if tuple(path for _, path in v15_entries) != ("core/capability_nexus_v14.py", V14_LIVE):
        raise V31EvidenceError("V15 live scan anchors are invalid")
    v14_entries = _manifest(V14_LIVE)
    if tuple(path for _, path in v14_entries) != ("core/capability_nexus_v13.py", V13_LIVE):
        raise V31EvidenceError("V14 live scan anchors are invalid")
    v13_entries = _manifest(V13_LIVE)
    if tuple(path for _, path in v13_entries) != ("core/capability_nexus_v12.py", V12_LIVE):
        raise V31EvidenceError("V13 live scan anchors are invalid")
    v12_entries = _manifest(V12_LIVE)
    if tuple(path for _, path in v12_entries) != ("core/capability_nexus_v11.py", V11_LIVE):
        raise V31EvidenceError("V12 live scan anchors are invalid")
    v11_entries = _manifest(V11_LIVE)
    if tuple(path for _, path in v11_entries) != ("core/capability_nexus_v10.py", V10_LIVE):
        raise V31EvidenceError("V11 live scan anchors are invalid")
    v10_entries = _manifest(V10_LIVE)
    if tuple(path for _, path in v10_entries) != ("core/capability_nexus_v9.py", V9_LIVE):
        raise V31EvidenceError("V10 live scan anchors are invalid")
    v9_entries = _manifest(V9_LIVE)
    if tuple(path for _, path in v9_entries) != ("core/capability_nexus_v8.py", V8_LIVE):
        raise V31EvidenceError("V9 live scan anchors are invalid")
    v8_entries = _manifest(V8_LIVE)
    if tuple(path for _, path in v8_entries) != ("core/capability_nexus_v7.py", V7_LIVE):
        raise V31EvidenceError("V8 live scan anchors are invalid")
    v7_entries = _manifest(V7_LIVE)
    if tuple(path for _, path in v7_entries) != ("core/capability_nexus_v6.py", V6_LIVE):
        raise V31EvidenceError("V7 live scan anchors are invalid")
    v6_entries = _manifest(V6_LIVE)
    if tuple(path for _, path in v6_entries) != ("core/capability_nexus_v5.py", V5_LIVE):
        raise V31EvidenceError("V6 live scan anchors are invalid")
    v5_entries = _manifest(V5_LIVE)
    if tuple(path for _, path in v5_entries) != ("core/capability_nexus_v4.py", V4_LIVE):
        raise V31EvidenceError("V5 live scan anchors are invalid")
    v4_entries = _manifest(V4_LIVE)
    if tuple(path for _, path in v4_entries) != ("core/capability_nexus_v3.py", V3_LIVE):
        raise V31EvidenceError("V4 live scan anchors are invalid")
    v3_entries = _manifest(V3_LIVE)
    if tuple(path for _, path in v3_entries) != ("core/capability_nexus_v2.py", V2_LIVE):
        raise V31EvidenceError("V3 live scan anchors are invalid")
    v2_entries = _manifest(V2_LIVE)
    if tuple(path for _, path in v2_entries) != ("core/capability_nexus_v1.py", V1_LIVE):
        raise V31EvidenceError("V2 live scan anchors are invalid")
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
        (V14_HISTORY["core/capability_nexus_v14.py"], "core/capability_nexus_v14.py"),
        (V15_HISTORY["core/capability_nexus_v15.py"], "core/capability_nexus_v15.py"),
        (V16_HISTORY["core/capability_nexus_v16.py"], "core/capability_nexus_v16.py"),
        (V17_HISTORY["core/capability_nexus_v17.py"], "core/capability_nexus_v17.py"),
        (V18_HISTORY["core/capability_nexus_v18.py"], "core/capability_nexus_v18.py"),
        (V19_HISTORY["core/capability_nexus_v19.py"], "core/capability_nexus_v19.py"),
        (V20_HISTORY["core/capability_nexus_v20.py"], "core/capability_nexus_v20.py"),
        (V21_HISTORY["core/capability_nexus_v21.py"], "core/capability_nexus_v21.py"),
        (V22_HISTORY["core/capability_nexus_v22.py"], "core/capability_nexus_v22.py"),
        (V23_HISTORY["core/capability_nexus_v23.py"], "core/capability_nexus_v23.py"),
        (V24_HISTORY["core/capability_nexus_v24.py"], "core/capability_nexus_v24.py"),
        (V25_HISTORY["core/capability_nexus_v25.py"], "core/capability_nexus_v25.py"),
        (V26_HISTORY["core/capability_nexus_v26.py"], "core/capability_nexus_v26.py"),
        (V27_HISTORY["core/capability_nexus_v27.py"], "core/capability_nexus_v27.py"),
        (V28_HISTORY["core/capability_nexus_v28.py"], "core/capability_nexus_v28.py"),
        (V29_HISTORY["core/capability_nexus_v29.py"], "core/capability_nexus_v29.py"),
        (V30_HISTORY["core/capability_nexus_v30.py"], "core/capability_nexus_v30.py"),
    )
    if bundle.get("live_scan") != {"count": len(expanded), "manifest_sha256": _sha(PROJECT / LIVE)}:
        raise V31EvidenceError("live scan summary drift")
    for digest, relative in expanded:
        path = PROJECT / relative
        if _sha(path) != digest or "capability_nexus_v31" in _read_text(relative):
            raise V31EvidenceError(f"live boundary drift/wiring: {relative}")
    return {
        "anchors": [path for _, path in entries],
        "count": len(expanded),
        "manifest_sha256": _sha(PROJECT / LIVE),
        "unique": len({path for _, path in expanded}) == len(expanded),
    }


def _assignment(path: Path, name: str) -> object:
    _guard_project_path(path)
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.Assign) and any(isinstance(item, ast.Name) and item.id == name for item in node.targets):
            return ast.literal_eval(node.value)
    raise V31EvidenceError(f"missing assignment: {name}")


def _semantics(bundle: dict[str, object]) -> None:
    tree = ast.parse(_read_text(CORE))
    forbidden_overclaims = (
        "im" + "mutable",
        "tamper" + "-proof",
        "cannot be " + "spoofed",
        "cannot be " + "mutated",
    )
    for relative in (CORE, TESTS, SELF, WORKER, REPORTER, WHITESPACE, CHECKPOINT, METRICS, BUNDLE):
        source = _read_text(relative).casefold()
        if any(term in source for term in forbidden_overclaims):
            raise V31EvidenceError(f"same-process runtime overclaim is forbidden: {relative}")
    forbidden = {"actions", "dashboard", "httpx", "main", "memory", "mcp", "requests", "socket", "subprocess", "webbrowser"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import) and {item.name.split(".", 1)[0] for item in node.names} & forbidden:
            raise V31EvidenceError("candidate imports a forbidden runtime/provider surface")
        if isinstance(node, ast.ImportFrom) and (node.module or "").split(".", 1)[0] in forbidden:
            raise V31EvidenceError("candidate imports a forbidden runtime/provider surface")
    sys.path.insert(0, str(PROJECT))
    try:
        from core.capability_nexus_v31 import (  # noqa: PLC0415
            CapabilityNexusV31,
            NexusFeatureGateV31,
            _METADATA_ENUMS,
            _safe_metadata,
            build_legacy_descriptors_v31,
        )
    finally:
        sys.path.pop(0)
    nexus = CapabilityNexusV31(NexusFeatureGateV31())
    if hasattr(nexus, "dispatch") or hasattr(nexus, "execute"):
        raise V31EvidenceError("registry exposes dispatch")
    declarations = _assignment(PROJECT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(PROJECT / "core/permission_broker.py", "MODEL_TOOL_POLICIES")
    built = build_legacy_descriptors_v31(
        declarations, policies, workspace_id="workspace-verifier", account_id="account-verifier", profile_id="profile-verifier"
    )
    if len(built.descriptors) != 26 or dict(built.policy_mapping()) != policies:
        raise V31EvidenceError("legacy parity failed")
    expected_metadata_enums = {
        "data_source": frozenset({"constructor_allowlist", "healthy", "local_catalog"}),
        "dispatch_path": frozenset({"legacy_unchanged"}),
        "fallback_class": frozenset({"explicit_browser_fallback"}),
        "policy_source": frozenset({"trusted_host_mapping"}),
    }
    if dict(_METADATA_ENUMS) != expected_metadata_enums:
        raise V31EvidenceError("closed metadata provenance contract drift")
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
            raise V31EvidenceError("closed metadata provenance contract accepted an unknown value")
    safe_metadata_node = next(
        node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "_safe_metadata"
    )
    called = {
        node.func.id
        for node in ast.walk(safe_metadata_node)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
    }
    if called & {"_secret_canary", "_raw_credential_canary", "_validate_content_decoding_closure"}:
        raise V31EvidenceError("typed metadata still uses free-text heuristic inference")
    claims = bundle.get("claims")
    expected = {
        "callbacks_outside_locks", "default_off_no_dispatch", "exact_concrete_read_only_gate",
        "profile_bound_projection_snapshot_cursor_receipt",
        "bounded_pending_uncertain_no_replay",
        "closed_metadata_provenance_enums_and_typed_hash",
        "content_scanners_confined_to_free_text_schema_and_legacy_declarations",
        "decoded_before_allowlist_content_scanning",
        "canonical_secret_name_field_rejection",
        "no_metadata_heuristic_inference",
        "frozen_history_cryptographically_validated",
        "pure_worker_has_no_subprocess_surface",
        "regression_base_and_subtest_semantics_reconciled",
        "no_bootstrap_artifact_or_surface",
        "windows_direct_createprocess_suspended_before_job_assignment",
        "resume_only_after_successful_job_assignment",
        "fixed_phase_ids_have_no_arbitrary_argv",
        "fresh_junit_realpath_sentinel_scoped",
        "posix_single_cleanup_state_machine_esrch_proof",
        "posix_immediate_ownership_direct_child_fallback",
        "flat_structured_cleanup_failure_aggregation",
        "recursive_cycle_safe_cleanup_failure_flattening",
        "shared_exception_dag_is_not_misclassified_as_cycle",
        "empty_structured_cleanup_payload_fails_closed",
        "checked_closehandle_retains_ownership_on_failure",
        "explicit_pointer_safe_kernel32_job_abi",
        "cross_platform_owned_process_trees_fail_closed",
        "strict_canonical_junit_lexical_and_content_schema",
        "structured_quantitative_evidence_semantically_validated",
        "checkpoint_has_no_unchecked_quantitative_claims",
        "artifact_live_history_counts_cross_validated",
        "atomic_entry_hook_admission_and_outer_finally_cleanup",
        "recursive_v1_to_v30_history_and_component_reparse_rejection",
        "hostile_cleanup_accessors_are_bounded_and_fail_closed",
        "hostile_exception_rendering_uses_pointer_free_fallback",
        "structured_record_fields_require_exact_str_before_operations",
        "safe_exception_type_metadata_bypasses_hostile_metaclasses",
        "exact_cleanup_payload_container_and_preiteration_item_budget",
        "cleanup_record_deduplication_precedes_capacity_accounting",
        "cleanup_overflow_is_separate_bounded_fail_closed_state",
        "cleanup_budget_overflow_short_circuits_all_traversal",
        "cleanup_wrapper_always_new_never_primary",
        "api_read_only_snapshot",
        "not_a_same_process_reflection_security_boundary",
        "runtime_wrapper_not_durable_audit_authority",
        "hash_bound_manifests_supply_persisted_audit_integrity",
        "one_shot_primary_descriptors_never_consulted",
        "complete_cleanup_snapshot_preserved_without_primary_attachment",
        "attribute_names_require_exact_builtin_str_before_operations",
        "ordinary_post_construction_attribute_assignment_and_deletion_are_closed",
        "hostile_str_subclass_attribute_names_are_never_invoked",
        "mutable_external_projections_are_not_authority",
        "content_addressed_projection_snapshots_are_historical_authority",
        "minimal_exact_projection_allowlist",
        "projection_live_path_drift_does_not_rewrite_frozen_history",
        "authoritative_paths_are_guarded_before_read_or_hash",
        "authoritative_workspace_containment_is_exact",
        "authoritative_component_case_aliases_are_rejected",
        "authoritative_ancestor_and_final_reparse_points_are_rejected",
        "artifact_manifest_members_are_reparse_checked_before_hash",
        "parent_fixed_phase_targets_guarded_before_process_creation",
    }
    if not isinstance(claims, dict) or set(claims) != expected or not all(claims.values()):
        raise V31EvidenceError("semantic claim set is invalid")


def _environment(bundle: dict[str, object]) -> None:
    recorded = bundle.get("environment")
    expected = {"executable": sys.executable, "platform": platform.platform(), "python": platform.python_version()}
    if not isinstance(recorded, dict) or any(recorded.get(key) != value for key, value in expected.items()):
        raise V31EvidenceError("environment drift")
    commit = bundle.get("base_commit")
    if not isinstance(commit, str) or re.fullmatch(r"[0-9a-f]{40}", commit) is None:
        raise V31EvidenceError("base commit evidence is invalid")


def verify(fresh_focused_junit: Path) -> dict[str, object]:
    paths = _dag()
    bundle = _bundle(paths)
    focused = _junit()
    if focused["errors"] or focused["failed"] or focused["skipped"] or bundle.get("counts") != focused:
        raise V31EvidenceError("JUnit counts drift")
    if not fresh_focused_junit.is_file() or _junit_path(fresh_focused_junit) != focused:
        raise V31EvidenceError("direct focused pytest evidence does not match frozen JUnit")
    static = _static()
    if bundle.get("static_gates") != static:
        raise V31EvidenceError("static evidence drift")
    history, tamper = _history_and_tamper(bundle)
    live = _live(bundle)
    metrics = _validate_metrics(paths, focused, static, history, tamper, live)
    if bundle.get("historical_recursive_evidence") != history:
        raise V31EvidenceError("bundle recursive history evidence drift")
    if bundle.get("regression_evidence") != metrics["regressions"]:
        raise V31EvidenceError("bundle regression evidence drift")
    if bundle.get("artifact_entries") != metrics["artifact"]:
        raise V31EvidenceError("bundle artifact entry evidence drift")
    if bundle.get("structured_evidence") != {
        "combined_junit_sha256": _sha(PROJECT / COMBINED_JUNIT),
        "metrics_sha256": _sha(PROJECT / METRICS),
        "regression_junit_sha256": _sha(PROJECT / REGRESSION_JUNIT),
        "regression_report_sha256": _sha(PROJECT / REGRESSION_REPORT),
    }:
        raise V31EvidenceError("bundle structured evidence binding drift")
    _checkpoint()
    _semantics(bundle)
    _environment(bundle)
    return {"artifacts": len(paths), "focused_passed": focused["passed"], "live_scan_files": live["count"],
            "root_sha256": _sha(PROJECT / ROOT_MANIFEST)}


def _validated_fresh_focused_junit(path: Path) -> Path:
    if path.name != "focused.junit.xml" or re.fullmatch(r"[0-9a-f]{64}", path.parent.name) is None:
        raise V31EvidenceError("fresh focused JUnit path is not nonce-scoped")
    try:
        base = _PRIVATE_BASE.resolve(strict=True)
        directory = path.parent.resolve(strict=True)
        resolved = path.resolve(strict=True)
    except OSError as exc:
        raise V31EvidenceError("fresh focused JUnit private realpath is invalid") from exc
    expected_base = Path(tempfile.gettempdir()).resolve(strict=True) / _PRIVATE_BASE.name
    if base != expected_base or directory.parent != base or resolved.parent != directory:
        raise V31EvidenceError("fresh focused JUnit escapes its fixed private base")
    for component in (_PRIVATE_BASE, path.parent, path.parent / _PRIVATE_SENTINEL, path):
        _assert_no_reparse(str(component.relative_to(PROJECT))) if component.is_relative_to(PROJECT) else None
        info = component.lstat()
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400):
            raise V31EvidenceError("fresh focused JUnit path contains a reparse component")
    sentinel = path.parent / _PRIVATE_SENTINEL
    if sentinel.read_text(encoding="ascii") != f"{_PRIVATE_CONTRACT}:{path.parent.name}\n":
        raise V31EvidenceError("fresh focused JUnit sentinel is invalid")
    return resolved


def main() -> int:
    if len(sys.argv) != 3 or sys.argv[1] != "--fresh-focused-junit":
        raise V31EvidenceError("pure worker requires exactly one fresh focused JUnit path")
    fresh = _validated_fresh_focused_junit(Path(sys.argv[2]))
    print("P53_CAPABILITY_NEXUS_V31_EVIDENCE_OK " + json.dumps(verify(fresh), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

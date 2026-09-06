from __future__ import annotations

import ast
from builtins import ExceptionGroup
import base64
from concurrent.futures import ThreadPoolExecutor
import copy
import ctypes
from dataclasses import FrozenInstanceError
import hashlib
import json
import os
from pathlib import Path
import sys
import subprocess
import threading
import tempfile
import time
from urllib.parse import quote
import xml.etree.ElementTree as ET

import pytest

from core.capability_nexus_v32 import (
    CATALOG_CONTRACT_VERSION_V32,
    LOCK_ORDER_V32,
    CancellationTokenV32,
    CapabilityDescriptorV32,
    CapabilityNexusV32,
    CapabilityProjectionV32,
    CapabilityStatusV32,
    CapabilityV32ContractError,
    CapabilityV32DeniedError,
    CatalogItemV32,
    CatalogReadRequestV32,
    LocalCatalogReadAdapterV32,
    NexusFeatureGateV32,
    OperationDescriptorV32,
    OperationKindV32,
    ReadFailureClassV32,
    ReadStateV32,
    TransportKindV32,
    build_legacy_descriptors_v32,
)
import core.capability_nexus_v32 as nexus_v32_module
import scripts.verify_phase5_capability_nexus_v32 as parent_v32
import scripts.verify_phase5_capability_nexus_v32_worker as verifier_v32


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = "workspace-alpha"
ACCOUNT = "account-alpha"
PROFILE = "profile-alpha"
KEY = b"k" * 32
V1_HASHES = {
    "core/capability_nexus_v1.py": "cd196f8805b7d89923ce98607fe1c49a762c7001456b470677585f60fa27474a",
    "tests/test_capability_nexus_v1.py": "f1f183938294d4963ddc52e1910287b5ed4ff8854ff149011bb0cfda17a1571c",
    "scripts/verify_phase5_capability_nexus_v1.py": "8f8509f920d99bf524b6b0a7073608cd0ccf3470287dbddc376d46ffddaa9c56",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V1-001.sha256": "e5f7d577cd0916c3df46d5b540668540fc88a1ec7c60130a198b78c75ec4249b",
}
V2_HASHES = {
    "core/capability_nexus_v2.py": "4493fddc3d1d17da99db08aa98395ae14f0b9050c1d7238b59261e503424235a",
    "tests/test_capability_nexus_v2.py": "61e0b9256e3397b16fed985a7c0f39e9ff8b66dd42e1420e3bb79f37fa5b7b52",
    "scripts/verify_phase5_capability_nexus_v2.py": "20c9a5638f8612cd03a0ceb098af263b9b0f67361d38f0e452877235cc27553b",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V2-001.sha256": "668c5ced47eb6c1b654fcc5fb11c372e36b279e5a4af9f83121ebd806a7d8e7b",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V2-001.sha256": "72ddcefff3bb5c99ab7850156f9ec108e64237ca32b17d582e3a8669d8087759",
}
V3_HASHES = {
    "core/capability_nexus_v3.py": "4fed38cc65ecdce2aa4a352465cd91e4c5e36ab2ff4413333531957afa386aa2",
    "tests/test_capability_nexus_v3.py": "64b2a6c2fd252b4f30bc9bb04afad021757ea1980b4d020d7b38e99748aee035",
    "scripts/verify_phase5_capability_nexus_v3.py": "bbfacc680cdc12bc6e201b4e57317a19a2926eb457c6138b7f29aa6c332ddae7",
    "scripts/check_phase5_capability_nexus_v3_whitespace.py": "ef9a907cc340847afb97b34fbfc2a300e5972a7730c83214dfa15e8a1b94e150",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V3-001.sha256": "270f2dd2ad0249e33bc0d04fff50ff150e74d75d687cd76fe2a16fae436b32a6",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V3-001.sha256": "071aa8e114db52e13f7381dade398b92bda6e1466514e49298c9b4a7efb91251",
}
V4_HASHES = {
    "core/capability_nexus_v4.py": "587040b0b4e31ddb24ad51791232af3b731e8a525a63c715f26d6dfcdb97cd7b",
    "tests/test_capability_nexus_v4.py": "51f49438f264134af7fda251158ab96c1aa35714ec4f02d5601058f9e697f0b2",
    "scripts/verify_phase5_capability_nexus_v4.py": "02aa36cbfe01428e123818685802d5e9febef995c4ea2831a0f3c83937b4e7ef",
    "scripts/check_phase5_capability_nexus_v4_whitespace.py": "891281226e2cd58f077a6ac0114eaeabf718fca7c04dc341690a362d218dd733",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V4-001.sha256": "476508f1b33497eae86b53699fcdb53ce8a5d0557c2b28a07ba9b4eff297805d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V4-001.sha256": "3eec7517108ba2d1ad202be9bc08835703ebea24f13091c11958ca7decbcd054",
}
V5_HASHES = {
    "core/capability_nexus_v5.py": "cd3330522c275a88641884d9eb20c0448a3dd1a0b9051f3ea0a8c8983ee752f4",
    "tests/test_capability_nexus_v5.py": "f75be0cb1c9124a3fa329945de5a2b949b5598bbf9b6c181746eb5461df63e65",
    "scripts/verify_phase5_capability_nexus_v5.py": "890177d93e360726607b4e4093742bfe22cba09dbd588db251312b1129e7fc09",
    "scripts/check_phase5_capability_nexus_v5_whitespace.py": "450e54b0d7966682c4b83efc39dc44642f764201c9629e25b9e4e2a8b08ce301",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V5-001.sha256": "edc93fe63291f83e09115f4e383e1998b80f456497193bfce3654525ebf3e58d",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V5-001.sha256": "1b2868ea7f526c83651d28e50e4bd533ffd8d2f0515ffdecdd5e353a93c8527a",
}
V6_HASHES = {
    "core/capability_nexus_v6.py": "cc87b4d201ded06ad8fae44aaf295d40b279e329b981ee4e79368555fdc4f09f",
    "tests/test_capability_nexus_v6.py": "8b56668d27140eca0cdf0b2b78b1525401e388bdc67155b4fb9737793d06b312",
    "scripts/verify_phase5_capability_nexus_v6.py": "21a3c31fc1f7f18fd4e336365c499f6a81b1f6fa9929b5300b3d81ce16498ad1",
    "scripts/check_phase5_capability_nexus_v6_whitespace.py": "ca463e53b812f1fb5fec92b71c66d8e9c5c9e35e9970032b8df42eaa09be1db5",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V6-001.sha256": "76917c2516ccb000d0b5bfc351d405e365759badbfffd4c5d2b9c1599070b2d3",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V6-001.sha256": "5e356381370ce275fe2a3800f87bd144ad21cc96339040e4d6e976afb0b4e26b",
}
V7_HASHES = {
    "core/capability_nexus_v7.py": "8f2b8a7f0cfbf05712d9f4a339f4f0617dd35c20dda5dac2ba1df7bc614b4559",
    "tests/test_capability_nexus_v7.py": "e6979f4d07c032229b87aa3d27138471afc2a80b0e504a93b68be87594a7a96c",
    "scripts/verify_phase5_capability_nexus_v7.py": "19fdda417b1927c2c3ea8a9861973c2d2ec1e5e364e7b50a00c8fdbbf043c4b7",
    "scripts/check_phase5_capability_nexus_v7_whitespace.py": "e43e07f203bd871f1e9e1435e30897def2eae46614b9cef65c18de824ae8ce0f",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V7-001.sha256": "1421797efec725795d861d1d374329158e745af475e56bfde7d298863c872eca",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V7-001.sha256": "1de50b43ee4143e6de396102e080983ea0c004453db5ca70e2debbb900b78d00",
}
V8_HASHES = {
    "core/capability_nexus_v8.py": "225071341b59e4acafb0f2fa35e19175c84620b268e5d26598ca224beef20c4c",
    "tests/test_capability_nexus_v8.py": "59ee46547dbfe5b6f8790ca68b602495ddac2b3d51bab6d67193b2b0a0e441b9",
    "scripts/verify_phase5_capability_nexus_v8.py": "c630b3620e84e19d515a6d04db7040e6a4d97a0560b2529dc93ad1132735130c",
    "scripts/check_phase5_capability_nexus_v8_whitespace.py": "46506a67cf12cd9f67d5eccba62a86bbd4412f11043c38c15789ca54cee165e4",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V8-001.sha256": "8f12047f2632f61d62417201fff9fcbf0e926ffbfde11a9a760ed4b907377aaa",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V8-001.sha256": "712ddc1e02f7b57945fcf7b83238dc7efd14da809d735ab5276440867f589970",
}
V9_HASHES = {
    "core/capability_nexus_v9.py": "36c281c8dcaf522b0d52ffbdcd28a55e6145f5cc08bf8370ae206da86464c7f8",
    "tests/test_capability_nexus_v9.py": "3111f403eff79d911547cd54675502b148958926a44732f58749c33102f3de0c",
    "scripts/verify_phase5_capability_nexus_v9.py": "28d279c6c86811df3b0d0ff5c8c5824eb1391335f78bbc95ffca43a43de474f6",
    "scripts/check_phase5_capability_nexus_v9_whitespace.py": "99af22dd17ce948f5937a13e9c070a70f569dc80552ec78b7efdf452e94c97af",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V9-001.sha256": "d55419e2841634f91a1c71b5f70ade61b17dac2d3799da8d757252decb94e4f9",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V9-001.sha256": "018e5bfde1f749bcba64ad0520dabc83460c62fced34f326dfe603f066547c8f",
}
V10_HASHES = {
    "core/capability_nexus_v10.py": "74401ce43f11d544b2b6059c101702386e0e0bfec9fd2fd517f030cf21e699c0",
    "tests/test_capability_nexus_v10.py": "be8197b10b095aaaafb5e58d9daab9f60dec15155fcb1359662dae4f819b458d",
    "scripts/verify_phase5_capability_nexus_v10.py": "3241ad5ae3a2919d1642c2dd0ecc8ee85fd0a7e26be813ac44b461408121a873",
    "scripts/check_phase5_capability_nexus_v10_whitespace.py": "0903471515fb3f14827b7c7bb3d67ec0e68bd8341fa51ec5d4d966014eadb578",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V10-001.sha256": "48b962b42c9705b4bc2ea376a50617f791b72d53fe5335ec9f58420280aae293",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V10-001.sha256": "2f8f37b4dd94cb217cfea35f6c236454342e9864cef1972cc94ad3d2992351a1",
}
V11_HASHES = {
    "core/capability_nexus_v11.py": "c3b43708c10f28e23f03ef15a5dd3cbd7c8315c45beb22314be75e0ce7e7f5c1",
    "tests/test_capability_nexus_v11.py": "817e8db14f480bbb35b543f9587552205e4ba2a6ba1bf2611b8566aef008f029",
    "scripts/verify_phase5_capability_nexus_v11.py": "01f9bb77c358e3bee1c8e357c214e572b55e134e40ace54367c939bf245d795c",
    "scripts/check_phase5_capability_nexus_v11_whitespace.py": "aa3c2b969cce11bf35406e07e7cfe488de7dcdaca7e6618b2c684d73396153b8",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V11-001.sha256": "472b6a1ae970cb4d2bd5ac7228f5d6716509aa9220f4f04218e30444ea9452f1",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V11-001.sha256": "46238e447361e320b1d46ef92b40d717ca91abcc238d7e35b0f83df957db2419",
}
V12_HASHES = {
    "core/capability_nexus_v12.py": "bc155ad1a8f35543ff296173b7bd6238ed7248e5d47bf2077d98f3b210e29b65",
    "tests/test_capability_nexus_v12.py": "35348d2044d8d6edba52ddc6f8113460c991629eac90cf9a06e582a441748642",
    "scripts/verify_phase5_capability_nexus_v12.py": "a89ba01f16ef26764be17ef499f7c5fcf161a81d30ecdbd542b7921a271a2ad1",
    "scripts/check_phase5_capability_nexus_v12_whitespace.py": "4a961bb6dd732608c8e7035d1945e20375ac2163182936ce4cfda9131c6cf223",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V12-001.sha256": "949f7f31a2b8a8b67bddb2c8654bd5846a203a00bc741ed129c45ead9e1ef67c",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V12-001.sha256": "3e3307ad18febf188dff5237127c83230a925f1ae6e93ee45bab7d1de9545431",
}
V13_HASHES = {
    "core/capability_nexus_v13.py": "44625eecb338ac891383413e85d6544b7893fa9f8bad3f463727d6f0f1498a27",
    "tests/test_capability_nexus_v13.py": "8585cec58401849383a7d2c6bcdbb492abf2136eb4c2492318b2655478a122be",
    "scripts/verify_phase5_capability_nexus_v13.py": "e09330ae88ffbe13abe0f3d514e48d6b103741045772e13463f4311b545bc43c",
    "scripts/check_phase5_capability_nexus_v13_whitespace.py": "d5d4c7c5680672819d3da6ac4dbf86adc590201231117b2f5ca689fb09492fc2",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V13-001.sha256": "e48bd590ce86e207259fbd97999a4c0fe5df9e3179f7fd04801a290b963d13ba",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V13-001.sha256": "16197a5110b33ddbd40142ac30542f230fe2285a2607d463cf9aeb70ea72d5a4",
}
V14_HASHES = {
    "core/capability_nexus_v14.py": "110170dc17e43cec844eaae55387989d6b057a8f07c01feb83b7e292bc0d1c07",
    "tests/test_capability_nexus_v14.py": "89ca8c50cef72cdc45cee5b2c2d9c28a98fda8f3ba9e9e2bbe6a2a32fd2ed8b3",
    "scripts/verify_phase5_capability_nexus_v14.py": "8eca4ea9bfaa550e31ec5b8f209e0d0c6dcb8724e6c22c799c2af3e56ecfc08c",
    "scripts/check_phase5_capability_nexus_v14_whitespace.py": "63066542f021baea421c2d10777e4ad58b6c6b21064c856e7e044b03a9f6fb0f",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V14-001.sha256": "5429f58302cab5e15a8e3d9076b316591a47fd3857a150ceb532d9e5fa5050e4",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V14-001.sha256": "3dc4e6bed2672a558fe3bef01c00ddcb46fe35baecc76080ffa45df399ac4790",
}
V15_HASHES = {
    "core/capability_nexus_v15.py": "0c61979351e9cee695474acc16265af10199b4b36392005dc04e6463bc4faf73",
    "tests/test_capability_nexus_v15.py": "400a5c734b1330a7f1fe79270d1fc0eb8fb40c3e5827946d67b290f83d50aa52",
    "scripts/verify_phase5_capability_nexus_v15.py": "788859851164233e62c3a7224dc8a197e86e092d2cdacc3dc8bf6b97fec860c8",
    "scripts/check_phase5_capability_nexus_v15_whitespace.py": "068b1e3c5e20457b7016e2c00de13c791e1aa47427b49a9b2b35e7ea0d3f6832",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V15-001.sha256": "08daf2b93e74f0b83d6487c30849313948fbf8b0d8ec6981a49fb076b2c69212",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V15-001.sha256": "60850f591b5e5a79f6015e07291b776dd682467cc6a4b3b6069e8590b247846d",
}
V16_HASHES = {
    "core/capability_nexus_v16.py": "f4fb99b94f1f5237afa81bd4c7e70f5987406e3b81da898cccaa534c00f90455",
    "tests/test_capability_nexus_v16.py": "9987536d7022d4c99d3080c11752ffcec151c609b80e6c4608b7d5967cc6c695",
    "scripts/verify_phase5_capability_nexus_v16.py": "d5fc6a6ed4502f579e26704d7f57c75e608a7ed554dc7e782279789c3b3fd584",
    "scripts/verify_phase5_capability_nexus_v16_worker.py": "4014a88c6d7daed840debb9c7d8815f83d71667f7e94f4940f79761654572730",
    "scripts/phase5_capability_nexus_v16_subtest_reporter.py": "64bfd18e2620dd12941e007e22c9f6aceda2811593fb31415350d5c882633d10",
    "scripts/check_phase5_capability_nexus_v16_whitespace.py": "3ba19bfd39f0b0e19219d7dedc528e263c782207a8e8a7e853ed06a89b4b600d",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V16-001.sha256": "8873308e576eae482bbb46ce764a4aa00af39709abd83fc4a842db8132dbb419",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V16-001.sha256": "74b500df804fa0508e52f5d2b88b725c7e3aa141be5c6a442926387be446e9b7",
}
V17_HASHES = {
    "core/capability_nexus_v17.py": "66419a598154c22d68f2d5a996bee6ab817d6602d57651c9cd6c56a41abbf422",
    "tests/test_capability_nexus_v17.py": "55899f8187631273901e750c1610966920f4dc604efb7396bd6585c5bc25a2dd",
    "scripts/verify_phase5_capability_nexus_v17.py": "3e8bb4cfb59882c3826d9f9df316b125702e77ba344ccb4be3dad3cc5a55003e",
    "scripts/verify_phase5_capability_nexus_v17_worker.py": "dab68d57104aff333341d4827f9621c5cf14d0dca36bd7bd16febcace82da9d9",
    "scripts/phase5_capability_nexus_v17_subtest_reporter.py": "a7860ef4c846ad3303b60572a580c698d26acfe148a6a0a985c9dc5ced15014a",
    "scripts/check_phase5_capability_nexus_v17_whitespace.py": "940d534dca45c754d85e5868fe7723d5309c184fa83185e22f37db0258635a89",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V17-001.sha256": "adc0aa3a417b59adc180901ea5b0d08c1449bb426402ce155c6297ed957e40c1",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V17-001.sha256": "0cc3cb936b97d2c545d38c5a35f63fcb88572405d3fc8cb76ea0f2afe8fbaf2f",
}
V18_HASHES = {
    "core/capability_nexus_v18.py": "daf165f09440e297bae81f74f45dd46d0c09f02ddf42d0eecd27c768f8c80a01",
    "tests/test_capability_nexus_v18.py": "9a8b992474479b58bfaaf2568d78206ff39f2c08566d5648dc4d44d00313af58",
    "scripts/verify_phase5_capability_nexus_v18.py": "6ed5d1d99d3ff3ef6f11d91e74cafe35d3864b2c557f3e93737104f88b96d4b9",
    "scripts/verify_phase5_capability_nexus_v18_worker.py": "b90e7d0084f36cb5fbd22b6adde4e3dbac18d7eea5e260b00f1b631222047c04",
    "scripts/phase5_capability_nexus_v18_bootstrap.py": "a365c0b89dcc012050aed4db1414048d562178ab0ad9fe58e1d035680f4d5a44",
    "scripts/phase5_capability_nexus_v18_subtest_reporter.py": "fbca475f22815ab967ecbd1dddbc448d5cc2bd06771a534e330281a81254423b",
    "scripts/check_phase5_capability_nexus_v18_whitespace.py": "5918ba491b06bfa066de7e9bfa09afd647ec3ed0685d3863b4c822ce3d6734ab",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V18-001.sha256": "5d9f457e54c625ed846bc9a0c193adb5da7da84bfdd5dbac39733f8ba6fb010b",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V18-001.sha256": "05967af9abdb81dde8b78e4c1fad5d09a2855102ffd7653e7101e7ac4c82d1d7",
}
V19_HASHES = {
    "core/capability_nexus_v19.py": "07843a76223dbb21658135774f442d5f33dbc25e5369001ad2b73a817e143cbc",
    "tests/test_capability_nexus_v19.py": "5efee050ca7381aad2e89c57b9f91a5233eedc22eac8104b6dc565ed5a80f0c4",
    "scripts/verify_phase5_capability_nexus_v19.py": "5ddd5f588437486a985056359e30dc3d1d2e97902d6a43c5963a895155d9d6e4",
    "scripts/verify_phase5_capability_nexus_v19_worker.py": "04a22377fb82ac1094a6ca4ba6c147989cced2ae6a526b21c73725b591f87ec2",
    "scripts/phase5_capability_nexus_v19_bootstrap.py": "eef5fe39198b5d71a57ab33122cc54b761428890f141d505d36320332f30bd18",
    "scripts/phase5_capability_nexus_v19_subtest_reporter.py": "c1d118c438c051f9cfd242a43a60aa33998435eb26262b9bdfbda04fc175874a",
    "scripts/check_phase5_capability_nexus_v19_whitespace.py": "35c470f2a716279529cd5d3e7638fbf340eeb4a7626dde7bb2b2032ba410ed13",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V19-001.sha256": "5f7f49a67142decccdb66e70aca7f726e704dfbbbc1bf9321d798faf18432ef6",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V19-001.sha256": "4ed79c2c0d37072e865ebcb1df4eb2cc1b12777bba6148832fa36c4ba575a7e5",
}
V20_HASHES = {
    "core/capability_nexus_v20.py": "d0ecdcbe63718e854a1c708f94b5c35c7ad2b9c7733a9efb10e6e6c5815cfb7a",
    "tests/test_capability_nexus_v20.py": "5c4fd2410e3c815d1e75d885e01aee013cb6d0bddb0af9d700d09ddf9c89d297",
    "scripts/verify_phase5_capability_nexus_v20.py": "0703335ec6a0ca1d8ad49916bfa11cac29cece08b38b0f34ea39bca50148239a",
    "scripts/verify_phase5_capability_nexus_v20_worker.py": "894b325d576d05c65edce9e968292a3f98d3f381779e87a3ed93e72ced7c2251",
    "scripts/phase5_capability_nexus_v20_subtest_reporter.py": "27dc1ea64a9851da5e071fcee0c59d6abbde8d0a6beef02a6598a743d3489c7e",
    "scripts/check_phase5_capability_nexus_v20_whitespace.py": "0b9e0acd4c7e60e6244d41cf607d95f3ee7be8166e3a0d3d602ac24ef399fd73",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V20-001.sha256": "d9e92f17f0386bba9bce421f72e6ef8ac60bb5e8aab98dfac9f6671df2db58b2",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V20-001.sha256": "9b813aed42fe251f979f9f36c9da742d021ed13435d1f31d87672bf9cf15fd46",
}
V21_HASHES = {
    "core/capability_nexus_v21.py": "1f1bc766f7062b15c5a64666c6b03231560733a0dc6e388d7b415927043ed41a",
    "tests/test_capability_nexus_v21.py": "72596e20060699e4f3a414b9800c68eabc5e2998d3a7bc015579aba829bf455b",
    "scripts/verify_phase5_capability_nexus_v21.py": "1df832eab61f58a084259fd8608873faf261f35c676d9688dfa7f9c2a99f87f2",
    "scripts/verify_phase5_capability_nexus_v21_worker.py": "4acc13327d7759aeb05e48c6cfef3ca335526ea2633f5d8ede21cced77515796",
    "scripts/phase5_capability_nexus_v21_subtest_reporter.py": "ec6ecadaeb5fb8b78b84575a36688c7a7b63e6f25499fc7482d6e7be4fce9613",
    "scripts/check_phase5_capability_nexus_v21_whitespace.py": "f3cdc9a331ad7e59419940fc44c45ae18fc0b1c20ca13df4604fe351d145f6eb",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V21-001.sha256": "055672516e56743f64df810a4c9f3bad4186cad3c6b9bb285640e4a36e65ad16",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V21-001.sha256": "b7c81643756462ed115bf75516c8c5ad2c345fca6cbb4691b064931cf2e169d8",
}
V22_HASHES = {
    "core/capability_nexus_v22.py": "f5c2b025e8cb9fe3d78cf270ecab877fd81521c48b025e683276fd27a8eae526",
    "tests/test_capability_nexus_v22.py": "7e76146aec6b0ab49765535ef99cd779da0def7bdfb8f903814fd19bf8db16d5",
    "scripts/verify_phase5_capability_nexus_v22.py": "23eae195813d5912065224c4bd9f81170f36136b9e7c0e2096938009afc8fd45",
    "scripts/verify_phase5_capability_nexus_v22_worker.py": "8062f3cfea92a8bd3c1d097c35120a20c909fb25228cb7e644999d6ac99cceed",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V22-001.sha256": "bcb19bf1a5b51084ff026ef861809fd365cff9d0fb6a06134ba516c1d3b03626",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V22-001.sha256": "7ed9d3e33cf3424e448fc0ced2c1ab79fb7f49b95a8f7cc4fcf655f6fd2c8e9a",
}
V23_HASHES = {
    "core/capability_nexus_v23.py": "32dd829130eb32eacb32052196052f7d66aa2f92e0e8d3c2ab1586e0011454ac",
    "tests/test_capability_nexus_v23.py": "6d2bc6924f979b50c0b86f1090f489dd9c45d6dfa4623b34fe583d57fefa4f7d",
    "scripts/verify_phase5_capability_nexus_v23.py": "01803bafb5db005754f7f11b25d3bd17065a14a0aa6eb52ae0da720bc26526e3",
    "scripts/verify_phase5_capability_nexus_v23_worker.py": "798071357e5e0acfb2e147a9157d61b280f6311ea306ddf92a0ca4410f750e94",
    "scripts/phase5_capability_nexus_v23_subtest_reporter.py": "baade702f6415733a9312136eddefd769bf333236332e512afe3cd2e36452ddf",
    "scripts/check_phase5_capability_nexus_v23_whitespace.py": "86adbda10c87c5d3ffed9419b4aca1792128080c85aa70738e48cd572ca82e63",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V23-001.sha256": "a69d4a66d6c829d52412e38434751c87ed5f24f72385aa016504224bead30d34",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V23-001.sha256": "7cb5799d375cf18b03836e96f013b7fc39c7ec02638c856451b910890150958b",
}
V24_HASHES = {
    "core/capability_nexus_v24.py": "4150d020a57e20c96805106aa8edc3b941e6866a2491d4cd9721bedaa82330d7",
    "tests/test_capability_nexus_v24.py": "d3a144a6bcd0215597f3a4a8a26f03d54cb996e5c31061aa2ab8b4285db9724e",
    "scripts/verify_phase5_capability_nexus_v24.py": "f695841cff8a677e087b144e10e52f930376aa38e35390bfc67e033ed6f78981",
    "scripts/verify_phase5_capability_nexus_v24_worker.py": "a7486db5bd9b29fc225ff981e6c6a2348d884fe03404035441ca0bf133ce5355",
    "scripts/phase5_capability_nexus_v24_subtest_reporter.py": "699e97849d756f07a8746ce1aaf6c7a988d076d1124fb5045e14aa0c140e3da4",
    "scripts/check_phase5_capability_nexus_v24_whitespace.py": "b9bf22f63c1693a5c76aebc5625db4f6e8f227fbb1d1977c624cfb3e305c0070",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V24-001.sha256": "dab74bcb848b08b74fc005045d1709755bb45d224208eff3b06a348d01c85332",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V24-001.sha256": "a0cef935efa2b34041bf4206fbd30f43d45a1282ad9c42339598c112c061dad9",
}
V25_HASHES = {
    "core/capability_nexus_v25.py": "88fca28c19bcaeb71e6840191440824339d87c33309ca58dd644706d9b02ca11",
    "tests/test_capability_nexus_v25.py": "7fb273a548778a8bff27d6b7d81f86c13fc67f8ac856d47f9d899958d4f2f3ba",
    "scripts/verify_phase5_capability_nexus_v25.py": "36fdf20b4f6260df649bd8ade9a38a1068c90c7e9aa24d4c6ed4766b0aa6a6db",
    "scripts/verify_phase5_capability_nexus_v25_worker.py": "a4c4ec22fc1ca8b730d50a94290954c54bcb152c9903ce197df57cf41afae688",
    "scripts/phase5_capability_nexus_v25_subtest_reporter.py": "a75d56fadbc4bd8dace2fbd59b7a019e080a16373ba0ffa7557b05f4b3bd0abf",
    "scripts/check_phase5_capability_nexus_v25_whitespace.py": "c7e5375681af73b74f58338afdba75aa15b127763c005b3c45838d76cc539829",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V25-001.sha256": "6d23c5825c45b41a9577ccd43dac683deb9dbadd52c853298ddc61aaf0f81799",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V25-001.sha256": "765d3fdc2c5a6cb2699b24ac3c3123aa490c9614e44beb749e9c91839f88fb8b",
}
V26_HASHES = {
    "core/capability_nexus_v26.py": "ba6a49717f371ad81feffcd4e565072b6fa9727b36c9cfe6c7ca956830aec1ed",
    "tests/test_capability_nexus_v26.py": "abb62f01b165fffc2f983dcd97ec3ec450a2cf8a698e11b760e89d613d6180d0",
    "scripts/verify_phase5_capability_nexus_v26.py": "2a802c05b57e34b3053e9d7e8279cc284445193665fbcca02f8feedfbb5bc17a",
    "scripts/verify_phase5_capability_nexus_v26_worker.py": "ce76bad56870168c56eb50744682599af1abad5c63e1d7192fdaacb2558af2ae",
    "scripts/phase5_capability_nexus_v26_subtest_reporter.py": "45d976e8b4f6df61044185c23dfd2212e40888bf9160dbca827522fc1c946925",
    "scripts/check_phase5_capability_nexus_v26_whitespace.py": "cd63062747827485603dc6ce20eb92a46af51459c6c56d2a6bd7f932d66a319d",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V26-001.sha256": "be0b46af882855d7acee1e219b470a2e2ab9ffcc1e6b5781326c1c0839e4b508",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V26-001.sha256": "1bc06d4d578bd9cc9e9a84404e22bbec47ec246e4b2c40ee47593563297d1e43",
}
V27_HASHES = {
    "core/capability_nexus_v27.py": "ae84b12356c2c258b57fc44a9cfc6dc35c555b458509e24c846b69c97cd61abe",
    "tests/test_capability_nexus_v27.py": "0335a5ee2ce1cae523e5a829fde31c7fb24466d578bf0775b5492ff95ce084c7",
    "scripts/verify_phase5_capability_nexus_v27.py": "8ebba11664ff18118925494e463333b6040b4b5a3215a93e84a709f399af42b6",
    "scripts/verify_phase5_capability_nexus_v27_worker.py": "c8a829e67aa532a151f7aa0e132f4a3f2c9dd9e5dceb0ac2bdfad9a12cbfc794",
    "scripts/phase5_capability_nexus_v27_subtest_reporter.py": "b4c1a213dd5e2a5c8eb43370821e4a76d0c1fbda8e6cdabab73b6b2cc4b8c926",
    "scripts/check_phase5_capability_nexus_v27_whitespace.py": "b14478bb2ecadd74e875ce466879f4759b019b899a9af16fe33b3ac00b3efeda",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V27-001.sha256": "324072931ddaaff6baba1c1047434fff1b591f7bba7369b6411d8556d630bef8",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V27-001.sha256": "2c9135b796c634758775d62ae4fad40782807f20f2e7f459455c49bc08f60a62",
}
V28_HASHES = {
    "core/capability_nexus_v28.py": "4010ec3cacd14c3f6804835e04af101b72550432d345ea008c9d4f7187c1b166",
    "tests/test_capability_nexus_v28.py": "9964312809fb03c100066ab9a3b028fc0807264c8e664814836f5dbcc649ce3d",
    "scripts/verify_phase5_capability_nexus_v28.py": "b2e9d45f66b790e4cf3158480828b51c726c0467a240d593d4d46b2fa2fc9630",
    "scripts/verify_phase5_capability_nexus_v28_worker.py": "5a47381798794725cd8700c73056b5d8c5e4d8e79460fe059a6a9228a3896235",
    "scripts/phase5_capability_nexus_v28_subtest_reporter.py": "0109b7bb5a9b972b05574481ad4a5be076179d897d3f4f96cc0208fd29a896a8",
    "scripts/check_phase5_capability_nexus_v28_whitespace.py": "b38e7bd2769349faaa4e6587cd817cdff751a995302f7cbcd47e2f29ad06e23c",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V28-001.sha256": "a305eb161afa80a31f434378682d778f4a2dce54aafa487719813bbaa954128a",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V28-001.sha256": "a98068bd79c2d4d0c0017ea56a35c35ab357d597427427d06fbe47b844185b29",
}
V29_HASHES = {
    "core/capability_nexus_v29.py": "7fb6735afe304d22c3cac8f0654327789a2d603a398b892ccbe32b7ef552a9ca",
    "tests/test_capability_nexus_v29.py": "bfbfbb70c8fe28f63c7a78c89e9e850a998e059f1fdd779ec100c72c21a6325c",
    "scripts/verify_phase5_capability_nexus_v29.py": "088df366076d6b4b9e50df86d261f10049bcefcba5fd8cacd880252eec70f978",
    "scripts/verify_phase5_capability_nexus_v29_worker.py": "36b490ed079a639a7ef8758864c5741d6996a4ea16ca003ef84a4447666d2b76",
    "scripts/phase5_capability_nexus_v29_subtest_reporter.py": "832b1fc860a551e1cc69c0c2c9d4ce6e3951762dc6fe6b85bf6bcd5b8735c97b",
    "scripts/check_phase5_capability_nexus_v29_whitespace.py": "09edee135d535bd46a0a9f7d5406bf29d139ac6c62e4e7251446f40f466ec467",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V29-001.sha256": "c3450d183158860aa91bf73245883f0feb41402b8f0c4567c28854bcb10e0ec3",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V29-001.sha256": "0b8ed1cf8b1b2b1e5fb770ee763021b1413973f6deea6590ad99ef04aa36fba1",
}
V30_HASHES = {
    "core/capability_nexus_v30.py": "d2a7bc76d14eb0ade4ac3ed04ee8c6c2eeebe0b81547af4e6ae44949387cd8d6",
    "tests/test_capability_nexus_v30.py": "dcc5db95a7ebfda08ab30cdb4cf196f1534df9956fb54ab007d13a9dfeae4840",
    "scripts/verify_phase5_capability_nexus_v30.py": "8957a799793dc8e1e118336629845a4320c4439ec729d0a724e990b5e39a1f99",
    "scripts/verify_phase5_capability_nexus_v30_worker.py": "135968b40246d3d7963cc5df0f508b6d4847f427b0deccdd8888bbf10f18e749",
    "scripts/phase5_capability_nexus_v30_subtest_reporter.py": "0b16e2d30226d51483b473ae4381496597f455df87a6cd2f2bd0cea6cc9d5cb7",
    "scripts/check_phase5_capability_nexus_v30_whitespace.py": "d49bae9b5cb51acdbcd0709528db5af39c1caa65712c5192ef775049cdadff36",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V30-001.sha256": "13f5adecf2ee987761511a492a4066446ba6e7d42bc9a677dbab0c272b3b584a",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V30-001.sha256": "e6fb21e6963902d7e358e75002376af0fae389c28177bd9bce333f7dc9d191e1",
}
V31_HASHES = {
    "core/capability_nexus_v31.py": "31943383dc4285b9af86502e428f4a8965664cccbaabecdc5e5a348a81f0b396",
    "tests/test_capability_nexus_v31.py": "ae2fc412a7b0a28680bed3188100d8a1b193502c481fc84e59812842db91b1c2",
    "scripts/verify_phase5_capability_nexus_v31.py": "d96588010b8b1eed524d53e82127eb83c9b69f048c156a4bb6768cec4b1e2ea3",
    "scripts/verify_phase5_capability_nexus_v31_worker.py": "f4ec8a712eb3c8cb230bc6e84b66558fcc5ff683c33178d0eb31ca2324e93904",
    "scripts/phase5_capability_nexus_v31_subtest_reporter.py": "9d402864bacfd9ac956b67d4fb354979582de7158f3809447ca277a4a2938adb",
    "scripts/check_phase5_capability_nexus_v31_whitespace.py": "5f63841bf4a8551edd21af3c1d36abc96842d73f4a50a087ee1defd535a8283d",
    "docs/onyx/VE-ARTIFACTS-P53-CAPABILITY-NEXUS-V31-001.sha256": "e332c904fac7fe9f53cd976210637fbb1a3b8aa74d55e828c95aa9ca448bc3ed",
    "docs/onyx/VE-SOURCE-P53-CAPABILITY-NEXUS-V31-001.sha256": "1fe65cb6c5e238c7b1066c72dbcab9d5967e3c8fc9d9055aa56cc30d0e4b888d",
}


def _assignment(path: Path, name: str):
    tree = ast.parse(path.read_text(encoding="utf-8"))
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(item, ast.Name) and item.id == name for item in node.targets
        ):
            return ast.literal_eval(node.value)
    raise AssertionError(name)


def _operation(**changes) -> OperationDescriptorV32:
    values = {
        "operation_id": "catalog_read",
        "kind": OperationKindV32.READ,
        "description": "Read allowlisted metadata.",
        "parameter_schema_json": '{"properties":{},"type":"OBJECT"}',
        "required_scopes": ("catalog.metadata.read",),
        "data_classes": ("allowlisted_metadata",),
        "risk_class": "low",
        "approval_class": "host_policy_required",
        "allowed_targets": ("local_catalog",),
    }
    values.update(changes)
    return OperationDescriptorV32(**values)


def _descriptor(**changes) -> CapabilityDescriptorV32:
    values = {
        "capability_id": "local.catalog",
        "capability_version": "v32",
        "provider": "onyx_local",
        "transport": TransportKindV32.LOCAL,
        "api_name": "local_catalog",
        "api_version": CATALOG_CONTRACT_VERSION_V32,
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "credential_alias": None,
        "operations": (_operation(),),
        "status": CapabilityStatusV32.DISABLED,
        "status_reason": "candidate_not_activated",
        "limitations": ("no_dispatch",),
    }
    values.update(changes)
    return CapabilityDescriptorV32(**values)


def _items(count: int = 5) -> tuple[CatalogItemV32, ...]:
    return tuple(
        CatalogItemV32(f"item-{i:02d}", f"Item {i}", "fixture", "v32", ("safe",))
        for i in range(count)
    )


def _adapter(hook=lambda: None, **changes) -> LocalCatalogReadAdapterV32:
    values = {
        "items": _items(),
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "cursor_signing_key": KEY,
        "read_hook": hook,
        "status": CapabilityStatusV32.AVAILABLE_READ_ONLY,
        "status_reason": "healthy",
    }
    values.update(changes)
    return LocalCatalogReadAdapterV32(**values)


def _request(**changes) -> CatalogReadRequestV32:
    values = {
        "workspace_id": WORKSPACE,
        "account_id": ACCOUNT,
        "profile_id": PROFILE,
        "target": "local_catalog",
        "correlation_id": "corr-001",
        "page_size": 2,
    }
    values.update(changes)
    return CatalogReadRequestV32(**values)


def test_v1_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V1_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v2_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V2_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v3_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V3_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v4_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V4_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v5_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V5_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v6_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V6_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v7_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V7_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v8_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V8_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v9_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V9_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v10_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V10_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v11_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V11_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v12_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V12_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v13_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V13_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v14_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V14_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v15_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V15_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v16_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V16_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v17_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V17_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v18_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V18_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v19_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V19_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v20_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V20_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v21_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V21_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v22_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V22_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v23_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V23_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v24_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V24_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v25_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V25_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v26_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V26_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v27_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V27_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v28_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V28_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v29_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V29_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v30_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V30_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v31_candidate_bytes_are_exact_and_remain_rejected_history():
    for relative, expected in V31_HASHES.items():
        assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == expected


def test_v32_core_and_metadata_behavior_are_exact_version_normalization():
    prior = (ROOT / "core/capability_nexus_v31.py").read_text(encoding="utf-8")
    current = (ROOT / "core/capability_nexus_v32.py").read_text(encoding="utf-8")
    assert prior.replace("V31", "V32").replace("v31", "v32") == current


def test_v20_windows_suspended_job_path_is_exact_after_version_normalization():
    prior = ast.parse(
        (ROOT / "scripts/verify_phase5_capability_nexus_v20.py").read_text(
            encoding="utf-8"
        )
    )
    current = ast.parse(
        (ROOT / "scripts/verify_phase5_capability_nexus_v32.py").read_text(
            encoding="utf-8"
        )
    )
    names = {
        "_kernel32",
        "_checked_close",
        "_WindowsJob",
        "_wait_job_empty",
        "_create_file_handle",
        "_bounded_output",
        "_windows_phase",
    }

    def selected(tree):
        return {
            node.name: ast.unparse(node)
            for node in tree.body
            if isinstance(node, (ast.FunctionDef, ast.ClassDef)) and node.name in names
        }

    expected = selected(prior)
    normalized = {
        name: source.replace("V32", "V20").replace("v32", "v20")
        for name, source in selected(current).items()
    }
    assert set(expected) == names
    assert normalized == expected


def _percent_layers(value: str, layers: int) -> str:
    for _ in range(layers):
        value = quote(value, safe="-._~/:@")
    return value


def _base64_layers(
    value: str, layers: int, *, urlsafe: bool = False, unpadded: bool = False
) -> str:
    for _ in range(layers):
        encoder = base64.urlsafe_b64encode if urlsafe else base64.b64encode
        value = encoder(value.encode()).decode()
        if unpadded:
            value = value.rstrip("=")
    return value


def test_registry_requires_profile_and_binds_discovery_exactly():
    nexus = CapabilityNexusV32()
    descriptor = _descriptor()
    nexus.register(descriptor)
    with pytest.raises(TypeError):
        nexus.discover(
            descriptor.capability_id,
            workspace_id=WORKSPACE,
            account_id=ACCOUNT,
            expected_version="v32",
            expected_digest=descriptor.digest,
        )
    for profile in ("profile-other", "PROFILE-alpha"):
        with pytest.raises(CapabilityV32DeniedError):
            nexus.discover(
                descriptor.capability_id,
                workspace_id=WORKSPACE,
                account_id=ACCOUNT,
                profile_id=profile,
                expected_version="v32",
                expected_digest=descriptor.digest,
            )


def test_snapshot_is_profile_bound_and_digest_changes_by_profile():
    nexus = CapabilityNexusV32()
    nexus.register(_descriptor())
    first = nexus.snapshot(
        workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
    )
    other = nexus.snapshot(
        workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id="profile-other"
    )
    assert len(first.entries) == 1 and other.entries == ()
    assert first.snapshot_digest != other.snapshot_digest
    with pytest.raises(FrozenInstanceError):
        first.profile_id = "changed"  # type: ignore[misc]


def test_projection_constructor_rejects_cross_profile_and_authority():
    descriptor = _descriptor()
    with pytest.raises(CapabilityV32ContractError):
        CapabilityProjectionV32(
            descriptor,
            descriptor.digest,
            WORKSPACE,
            ACCOUNT,
            "profile-other",
            CapabilityStatusV32.DISABLED,
            "disabled",
        )
    with pytest.raises(CapabilityV32ContractError):
        CapabilityProjectionV32(
            descriptor,
            descriptor.digest,
            WORKSPACE,
            ACCOUNT,
            PROFILE,
            CapabilityStatusV32.DISABLED,
            "disabled",
            authority_granted=True,
        )


class _GateSubclass(NexusFeatureGateV32):
    pass


class _FakeGate:
    nexus_enabled = False
    shadow_mode = True
    dispatch_enabled = False


@pytest.mark.parametrize("gate", [_GateSubclass(), _FakeGate(), object()])
def test_registry_rejects_gate_subclasses_fakes_and_duck_types(gate):
    with pytest.raises(CapabilityV32ContractError, match="exact concrete"):
        CapabilityNexusV32(gate)  # type: ignore[arg-type]


def test_exact_gate_is_frozen_default_off_and_lock_order_is_declared():
    gate = NexusFeatureGateV32()
    nexus = CapabilityNexusV32(gate)
    assert nexus.gate is gate and nexus.lock_order == LOCK_ORDER_V32
    with pytest.raises(FrozenInstanceError):
        gate.shadow_mode = False  # type: ignore[misc]
    for values in (
        {"nexus_enabled": True},
        {"shadow_mode": False},
        {"dispatch_enabled": True},
    ):
        with pytest.raises(CapabilityV32ContractError):
            NexusFeatureGateV32(**values)


@pytest.mark.parametrize(
    "key",
    [
        "api_key",
        "Api-Key",
        "TOKEN",
        "pass.word",
        "Secret",
        "authorization",
        "cookie",
        "private-key",
        "%61pi_key",
    ],
)
def test_metadata_rejects_secret_names_and_normalization_bypasses(key):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=((key, "redacted"),))


@pytest.mark.parametrize(
    "value",
    [
        "token=abcd1234",
        "TOKEN%3Dabcd1234",
        "password:abcd1234",
        "-----BEGIN PRIVATE KEY-----",
        "eyJabcdefgh.abcdefgh.abcdefgh",
        base64.b64encode(b"api_key=abcd1234").decode(),
    ],
)
def test_metadata_rejects_plain_percent_and_base64_secret_values(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_percent_secret(layers):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(
            metadata=(("data_source", _percent_layers("token=abcd1234", layers)),)
        )


@pytest.mark.parametrize("layers", [2, 3])
def test_metadata_rejects_double_and_triple_base64_secret(layers):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(
            metadata=(("data_source", _base64_layers("api_key=abcd1234", layers)),)
        )


def test_metadata_rejects_mixed_percent_base64_secret():
    encoded = _percent_layers(_base64_layers("password=abcd1234", 2), 2)
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("unpadded", [False, True])
def test_metadata_rejects_urlsafe_padded_and_unpadded_secret(unpadded):
    encoded = _base64_layers(
        "authorization=Bearer1234", 2, urlsafe=True, unpadded=unpadded
    )
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize(
    "value",
    [
        "ＴＯＫＥＮ＝abcd1234",
        "ToKeN=abcd1234",
        "to\u200bken=abcd1234",
        "token\x00=abcd1234",
    ],
)
def test_metadata_rejects_case_unicode_and_control_canaries(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "sk-" + "A" * 32,
        "sk-proj-" + "B" * 40,
        "ghp_" + "c" * 36,
        "gho_" + "D" * 40,
        "AKIA" + "E" * 16,
        "ASIA" + "F" * 16,
        "sk_live_" + "g" * 24,
        "sk_test_" + "H" * 24,
        "AIza" + "i" * 35,
        "Bearer " + "j" * 32,
        "Basic " + base64.b64encode(b"user:password").decode(),
        "github_pat_" + "K" * 30,
        "xoxb-" + "1234567890-abcdefghijklmnop",
        "npm_" + "L" * 36,
        "SG." + "M" * 22 + "." + "N" * 43,
        "SK" + "a1" * 16,
        "Ab3_defGHIjklMNopQRstuVWxyz0123456789-_aBCDefGhijkLmnop",
    ],
)
def test_metadata_rejects_bounded_raw_credential_families(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "sk-short",
        "ghp_short",
        "AKIA" + "A" * 15,
        "BKIA" + "A" * 16,
        "pk_live_" + "a" * 24,
        "AIza" + "a" * 34,
        "bearer_policy",
        "Basic authentication",
        "sk-documentation-reference-2026",
        "github_pat_example",
        "xoxb-documentation",
        "npm_short",
        "SG.example.reference",
        "SK" + "a" * 31,
        "BuildArtifact_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "Aa1" * 10 + "A",
    ],
)
def test_metadata_raw_credential_near_misses_remain_valid(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5",
        "Aa1Bb2Cc3Dd4Ee5Ff6Gg7Hh8Ii9Jj0Kk1Ll2Mm3Nn4Oo5Pp6Qq7Rr8Ss9Tt0Uu1",
    ],
)
def test_metadata_rejects_compact_opaque_tokens_at_32_and_64_plus(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_hashes_are_allowed_only_in_explicit_typed_hash_field():
    digest = "0123456789abcdef" * 4
    assert (
        dict(_descriptor(metadata=(("declaration_sha256", digest),)).metadata)[
            "declaration_sha256"
        ]
        == digest
    )
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", digest),))


@pytest.mark.parametrize(
    "prefix",
    [
        "token",
        "secret",
        "password",
        "auth",
        "api_key",
        "TOKEN",
        "tоken",
        "tᴏken",
        "credential",
    ],
)
def test_opaque_semantic_exemption_never_allows_protected_prefixes(prefix):
    value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_protected_opaque_prefixes_are_rejected_after_encoding_layers():
    value = "api_key_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    for encoded in (_percent_layers(value, 2), _base64_layers(value, 2)):
        with pytest.raises(CapabilityV32ContractError):
            _descriptor(metadata=(("data_source", encoded),))


def test_unknown_prefix_with_opaque_tail_is_rejected():
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(
            metadata=(("data_source", "unknown_Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"),)
        )


@pytest.mark.parametrize(
    "value",
    [
        "BuildArtifact_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "documentation_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "reference_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
        "release_2026-AbCdEfGhIjKlMnOpQrStUvWxYz1234567890",
    ],
)
def test_explicit_safe_semantic_prefixes_preserve_wordlike_identifiers(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_protected_prefix_tail_boundary_is_bounded():
    for size in (16, 25, 26):
        with pytest.raises(CapabilityV32ContractError):
            _descriptor(metadata=(("data_source", "token_" + "A" * size),))


@pytest.mark.parametrize("prefix", sorted(nexus_v32_module._SECRET_NAMES))
def test_every_canonical_secret_name_rejects_compact_opaque_suffix(prefix):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(
            metadata=(
                ("data_source", prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"),
            )
        )


@pytest.mark.parametrize(
    "prefix",
    [
        "access_token",
        "refresh_token",
        "ACCESS_TOKEN",
        "Refresh_Token",
        "access_tоken",
        "refresh_tᴏken",
    ],
)
def test_access_and_refresh_token_prefix_spans_reject_case_and_confusables(prefix):
    value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_access_refresh_prefixes_reject_after_percent_and_base64_layers():
    for prefix in ("access_token", "refresh_token"):
        value = prefix + "_" + "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8St1Uv3Wx5"
        for encoded in (_percent_layers(value, 2), _base64_layers(value, 2)):
            with pytest.raises(CapabilityV32ContractError):
                _descriptor(metadata=(("data_source", encoded),))


def test_multi_segment_secret_prefix_and_31_32_total_boundaries():
    for size in (16, 18, 19):
        with pytest.raises(CapabilityV32ContractError):
            _descriptor(metadata=(("data_source", "access_token_" + "A" * size),))


@pytest.mark.parametrize("name", sorted(nexus_v32_module._SECRET_NAMES))
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_secret_name_is_rejected_at_every_span_position(name, position):
    opaque = "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8"
    values = {
        "leading": f"__{name}__{opaque}",
        "middle": f"source__{name}__{opaque}",
        "trailing": f"{opaque}__{name}__",
    }
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize(
    "value",
    [
        "token" + "A" * 40,
        "source_token_" + "A" * 20,
        "documentation_access_token_" + "A" * 20,
        "source__token__" + "A" * 20,
        "___token___" + "A" * 20,
    ],
)
def test_protected_names_ignore_namespace_and_separator_bypasses(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_short_protected_names_reject_after_base64_layers():
    for value in ("token_" + "A" * 16, "access_token_" + "A" * 16):
        with pytest.raises(CapabilityV32ContractError):
            _descriptor(metadata=(("data_source", _base64_layers(value, 2)),))


@pytest.mark.parametrize(
    "value",
    [
        "tokenization",
        "authentication",
        "source_documentation",
        "reference_identifier",
        "documentation_reference_2026",
    ],
)
def test_wordlike_non_secret_identifiers_remain_valid(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "sourceToken" + "A" * 20,
        "sourceAccessToken" + "A" * 20,
        "sourceApiKey" + "A" * 20,
        "sourceCredential" + "A" * 20,
        "A" * 20 + "TokenSource",
        "prefixTokenMiddle" + "A" * 20,
        "prefixAccessTokenMiddle" + "A" * 20,
        "prefixApiKeyMiddle" + "A" * 20,
        "prefixCredentialMiddle" + "A" * 20,
        "sourcetoken" + "a" * 20,
        "sourceaccesstoken" + "a" * 20,
        "sourceapikey" + "a" * 20,
        "sourcecredential" + "a" * 20,
    ],
)
def test_camel_pascal_and_case_free_protected_names_reject_at_any_offset(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "separator", ["_", "-", ".", "/", " ", "__", "--", "..", "//", " \t "]
)
@pytest.mark.parametrize("name", ["token", "access_token", "api_key", "credential"])
def test_mixed_repeated_namespace_separators_cannot_hide_protected_names(
    separator, name
):
    rendered_name = separator.join(name.split("_"))
    value = separator.join(("source", rendered_name, "A" * 20))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "name",
    sorted(nexus_v32_module._SECRET_NAMES | nexus_v32_module._CREDENTIAL_OPAQUE_NAMES),
)
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_canonical_protected_table_name_rejects_at_every_position(name, position):
    opaque = "Ab3Cd5Ef7Gh9Jk2Lm4Np6Qr8"
    values = {
        "leading": f"..{name}//{opaque}",
        "middle": f"source/{name}..{opaque}",
        "trailing": f"{opaque}  {name}/source",
    }
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize(
    "value",
    [
        "sourceTоken" + "A" * 20,
        "sourceAccesѕToken" + "A" * 20,
        "sourceApiKεy" + "A" * 20,
        "sourceCredеntial" + "A" * 20,
    ],
)
def test_camel_confusable_bypasses_reject_after_every_base64_layer(value, layers):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", _base64_layers(value, layers)),))


@pytest.mark.parametrize(
    "value",
    [
        "tokenization",
        "authentication",
        "source.tokenization.reference",
        "source/authentication/reference",
        "TokenizationReference",
        "AuthenticationReference",
    ],
)
def test_benign_wordlike_identifiers_remain_valid_across_namespace_and_camel_forms(
    value,
):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "tail",
    [
        ("abcd", "efgh", "ijkl", "mnop"),
        ("ab12", "cd34", "ef56", "gh78"),
        ("abcdef", "ghijkl", "mnop"),
        ("abcdefgh", "ijklmnop"),
    ],
)
@pytest.mark.parametrize("separator", ["_", "-", ".", "/", " ", "__", ".//.", "_ / "])
@pytest.mark.parametrize(
    "name", ["token", "access_token", "auth", "api_key", "credential"]
)
def test_generated_chunked_opaque_tails_reject_across_namespaces(name, separator, tail):
    rendered_name = separator.join(name.split("_"))
    value = separator.join(("namespace", rendered_name, *tail))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "name",
    sorted(nexus_v32_module._SECRET_NAMES | nexus_v32_module._CREDENTIAL_OPAQUE_NAMES),
)
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
def test_every_protected_name_rejects_chunked_tail_at_every_generated_position(
    name, position
):
    chunks = ("ab12", "cd34", "ef56", "gh78")
    values = {
        "leading": ".".join((name, *chunks, "namespace")),
        "middle": "/".join(("namespace", name, *chunks)),
        "trailing": "_".join((*chunks, name, "namespace")),
    }
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize(
    "value",
    [
        "namespace.tоken.abcd.efgh.ijkl.mnop",
        "namespace.access.tоken.ab12.cd34.ef56.gh78",
        "namespace.аuth.abcdef.ghijkl.mnop",
        "namespace.credеntial.abcdefgh.ijklmnop",
    ],
)
def test_chunked_confusable_credentials_reject_after_base64_layers(value, layers):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", _base64_layers(value, layers)),))


@pytest.mark.parametrize("layers", [1, 2, 3])
def test_chunked_credentials_reject_after_percent_layers(layers):
    value = "access token abcd efgh ijkl mnop"
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", _percent_layers(value, layers)),))


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("position", ["prefix", "suffix"])
@pytest.mark.parametrize(
    "opaque", ["A" * 20, "abcd_efgh_ijkl_mnop", "ab12.cd34.ef56.gh78"]
)
def test_benign_word_exemption_never_hides_appended_or_prepended_opaque_material(
    safe, position, opaque
):
    value = safe + opaque if position == "prefix" else opaque + safe
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    ("protected_phrase", "natural_word"),
    [
        ("authorization", "interoperability"),
        ("token", "characterization"),
        ("auth", "internationalization"),
        ("access token", "standardization"),
        ("authorization", "collaboration"),
        ("token", "configuration"),
        ("auth", "identification"),
        ("access token", "documentation"),
    ],
)
@pytest.mark.parametrize("form", ["space", "camel", "namespace"])
def test_generated_natural_language_words_are_not_opaque_credentials(
    protected_phrase, natural_word, form
):
    words = protected_phrase.split()
    if form == "space":
        value = " ".join((*words, natural_word))
    elif form == "camel":
        value = words[0].title() + "".join(
            word.title() for word in (*words[1:], natural_word)
        )
    else:
        value = ".".join((*words, natural_word))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "auth access control policies",
        "auth_access_control_policies",
        "authorization interoperability standards",
        "token characterization reference",
        "access token interoperability policy",
    ],
)
def test_multiword_benign_prose_is_not_aggregated_as_an_opaque_tail(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("split", range(1, 16))
@pytest.mark.parametrize(
    "delimiter",
    ["|", ",", "@", ":", ";", "!", "?", "+", "=", "~", "•", "—", "、", "§", "→"],
)
def test_every_two_chunk_partition_at_threshold_rejects_across_unicode_delimiters(
    split, delimiter
):
    opaque = "z9x8c7v6b5n4m3q2"
    value = delimiter.join(("namespace", "token", opaque[:split], opaque[split:]))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("split", range(1, 16))
@pytest.mark.parametrize(
    "opaque",
    ["z9x8c7v6b5n4m3q2", "bcdfghjklmnpqrst", "aaaaaaaaaaaaaaaa", "Ab3Cd5Ef7Gh9Jk2L"],
)
def test_generated_opaque_families_reject_independent_of_partition_size(split, opaque):
    value = "namespace|auth|" + opaque[:split] + "@" + opaque[split:]
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "name",
    sorted(nexus_v32_module._SECRET_NAMES | nexus_v32_module._CREDENTIAL_OPAQUE_NAMES),
)
@pytest.mark.parametrize("position", ["leading", "middle", "trailing"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
def test_all_canonical_names_reject_at_all_positions_across_punctuation_categories(
    name, position, delimiter
):
    chunks = ("z9x8c7v6b5n4m", "3q2")
    values = {
        "leading": delimiter.join((name, *chunks, "namespace")),
        "middle": delimiter.join(("namespace", name, *chunks)),
        "trailing": delimiter.join((*chunks, name, "namespace")),
    }
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize("layers", [1, 2, 3])
@pytest.mark.parametrize("encoding", ["base64", "percent"])
@pytest.mark.parametrize(
    "value",
    [
        "namespace|tоken|z9x8c7v6b5n4m|3q2",
        "namespace,access,tоken,z9x8c7v6b5n4m,3q2",
        "namespace@аuth@z9x8c7v6b5n4m@3q2",
        "namespace•credеntial•z9x8c7v6b5n4m•3q2",
    ],
)
def test_unicode_delimiter_confusables_reject_after_every_encoding_layer(
    value, encoding, layers
):
    encoded = (
        _base64_layers(value, layers)
        if encoding == "base64"
        else _percent_layers(value, layers)
    )
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
def test_exact_safe_word_boundaries_survive_arbitrary_unicode_punctuation(
    safe, delimiter
):
    value = delimiter.join(("namespace", safe, "responsibilities"))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("safe", ["tokenization", "authentication"])
@pytest.mark.parametrize("delimiter", ["|", ",", "@", "•", "—", "、", "→"])
@pytest.mark.parametrize("split", [1, 3, 8, 13, 15])
def test_safe_words_never_exempt_partitioned_opaque_material(safe, delimiter, split):
    opaque = "z9x8c7v6b5n4m3q2"
    value = delimiter.join((safe, opaque[:split], opaque[split:]))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    ("protected_phrase", "natural_word"),
    [
        ("authorization", "responsibilities"),
        ("token", "telecommunications"),
        ("auth", "microarchitecture"),
        ("access token", "multidisciplinary"),
        ("authorization", "interoperability"),
        ("token", "characterization"),
        ("auth", "internationalization"),
        ("access token", "standardization"),
        ("authorization", "collaboration"),
        ("token", "configuration"),
        ("auth", "identification"),
        ("access token", "documentation"),
        ("authorization", "observability"),
        ("token", "extensibility"),
        ("auth", "portability"),
        ("access token", "maintainability"),
        ("authorization", "governance"),
    ],
)
@pytest.mark.parametrize("form", ["space", "camel", "pascal", "punctuation"])
def test_broad_generated_natural_technical_families_remain_valid(
    protected_phrase, natural_word, form
):
    words = protected_phrase.split()
    if form == "space":
        value = " ".join((*words, natural_word))
    elif form == "camel":
        value = words[0] + "".join(word.title() for word in (*words[1:], natural_word))
    elif form == "pascal":
        value = "".join(word.title() for word in (*words, natural_word))
    else:
        value = "|".join((*words, natural_word))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "authorization responsibilities for distributed systems",
        "token telecommunications standards and governance",
        "auth microarchitecture documentation reference",
        "access token multidisciplinary policy review",
        "AuthorizationResponsibilities",
        "TokenTelecommunications",
        "AuthMicroarchitecture",
        "AccessTokenMultidisciplinary",
    ],
)
def test_natural_technical_sentences_and_camel_compounds_are_not_opaque(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("split", range(1, 16))
@pytest.mark.parametrize(
    "delimiter", ["|", ",", "@", ":", ";", "+", "=", "•", "—", "、", "→"]
)
def test_two_sided_opaque_partitions_aggregate_across_protected_span(split, delimiter):
    opaque = "z9x8c7v6b5n4m3q2"
    value = delimiter.join((opaque[:split], "token", opaque[split:]))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "opaque",
    [
        "qwertyuiopasdfghization",
        "asdfghjklqwertyability",
        "abcdefghijklmnopization",
        "zxcvbnmasdfghology",
        "poiuytrewqlkjhgfment",
    ],
)
@pytest.mark.parametrize("position", ["leading", "trailing", "two_sided"])
def test_natural_looking_suffix_never_blesses_keyboard_or_sequential_material(
    opaque, position
):
    values = {
        "leading": f"token|{opaque}",
        "trailing": f"{opaque}|token",
        "two_sided": f"{opaque[:8]}|token|{opaque[8:]}",
    }
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", values[position]),))


@pytest.mark.parametrize(
    "value",
    [
        "token platform database",
        "authorization service endpoint registry",
        "auth deployment orchestration",
        "access token federation synchronization",
        "TokenPlatformDatabase",
        "AuthorizationServiceEndpointRegistry",
        "AuthDeploymentOrchestration",
        "AccessTokenFederationSynchronization",
    ],
)
def test_held_out_ordinary_technical_prose_and_compounds_remain_valid(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "word",
    [
        "responsibilities",
        "telecommunications",
        "microarchitecture",
        "multidisciplinary",
        "observability",
        "extensibility",
        "portability",
        "maintainability",
        "deployment",
        "orchestration",
        "federation",
        "synchronization",
        "platform",
        "database",
        "service",
        "endpoint",
        "registry",
    ],
)
def test_embedded_ngram_model_accepts_held_out_natural_boundary_corpus(word):
    assert (
        nexus_v32_module._english_word_score(word)
        >= nexus_v32_module._NATURAL_SCORE_THRESHOLD
    )


@pytest.mark.parametrize(
    "word",
    [
        "qwertyuiopasdfghization",
        "abcdefghijklmnop",
        "bcdfghjklmnpqrst",
        "zxcvbnmasdfghjkl",
        "poiuytrewqlkjhgfment",
        "aaaaaaaaaaaaaaaa",
    ],
)
def test_embedded_ngram_model_rejects_generated_opaque_boundary_corpus(word):
    assert (
        nexus_v32_module._english_word_score(word)
        < nexus_v32_module._NATURAL_SCORE_THRESHOLD
    )


@pytest.mark.parametrize(
    "protected", ["tóken", "to\u0301ken", "áuth", "a\u0301uth", "tóкen"]
)
@pytest.mark.parametrize("encoding", ["plain", "base64", "percent"])
@pytest.mark.parametrize("delimiter", ["|", "@", "•", "—"])
def test_composed_decomposed_diacritic_and_confusable_names_reject_every_encoding(
    protected, encoding, delimiter
):
    raw = delimiter.join(("z9x8c7v6", protected, "b5n4m3q2"))
    value = {
        "plain": raw,
        "base64": _base64_layers(raw, 2),
        "percent": _percent_layers(raw, 2),
    }[encoding]
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "token abcd efgh interoperability ijkl mnop",
        "token|abcd|efgh|interoperability|ijkl|mnop",
        "abcd efgh authorization responsibilities ijkl mnop",
        "abcd|efgh|authorization|responsibilities|ijkl|mnop",
    ],
)
def test_natural_word_interrupt_cannot_erase_credential_shaped_opaque_aggregate(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "арі_кеу=abcd1234",
        "tоken=abcd1234",
        "раssword=abcd1234",
        "sεcret=abcd1234",
        "аuth=abcd1234",
        "cοοkie=abcd1234",
        "рrivate=abcd1234",
        "вearer=abcd1234",
    ],
)
def test_metadata_rejects_cyrillic_and_greek_secret_confusables(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_metadata_confusables_are_scanned_after_mixed_decoding_layers():
    encoded = _percent_layers(_base64_layers("tоken=abcd1234", 2), 2)
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", encoded),))


@pytest.mark.parametrize("value", ["token\u202e=abcd1234", "to\u0338ken=abcd1234"])
def test_metadata_rejects_bidi_and_combining_tricks(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value",
    [
        "Status: operação concluída em 東京",
        "Описание: deployment concluído",
        "Δεδομένα: relatório final готов",
    ],
)
def test_metadata_allows_benign_mixed_script_human_descriptions_with_colon(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize(
    "value", ['{"tоken":"abcd1234"}', "passwᴏrd:abcd1234", "аuth=abcd1234"]
)
def test_metadata_rejects_confusable_secret_assignments_and_json_fragments(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("value", ["東京カタログ", "каталогданных", "Δεδομένα"])
def test_metadata_preserves_benign_unstructured_international_display(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


@pytest.mark.parametrize("field", ["tᴏken", "tօken", "passwᴏrd", "арі_кеу"])
def test_schema_rejects_non_ascii_and_confusable_structured_field_keys(field):
    schema = '{"properties":{"' + field + '":{"type":"STRING"}},"type":"OBJECT"}'
    with pytest.raises(CapabilityV32ContractError):
        _operation(parameter_schema_json=schema)


@pytest.mark.parametrize(
    "value",
    ["ghp_" + "A" * 30, "AKIA" + "B" * 16, "sk_test_" + "C" * 24],
)
def test_schema_rejects_raw_credentials_in_nested_defaults_examples_and_descriptions(
    value,
):
    for field in ("default", "example", "description"):
        schema = {
            "properties": {"safe_field": {field: value, "type": "STRING"}},
            "type": "OBJECT",
        }
        encoded = nexus_v32_module.json.dumps(
            schema, sort_keys=True, separators=(",", ":")
        )
        with pytest.raises(CapabilityV32ContractError):
            _operation(parameter_schema_json=encoded)


def test_recursive_schema_cycle_depth_node_and_scalar_budgets_fail_closed():
    cycle = {}
    cycle["safe"] = cycle
    with pytest.raises(CapabilityV32ContractError, match="cycle"):
        nexus_v32_module._reject_json_secrets(cycle, "fixture")
    deep = current = {}
    for index in range(26):
        current["safe"] = {}
        current = current["safe"]
    with pytest.raises(CapabilityV32ContractError):
        nexus_v32_module._reject_json_secrets(deep, "fixture")
    with pytest.raises(CapabilityV32ContractError, match="node"):
        nexus_v32_module._reject_json_secrets(0, "fixture", _budget=[4096, 0])
    with pytest.raises(CapabilityV32ContractError, match="scalar byte"):
        nexus_v32_module._reject_json_secrets(["a" * 4096] * 17, "fixture")


@pytest.mark.parametrize(
    "key,value",
    [
        ("data_source", "constructor_allowlist"),
        ("dispatch_path", "legacy_unchanged"),
        ("policy_source", "trusted_host_mapping"),
        ("fallback_class", "explicit_browser_fallback"),
        ("declaration_sha256", "a" * 64),
        ("data_source", "healthy"),
        ("data_source", "local_catalog"),
    ],
)
def test_benign_metadata_fixtures_remain_valid(key, value):
    assert dict(_descriptor(metadata=((key, value),)).metadata)[key] == value


@pytest.mark.parametrize(
    "key,value",
    [
        ("data_source", "Healthy"),
        ("data_source", "healthy "),
        ("data_source", "constructor-allowlist"),
        ("dispatch_path", "LEGACY_UNCHANGED"),
        ("policy_source", "trusted host mapping"),
        ("fallback_class", "explicit_browser_fallback\n"),
        ("declaration_sha256", "A" * 64),
        ("declaration_sha256", "a" * 63),
        ("declaration_sha256", "g" * 64),
        ("Data_Source", "healthy"),
        ("data_source", "ｈｅａｌｔｈｙ"),
        ("data_source", b"healthy"),
        ("data_source", None),
    ],
)
def test_metadata_contract_requires_exact_case_ascii_type_and_canonical_form(
    key, value
):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=((key, value),))


@pytest.mark.parametrize(
    "key,value",
    [
        ("data_source", "future_catalog"),
        ("dispatch_path", "new_dispatcher"),
        ("policy_source", "dynamic_policy"),
        ("fallback_class", "automatic_browser_fallback"),
    ],
)
def test_every_non_hash_metadata_key_is_a_closed_enum(key, value):
    with pytest.raises(CapabilityV32ContractError, match="closed enum"):
        _descriptor(metadata=((key, value),))


@pytest.mark.parametrize(
    "value",
    [
        "token platform database",
        "東京カタログ",
        "بيانات النظام المحلية",
        "qwertyuiopasdfghization",
        "abcd1234|token|efgh5678",
        base64.b64encode(b"token platform database").decode(),
        quote("tóken", safe=""),
        "to\u0301ken",
        "authorization responsibilities interoperability",
    ],
)
def test_v13_adversarial_and_benign_text_classes_are_not_metadata_values(value):
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", value),))


def test_metadata_enum_table_is_read_only_and_future_values_require_source_change():
    assert dict(nexus_v32_module._METADATA_ENUMS) == {
        "data_source": frozenset({"constructor_allowlist", "healthy", "local_catalog"}),
        "dispatch_path": frozenset({"legacy_unchanged"}),
        "fallback_class": frozenset({"explicit_browser_fallback"}),
        "policy_source": frozenset({"trusted_host_mapping"}),
    }
    with pytest.raises(TypeError):
        nexus_v32_module._METADATA_ENUMS["data_source"] = frozenset({"future_catalog"})
    with pytest.raises(AttributeError):
        nexus_v32_module._METADATA_ENUMS["data_source"].add("future_catalog")


@pytest.mark.parametrize(
    "description",
    [
        "Status: operação concluída em 東京",
        "Описание: deployment concluído",
        "بيانات النظام المحلية متاحة",
    ],
)
def test_benign_human_text_remains_valid_only_in_description_context(description):
    assert _operation(description=description).description == description
    schema = {
        "properties": {"safe_field": {"description": description, "type": "STRING"}},
        "type": "OBJECT",
    }
    encoded = nexus_v32_module.json.dumps(
        schema, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    )
    assert _operation(parameter_schema_json=encoded).parameter_schema_json == encoded


@pytest.mark.parametrize(
    "description",
    [
        "ghp_" + "A" * 30,
        base64.b64encode(("sk_test_" + "B" * 24).encode()).decode(),
        "tоken=abcd1234",
    ],
)
def test_description_context_preserves_decoded_credential_and_confusable_rejection(
    description,
):
    with pytest.raises(CapabilityV32ContractError):
        _operation(description=description)


def test_legacy_declaration_description_uses_the_same_content_scanner():
    declarations = [
        dict(item) for item in _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    ]
    declarations[0] = {
        **declarations[0],
        "description": base64.b64encode(b"ghp_AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA").decode(),
    }
    policies = _assignment(ROOT / "core/permission_broker.py", "MODEL_TOOL_POLICIES")
    with pytest.raises(CapabilityV32ContractError):
        build_legacy_descriptors_v32(
            declarations,
            policies,
            workspace_id=WORKSPACE,
            account_id=ACCOUNT,
            profile_id=PROFILE,
        )


def test_metadata_rejects_malformed_ambiguous_and_residual_encodings():
    for value in ("safe%ZZvalue", "abcd+_==", "safe\\u0074oken"):
        with pytest.raises(CapabilityV32ContractError):
            _descriptor(metadata=(("data_source", value),))


def test_metadata_rejects_depth_and_expansion_bombs():
    too_deep = _base64_layers("token=abcd1234", 8)
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", too_deep),))
    expansion = "\ufdfa" * 500
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", expansion),))


def test_content_decoding_cycle_detection_fails_closed(monkeypatch):
    transitions = {"cycle_a": "cycle_b", "cycle_b": "cycle_a"}
    monkeypatch.setattr(
        nexus_v32_module,
        "_canonical_percent_decode",
        lambda value: transitions.get(value),
    )
    with pytest.raises(CapabilityV32ContractError, match="cycle"):
        nexus_v32_module._validate_content_decoding_closure("cycle_a")


def test_metadata_accepts_only_declared_safe_keys_and_opaque_alias_not_value():
    descriptor = _descriptor(
        credential_alias="alias:catalog/account",
        metadata=(("data_source", "constructor_allowlist"),),
    )
    assert descriptor.credential_alias == "alias:catalog/account"
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("random_note", "safe"),))
    with pytest.raises(CapabilityV32ContractError):
        _descriptor(metadata=(("data_source", {"token": "hidden"}),))


def test_nested_schema_secret_canaries_are_rejected():
    with pytest.raises(CapabilityV32ContractError):
        _operation(
            parameter_schema_json='{"properties":{"nested":{"properties":{"Password":{"type":"STRING"}}}}}'
        )


def test_adapter_defaults_disabled_and_has_no_dispatch_or_mutation():
    adapter = LocalCatalogReadAdapterV32(
        _items(),
        workspace_id=WORKSPACE,
        account_id=ACCOUNT,
        profile_id=PROFILE,
        cursor_signing_key=KEY,
        read_hook=lambda: None,
    )
    assert adapter.health().status is CapabilityStatusV32.DISABLED
    assert adapter.read_page(_request()).state is ReadStateV32.DENIED
    assert not hasattr(adapter, "execute") and not hasattr(adapter, "dispatch")
    with pytest.raises(CapabilityV32DeniedError):
        adapter.mutate({})


def test_hook_runs_without_adapter_lock_and_can_reenter_health():
    holder = {}
    observed = []

    def hook():
        observed.append(holder["adapter"].health().status)
        finished = threading.Event()
        thread = threading.Thread(
            target=lambda: (holder["adapter"].health(), finished.set())
        )
        thread.start()
        assert finished.wait(1), "adapter lock was held across hook"
        thread.join()

    holder["adapter"] = _adapter(hook)
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV32.COMPLETED
    assert observed == [CapabilityStatusV32.AVAILABLE_READ_ONLY]


def test_same_correlation_reentry_is_denied_before_second_hook_or_reservation():
    holder = {}
    calls = []
    request = _request()

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV32DeniedError, match="reentrancy"):
            holder["adapter"].read_page(request)

    holder["adapter"] = _adapter(hook)
    assert holder["adapter"].read_page(request).state is ReadStateV32.COMPLETED
    assert len(calls) == 1 and holder["adapter"].health().quota_remaining == 99


def test_new_correlation_and_indirect_hook_reentry_are_denied_without_quota_drift():
    holder = {}
    calls = []

    def indirect():
        holder["adapter"].read_page(_request(correlation_id="corr-nested"))

    def hook():
        calls.append(1)
        with pytest.raises(CapabilityV32DeniedError, match="reentrancy"):
            indirect()

    holder["adapter"] = _adapter(hook, quota_limit=1, rate_limit=1)
    assert holder["adapter"].read_page(_request()).state is ReadStateV32.COMPLETED
    limited = holder["adapter"].read_page(_request(correlation_id="corr-after"))
    assert limited.state is ReadStateV32.RATE_LIMITED
    assert calls == [1] and holder["adapter"].health().quota_remaining == 0


def test_hook_exception_cleans_reentrancy_guard_for_later_correlation():
    calls = []

    def hook():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("fixture")

    adapter = _adapter(hook)
    assert adapter.read_page(_request()).state is ReadStateV32.UNCERTAIN
    assert (
        adapter.read_page(_request(correlation_id="corr-002")).state
        is ReadStateV32.COMPLETED
    )
    assert calls == [1, 1]


def test_reentrancy_guard_rejects_hook_spawned_thread_before_reservation():
    holder = {}
    calls = []
    nested_errors = []

    def hook():
        calls.append(threading.get_ident())
        with ThreadPoolExecutor(max_workers=1) as pool:
            future = pool.submit(
                holder["adapter"].read_page, _request(correlation_id="corr-thread")
            )
            try:
                future.result(timeout=2)
            except CapabilityV32DeniedError as exc:
                nested_errors.append(str(exc))

    holder["adapter"] = _adapter(hook)
    outer = holder["adapter"].read_page(_request())
    assert outer.state is ReadStateV32.COMPLETED
    assert nested_errors == ["catalog read reentrancy is denied"]
    assert len(calls) == 1 and holder["adapter"].health().quota_remaining == 99
    assert (
        holder["adapter"].read_page(_request(correlation_id="corr-after")).state
        is ReadStateV32.COMPLETED
    )


def test_hook_guard_is_per_adapter_and_does_not_hold_lock_during_callback():
    second = _adapter()
    observed = []
    first = _adapter(lambda: observed.append(second.read_page(_request()).state))
    assert first.read_page(_request()).state is ReadStateV32.COMPLETED
    assert observed == [ReadStateV32.COMPLETED]


def test_historical_leaf_budget_exact_boundary_and_overflow():
    leaves = {f"leaf-{index}": "a" * 64 for index in range(4095)}
    verifier_v32._record_historical_leaf(leaves, "boundary", "b" * 64)
    assert len(leaves) == 4096
    with pytest.raises(verifier_v32.V32EvidenceError, match="leaf budget"):
        verifier_v32._record_historical_leaf(leaves, "overflow", "c" * 64)
    with pytest.raises(verifier_v32.V32EvidenceError, match="digest conflict"):
        verifier_v32._record_historical_leaf(leaves, "boundary", "d" * 64)


def test_wide_historical_manifest_and_cycle_fail_before_expansion(monkeypatch):
    wide = tuple(("a" * 64, f"leaf-{index}") for index in range(4097))
    monkeypatch.setattr(verifier_v32, "_historical_manifest", lambda relative: wide)
    monkeypatch.setattr(
        verifier_v32, "_verify_historical_path", lambda relative, digest: None
    )
    with pytest.raises(verifier_v32.V32EvidenceError, match="leaf budget"):
        verifier_v32._verify_manifest_tree("wide.sha256", set(), set(), {}, 0)

    graph = {
        "a.sha256": (("a" * 64, "b.sha256"),),
        "b.sha256": (("b" * 64, "a.sha256"),),
    }
    monkeypatch.setattr(verifier_v32, "_historical_manifest", graph.__getitem__)
    with pytest.raises(verifier_v32.V32EvidenceError, match="cycle"):
        verifier_v32._verify_manifest_tree("a.sha256", set(), set(), {}, 0)


def test_exact_4096_leaf_manifest_is_accepted(monkeypatch):
    entries = tuple(("a" * 64, f"leaf-{index}") for index in range(4096))
    monkeypatch.setattr(verifier_v32, "_historical_manifest", lambda relative: entries)
    monkeypatch.setattr(
        verifier_v32, "_verify_historical_path", lambda relative, digest: None
    )
    leaves = {}
    verifier_v32._verify_manifest_tree("boundary.sha256", set(), set(), leaves, 0)
    assert len(leaves) == 4096


def test_historical_manifest_rejects_path_traversal_and_symlink(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="p53-v32-path-", dir=ROOT) as directory:
        base = Path(directory)
        monkeypatch.setattr(verifier_v32, "PROJECT", base)
        manifest = base / "bad.sha256"
        manifest.write_text("" + "a" * 64 + "  ../escape\n", encoding="utf-8")
        with pytest.raises(verifier_v32.V32EvidenceError, match="unsafe"):
            verifier_v32._historical_manifest("bad.sha256")
        target = base / "target.txt"
        target.write_text("safe", encoding="utf-8")
        normal = base / "normal"
        normal.mkdir()
        normal_file = normal / "leaf.txt"
        normal_file.write_text("normal", encoding="utf-8")
        verifier_v32._verify_historical_path(
            "normal/leaf.txt", hashlib.sha256(normal_file.read_bytes()).hexdigest()
        )
        link = base / "link.txt"
        try:
            link.symlink_to(target)
        except OSError:
            pytest.skip("symlink creation is unavailable")
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._verify_historical_path(
                "link.txt", hashlib.sha256(target.read_bytes()).hexdigest()
            )
        target_dir = base / "inside-target"
        target_dir.mkdir()
        ancestor_leaf = target_dir / "leaf.txt"
        ancestor_leaf.write_text("inside", encoding="utf-8")
        linked_dir = base / "linked-dir"
        linked_dir.symlink_to(target_dir, target_is_directory=True)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._verify_historical_path(
                "linked-dir/leaf.txt",
                hashlib.sha256(ancestor_leaf.read_bytes()).hexdigest(),
            )


def test_concurrent_duplicate_is_pending_then_completed_and_hook_once():
    entered, release = threading.Event(), threading.Event()
    calls = []

    def hook():
        calls.append(1)
        entered.set()
        assert release.wait(2)

    adapter = _adapter(hook)
    request = _request()
    with ThreadPoolExecutor(max_workers=2) as pool:
        future = pool.submit(adapter.read_page, request)
        assert entered.wait(1)
        with pytest.raises(CapabilityV32DeniedError, match="reentrancy"):
            adapter.read_page(request)
        release.set()
        assert future.result().state is ReadStateV32.COMPLETED
    health = adapter.health()
    assert len(calls) == 1 and health.quota_remaining == 99
    assert (
        health.pending_entries == 0
        and health.uncertain_entries == 0
        and health.ledger_entries == 1
    )


def test_validation_exception_releases_admission_claim():
    adapter = _adapter()
    with pytest.raises(CapabilityV32ContractError):
        adapter.read_page(object())  # type: ignore[arg-type]
    assert adapter.read_page(_request()).state is ReadStateV32.COMPLETED


def test_same_correlation_payload_drift_denies_without_hook_or_quota():
    calls = []
    adapter = _adapter(lambda: calls.append(1))
    adapter.read_page(_request())
    with pytest.raises(CapabilityV32DeniedError, match="drift"):
        adapter.read_page(_request(page_size=3))
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_hook_exception_becomes_uncertain_and_never_replays_or_leaks_exception():
    calls = []

    def hook():
        calls.append(1)
        raise RuntimeError("token=super-secret-value")

    adapter = _adapter(hook)
    request = _request()
    result = adapter.read_page(request)
    assert result.state is ReadStateV32.UNCERTAIN
    assert result.failure_class is ReadFailureClassV32.HOOK_EXCEPTION
    assert "secret" not in repr(result).lower()
    assert adapter.read_page(request) == result
    assert adapter.reconcile(request) == result
    assert calls == [1] and adapter.health().quota_remaining == 99


def test_cancelled_before_hook_rolls_back_quota_and_rate_and_never_calls_hook():
    token = CancellationTokenV32()
    now = [10.0]
    clock_calls = [0]

    def clock():
        clock_calls[0] += 1
        if clock_calls[0] == 2:
            token.cancel()
        return now[0]

    calls = []
    adapter = _adapter(
        lambda: calls.append(1), quota_limit=1, rate_limit=1, clock=clock
    )
    result = adapter.read_page(_request(cancellation=token))
    assert result.state is ReadStateV32.CANCELLED_BEFORE_HOOK
    assert adapter.health().quota_remaining == 1
    assert calls == []
    assert (
        adapter.read_page(_request(correlation_id="corr-002")).state
        is ReadStateV32.COMPLETED
    )


def test_timeout_after_hook_is_uncertain_and_not_replayed():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        now[0] = 2.0

    adapter = _adapter(hook, clock=lambda: now[0])
    request = _request(timeout_ms=1000)
    result = adapter.read_page(request)
    assert result.state is ReadStateV32.UNCERTAIN
    assert result.failure_class is ReadFailureClassV32.TIMEOUT
    assert adapter.read_page(request) == result and calls == [1]


@pytest.mark.parametrize(
    ("action", "failure"),
    [("kill", ReadFailureClassV32.KILL), ("revoke", ReadFailureClassV32.REVOKED)],
)
def test_kill_and_revoke_during_hook_latch_uncertain(action, failure):
    holder = {}

    def hook():
        holder["adapter"].set_kill(True) if action == "kill" else holder[
            "adapter"
        ].revoke()

    holder["adapter"] = _adapter(hook, credential_alias="alias:catalog/account")
    result = holder["adapter"].read_page(_request())
    assert result.state is ReadStateV32.UNCERTAIN and result.failure_class is failure
    assert holder["adapter"].read_page(_request()) == result


def test_pending_expiry_becomes_uncertain_and_late_hook_cannot_commit():
    now = [0.0]
    entered, release = threading.Event(), threading.Event()

    def hook():
        entered.set()
        assert release.wait(2)

    adapter = _adapter(hook, clock=lambda: now[0], pending_ttl_seconds=1.0)
    request = _request()
    with ThreadPoolExecutor(max_workers=1) as pool:
        future = pool.submit(adapter.read_page, request)
        assert entered.wait(1)
        now[0] = 2.0
        reconciled = adapter.reconcile(request)
        assert reconciled.state is ReadStateV32.UNCERTAIN
        assert reconciled.failure_class is ReadFailureClassV32.EXPIRED_PENDING
        release.set()
        assert future.result().state is ReadStateV32.UNCERTAIN


def test_uncertain_expiry_keeps_no_replay_tombstone_and_frees_uncertain_capacity():
    now = [0.0]
    calls = []

    def hook():
        calls.append(1)
        raise RuntimeError("fixed")

    adapter = _adapter(
        hook,
        clock=lambda: now[0],
        uncertain_ttl_seconds=1.0,
        pending_capacity=1,
        uncertain_capacity=1,
    )
    first_request = _request()
    assert adapter.read_page(first_request).state is ReadStateV32.UNCERTAIN
    with pytest.raises(CapabilityV32DeniedError, match="pending/uncertain"):
        adapter.read_page(_request(correlation_id="corr-002"))
    now[0] = 2.0
    expired = adapter.reconcile(first_request)
    assert expired.state is ReadStateV32.EXPIRED_UNCERTAIN
    assert expired.failure_class is ReadFailureClassV32.UNCERTAIN_EXPIRED
    assert adapter.read_page(first_request) == expired and calls == [1]
    assert (
        adapter.read_page(_request(correlation_id="corr-002")).state
        is ReadStateV32.UNCERTAIN
    )


def test_pending_and_uncertain_capacity_configuration_is_bounded():
    with pytest.raises(CapabilityV32ContractError):
        _adapter(ledger_capacity=2, pending_capacity=2, uncertain_capacity=1)
    with pytest.raises(CapabilityV32ContractError):
        _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=2)


def test_ledger_capacity_is_bounded_and_does_not_evict_for_replay():
    adapter = _adapter(ledger_capacity=1, pending_capacity=1, uncertain_capacity=1)
    request = _request()
    assert adapter.read_page(request).state is ReadStateV32.COMPLETED
    with pytest.raises(CapabilityV32DeniedError, match="capacity"):
        adapter.read_page(_request(correlation_id="corr-002"))
    assert adapter.read_page(request).state is ReadStateV32.COMPLETED


def test_profile_bound_cursor_cannot_cross_adapter_profile():
    first_adapter = _adapter()
    first = first_adapter.read_page(_request())
    assert first.next_cursor
    other = _adapter(profile_id="profile-other")
    with pytest.raises(CapabilityV32DeniedError):
        other.read_page(
            _request(
                profile_id="profile-other",
                correlation_id="corr-002",
                cursor=first.next_cursor,
            )
        )


def test_cursor_snapshot_and_signature_tamper_fail_closed():
    adapter = _adapter()
    cursor = adapter.read_page(_request()).next_cursor
    assert cursor
    tampered = cursor[:-1] + ("0" if cursor[-1] != "0" else "1")
    with pytest.raises(CapabilityV32DeniedError):
        adapter.read_page(_request(correlation_id="corr-002", cursor=tampered))
    changed = LocalCatalogReadAdapterV32(
        _items(6),
        workspace_id=WORKSPACE,
        account_id=ACCOUNT,
        profile_id=PROFILE,
        cursor_signing_key=KEY,
        read_hook=lambda: None,
        status=CapabilityStatusV32.AVAILABLE_READ_ONLY,
        status_reason="healthy",
    )
    with pytest.raises(CapabilityV32DeniedError):
        changed.read_page(_request(correlation_id="corr-003", cursor=cursor))


def test_rate_limit_and_quota_are_reserved_once_and_truthful():
    adapter = _adapter(rate_limit=1, quota_limit=1, clock=lambda: 10.0)
    assert adapter.read_page(_request()).state is ReadStateV32.COMPLETED
    limited = adapter.read_page(_request(correlation_id="corr-002"))
    assert limited.state is ReadStateV32.RATE_LIMITED and limited.retry_after_ms == 1000
    assert adapter.read_page(_request(correlation_id="corr-002")) == limited
    assert adapter.health().quota_remaining == 0


def test_unavailable_auth_scope_disabled_degraded_and_unknown_reconcile():
    assert (
        _adapter(auth_available=False).read_page(_request()).failure_class
        is ReadFailureClassV32.AUTH
    )
    assert (
        _adapter(granted_scopes=()).read_page(_request()).failure_class
        is ReadFailureClassV32.SCOPE
    )
    assert (
        _adapter(status=CapabilityStatusV32.DISABLED, status_reason="operator_disabled")
        .read_page(_request())
        .state
        is ReadStateV32.DENIED
    )
    degraded = _adapter(
        status=CapabilityStatusV32.DEGRADED, status_reason="partial_fixture"
    )
    assert degraded.read_page(_request()).state is ReadStateV32.COMPLETED
    unknown = degraded.reconcile(_request(correlation_id="unknown-corr"))
    assert unknown.state is ReadStateV32.UNKNOWN_CORRELATION


def test_legacy_builder_preserves_current_32_declarations_and_policies_without_import():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(
        ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES"
    )
    built = build_legacy_descriptors_v32(
        declarations,
        policies,
        workspace_id=WORKSPACE,
        account_id=ACCOUNT,
        profile_id=PROFILE,
    )
    assert len(built.descriptors) == 32
    assert {item["name"]: item for item in built.declarations()} == {
        item["name"]: item for item in declarations
    }
    assert dict(built.policy_mapping()) == policies
    assert all(
        item.status is CapabilityStatusV32.DISABLED for item in built.descriptors
    )


def test_legacy_missing_policy_and_duplicate_declaration_fail_closed():
    declarations = _assignment(ROOT / "main.py", "TOOL_DECLARATIONS")
    policies = _assignment(
        ROOT / "core" / "permission_broker.py", "MODEL_TOOL_POLICIES"
    )
    policies.pop("open_app")
    with pytest.raises(CapabilityV32ContractError):
        build_legacy_descriptors_v32(
            declarations,
            policies,
            workspace_id=WORKSPACE,
            account_id=ACCOUNT,
            profile_id=PROFILE,
        )
    with pytest.raises(CapabilityV32ContractError):
        build_legacy_descriptors_v32(
            declarations + [declarations[0]],
            {**policies, "open_app": "always_confirm"},
            workspace_id=WORKSPACE,
            account_id=ACCOUNT,
            profile_id=PROFILE,
        )


def test_registry_concurrency_duplicate_kill_revoke_and_snapshot_are_safe():
    nexus = CapabilityNexusV32()
    descriptors = [
        _descriptor(capability_id=f"fixture.capability-{i}") for i in range(16)
    ]
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(nexus.register, descriptors))
    assert (
        len(
            nexus.snapshot(
                workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
            ).entries
        )
        == 16
    )
    nexus.set_kill(True)
    assert all(
        item.projection_reason == "global_kill_active"
        for item in nexus.snapshot(
            workspace_id=WORKSPACE, account_id=ACCOUNT, profile_id=PROFILE
        ).entries
    )


def test_no_live_runtime_source_references_v32():
    live = [ROOT / "main.py", ROOT / "ui.py", ROOT / "scripts" / "launch_onyx.pyw"]
    live += list((ROOT / "actions").rglob("*.py")) + list(
        (ROOT / "dashboard").rglob("*.py")
    )
    live += [
        path
        for path in (ROOT / "core").glob("*.py")
        if path.name != "capability_nexus_v32.py"
    ]
    assert all(
        "capability_nexus_v32" not in path.read_text(encoding="utf-8", errors="ignore")
        for path in live
    )


def test_phase_runner_rejects_every_arbitrary_command_surface():
    with pytest.raises(parent_v32.V32ParentError, match="phase id"):
        parent_v32._run_phase(
            [sys.executable, "-c", "print('forbidden')"],
            evidence_nonce="a" * 64,
            label="x",
            timeout=1,
        )
    with pytest.raises(parent_v32.V32ParentError, match="phase id"):
        parent_v32._phase_command("arbitrary", Path("focused.junit.xml"))


def test_parent_has_two_direct_bounded_phases_and_pure_worker_has_no_subprocess_surface():
    parent_tree = ast.parse(
        (ROOT / "scripts/verify_phase5_capability_nexus_v32.py").read_text(
            encoding="utf-8"
        )
    )
    worker_tree = ast.parse(
        (ROOT / "scripts/verify_phase5_capability_nexus_v32_worker.py").read_text(
            encoding="utf-8"
        )
    )
    popen_calls = [
        node
        for node in ast.walk(parent_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        and node.func.attr == "Popen"
    ]
    bounded_calls = [
        node
        for node in ast.walk(parent_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "_run_phase"
    ]
    assert len(popen_calls) == 1
    assert len(bounded_calls) == 2
    assert all(
        any(keyword.arg == "timeout" for keyword in node.keywords)
        for node in bounded_calls
    )
    assert not any(
        isinstance(node, (ast.Import, ast.ImportFrom))
        and "subprocess" in ast.unparse(node)
        for node in ast.walk(worker_tree)
    )
    assert not any(
        isinstance(node, ast.Call)
        and isinstance(node.func, ast.Attribute)
        and node.func.attr in {"run", "Popen"}
        and isinstance(node.func.value, ast.Name)
        and node.func.value.id == "subprocess"
        for node in ast.walk(worker_tree)
    )
    source = (ROOT / "scripts/verify_phase5_capability_nexus_v32.py").read_text(
        encoding="utf-8"
    )
    assert all(
        token in source
        for token in (
            "_KILL_ON_JOB_CLOSE",
            "CreateJobObjectW",
            "AssignProcessToJobObject",
            "TerminateJobObject",
            "QueryInformationJobObject",
            "start_new_session",
            "os.killpg",
        )
    )
    assert not (ROOT / "scripts/phase5_capability_nexus_v32_bootstrap.py").exists()
    assert "bootstrap" not in source.lower()
    assert (
        "CreateProcessW" in source
        and "_CREATE_SUSPENDED" in source
        and "ResumeThread" in source
    )


def _copy_projection_fixture(destination: Path) -> None:
    for relative in (
        verifier_v32.MUTABLE_PROJECTION_MAP,
        *verifier_v32.MUTABLE_PROJECTION_SNAPSHOTS,
        *verifier_v32.MUTABLE_PROJECTIONS,
    ):
        target = destination / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes((ROOT / relative).read_bytes())


def test_v32_mutable_projection_mapping_is_exact_and_not_authority():
    mapping = verifier_v32._projection_mapping()
    assert tuple(mapping) == verifier_v32.MUTABLE_PROJECTIONS
    assert verifier_v32._mutable_projection_evidence() == {
        "authority": "content_addressed_frozen_snapshots_not_external_projection_paths",
        "entries": [mapping[path] for path in verifier_v32.MUTABLE_PROJECTIONS],
        "mapping_sha256": hashlib.sha256(
            (ROOT / verifier_v32.MUTABLE_PROJECTION_MAP).read_bytes()
        ).hexdigest(),
        "projection_paths_are_authority": False,
    }


def test_v32_history_uses_snapshot_after_current_projection_mutation(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-projection-current-") as directory:
        project = Path(directory)
        _copy_projection_fixture(project)
        for relative in verifier_v32.MUTABLE_PROJECTIONS:
            (project / relative).write_bytes(b"external projection changed after freeze\n")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        for relative, digest in verifier_v32.MUTABLE_PROJECTION_HASHES.items():
            verifier_v32._verify_historical_path(relative, digest)


def test_v32_projection_snapshot_tamper_fails_closed(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-projection-snapshot-") as directory:
        project = Path(directory)
        _copy_projection_fixture(project)
        snapshot = project / verifier_v32.MUTABLE_PROJECTION_SNAPSHOTS[0]
        snapshot.write_bytes(snapshot.read_bytes() + b"tamper")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="snapshot hash mismatch"):
            verifier_v32._projection_mapping()


def test_v32_projection_mapping_extra_missing_and_substitution_fail_closed(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-projection-map-") as directory:
        project = Path(directory)
        _copy_projection_fixture(project)
        mapping_path = project / verifier_v32.MUTABLE_PROJECTION_MAP
        pristine = json.loads(mapping_path.read_text(encoding="utf-8"))
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        variants = []
        missing = copy.deepcopy(pristine)
        missing["entries"].pop()
        variants.append(missing)
        extra = copy.deepcopy(pristine)
        extra["entries"].append(copy.deepcopy(extra["entries"][0]))
        variants.append(extra)
        path_substitution = copy.deepcopy(pristine)
        path_substitution["entries"][0]["path"] = "docs/onyx/OTHER.md"
        variants.append(path_substitution)
        snapshot_substitution = copy.deepcopy(pristine)
        snapshot_substitution["entries"][0]["snapshot"] = snapshot_substitution[
            "entries"
        ][1]["snapshot"]
        variants.append(snapshot_substitution)
        for value in variants:
            mapping_path.write_text(
                json.dumps(value, sort_keys=True, separators=(",", ":")) + "\n",
                encoding="utf-8",
                newline="\n",
            )
            with pytest.raises(verifier_v32.V32EvidenceError):
                verifier_v32._projection_mapping()


def _replace_with_identical_symlink(path: Path, external: Path) -> None:
    payload = path.read_bytes()
    external.parent.mkdir(parents=True, exist_ok=True)
    external.write_bytes(payload)
    path.unlink()
    try:
        path.symlink_to(external)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"file symlinks are unavailable on this platform: {exc}")


def test_path_metadata_precheck_race_window_is_deterministically_disclosed(
    monkeypatch,
):
    stable_filesystem_state_metadata_precheck = verifier_v32.PATH_INTEGRITY_CONTRACT[
        "mode"
    ]
    concurrent_writer_toctou_security_boundary = verifier_v32.PATH_INTEGRITY_CONTRACT[
        "concurrent_writer_toctou_security_boundary"
    ]
    assert stable_filesystem_state_metadata_precheck == (
        "stable_filesystem_state_metadata_precheck"
    )
    assert concurrent_writer_toctou_security_boundary is False
    with tempfile.TemporaryDirectory(prefix="onyx-v32-toctou-disclosure-") as directory:
        project = Path(directory) / "project"
        project.mkdir()
        relative = "authority.txt"
        target = project / relative
        target.write_bytes(b"checked-state\n")
        replacement = project / "replacement.txt"
        replacement.write_bytes(b"concurrent-writer-state\n")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        original_precheck = verifier_v32._assert_no_reparse

        def race_after_metadata_precheck(candidate: str) -> None:
            original_precheck(candidate)
            replacement.replace(project / relative)

        monkeypatch.setattr(
            verifier_v32, "_assert_no_reparse", race_after_metadata_precheck
        )
        assert verifier_v32._read_bytes(relative) == b"concurrent-writer-state\n"


def test_v32_path_integrity_limitation_is_bound_across_authoritative_evidence():
    expected = verifier_v32.PATH_INTEGRITY_CONTRACT
    mapping = json.loads(
        (ROOT / verifier_v32.MUTABLE_PROJECTION_MAP).read_text(encoding="utf-8")
    )
    metrics = json.loads((ROOT / verifier_v32.METRICS).read_text(encoding="utf-8"))
    bundle = json.loads((ROOT / verifier_v32.BUNDLE).read_text(encoding="utf-8"))
    checkpoint = (ROOT / verifier_v32.CHECKPOINT).read_text(encoding="utf-8")
    assert mapping["path_integrity_contract"] == expected
    assert metrics["path_integrity"] == expected
    assert bundle["path_integrity_contract"] == expected
    assert "not an atomic concurrent-writer or TOCTOU security boundary" in checkpoint
    assert "metadata_precheck_not_atomic_concurrent_writer_boundary" in bundle[
        "limitations"
    ]


def _authoritative_reader(kind: str, project: Path, relative: str) -> None:
    path = project / relative
    if kind in {"source_root_manifest", "artifact_manifest", "live_manifest"}:
        verifier_v32._manifest(relative)
    elif kind == "history_manifest":
        verifier_v32._historical_manifest(relative)
    elif kind in {"bundle", "metrics", "regression_report"}:
        verifier_v32._canonical_json(relative)
    elif kind in {"focused_junit", "combined_junit", "regression_junit"}:
        verifier_v32._junit_path(path)
    elif kind == "static":
        verifier_v32._static_path(path)
    elif kind in {"checkpoint", "tamper_fixture"}:
        verifier_v32._read_text(relative)
    elif kind in {"snapshot", "generic_artifact"}:
        verifier_v32._sha(path)
    else:  # pragma: no cover - the parameter list below is closed
        raise AssertionError(kind)


@pytest.mark.parametrize(
    ("kind", "relative"),
    [
        ("source_root_manifest", verifier_v32.ROOT_MANIFEST),
        ("artifact_manifest", verifier_v32.ARTIFACT_MANIFEST),
        ("bundle", verifier_v32.BUNDLE),
        ("metrics", verifier_v32.METRICS),
        ("checkpoint", verifier_v32.CHECKPOINT),
        ("focused_junit", verifier_v32.JUNIT),
        ("combined_junit", verifier_v32.COMBINED_JUNIT),
        ("regression_junit", verifier_v32.REGRESSION_JUNIT),
        ("regression_report", verifier_v32.REGRESSION_REPORT),
        ("static", verifier_v32.STATIC),
        ("live_manifest", verifier_v32.LIVE),
        ("history_manifest", verifier_v32.V31_ROOT_MANIFEST),
        ("tamper_fixture", "history/tamper-fixture.log"),
        ("snapshot", verifier_v32.MUTABLE_PROJECTION_SNAPSHOTS[0]),
        ("generic_artifact", "artifacts/generic.bin"),
    ],
)
def test_v32_every_authoritative_evidence_class_rejects_identical_symlink(
    monkeypatch,
    kind,
    relative,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-authoritative-class-") as directory:
        base = Path(directory)
        project = base / "project"
        path = project / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b"authoritative-identical-bytes\n")
        _replace_with_identical_symlink(path, base / "external" / f"{kind}.bin")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            _authoritative_reader(kind, project, relative)


def test_v32_reviewer_mapping_symlink_repro_rejects_external_identical_map(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-reviewer-map-") as directory:
        base = Path(directory)
        project = base / "project"
        mapping = project / verifier_v32.MUTABLE_PROJECTION_MAP
        mapping.parent.mkdir(parents=True, exist_ok=True)
        mapping.write_bytes((ROOT / verifier_v32.MUTABLE_PROJECTION_MAP).read_bytes())
        external = base / "outside-workspace" / "identical-map.json"
        _replace_with_identical_symlink(mapping, external)
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._projection_mapping()


def test_v32_parent_rejects_fixed_phase_target_symlink_before_launch(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-parent-target-") as directory:
        base = Path(directory)
        project = base / "project"
        target = project / "tests" / "focused.py"
        target.parent.mkdir(parents=True)
        target.write_bytes(b"identical phase target\n")
        _replace_with_identical_symlink(target, base / "outside" / "focused.py")
        monkeypatch.setattr(parent_v32, "PROJECT", project)
        monkeypatch.setattr(parent_v32, "TESTS", "tests/focused.py")
        with pytest.raises(parent_v32.V32ParentError, match="reparse"):
            parent_v32._phase_command("focused", Path("focused.junit.xml"))


def _v32_dag_required_paths() -> set[str]:
    histories = [getattr(verifier_v32, f"V{version}_HISTORY") for version in range(1, 32)]
    lives = [getattr(verifier_v32, f"V{version}_LIVE") for version in range(1, 32)]
    return {
        verifier_v32.CORE,
        verifier_v32.TESTS,
        verifier_v32.SELF,
        verifier_v32.WORKER,
        verifier_v32.REPORTER,
        verifier_v32.WHITESPACE,
        verifier_v32.CHECKPOINT,
        verifier_v32.BUNDLE,
        verifier_v32.JUNIT,
        verifier_v32.RAW,
        verifier_v32.STATIC,
        verifier_v32.LIVE,
        verifier_v32.METRICS,
        verifier_v32.COMBINED_JUNIT,
        verifier_v32.REGRESSION_JUNIT,
        verifier_v32.REGRESSION_REPORT,
        verifier_v32.MUTABLE_PROJECTION_MAP,
        *verifier_v32.MUTABLE_PROJECTION_SNAPSHOTS,
        *lives,
        *(path for history in histories for path in history),
    }


def test_v32_dag_rejects_identical_generic_artifact_symlink_before_hash(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-dag-symlink-") as directory:
        base = Path(directory)
        project = base / "project"
        generic = "artifacts/reviewer-identical.bin"
        artifact_paths = _v32_dag_required_paths() | {generic}
        for relative in artifact_paths:
            path = project / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes((relative + "\n").encode("utf-8"))
        generic_path = project / generic
        _replace_with_identical_symlink(
            generic_path,
            base / "outside-workspace" / "reviewer-identical.bin",
        )
        artifact = project / verifier_v32.ARTIFACT_MANIFEST
        artifact.parent.mkdir(parents=True, exist_ok=True)
        artifact.write_text(
            "".join(
                f"{hashlib.sha256((project / relative).read_bytes()).hexdigest()}  {relative}\n"
                for relative in sorted(artifact_paths)
            ),
            encoding="utf-8",
            newline="\n",
        )
        root = project / verifier_v32.ROOT_MANIFEST
        root.write_text(
            f"{hashlib.sha256(artifact.read_bytes()).hexdigest()}  {verifier_v32.ARTIFACT_MANIFEST}\n",
            encoding="utf-8",
            newline="\n",
        )
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._dag()


def test_v32_authoritative_path_rejects_aliases_case_and_outside_workspace(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-path-alias-") as directory:
        base = Path(directory)
        project = base / "project"
        canonical = project / "Evidence" / "Record.json"
        canonical.parent.mkdir(parents=True)
        canonical.write_bytes(b"regular\n")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        verifier_v32._assert_no_reparse("Evidence/Record.json")
        for alias in (
            "Evidence/../Evidence/Record.json",
            "Evidence//Record.json",
            "Evidence\\Record.json",
            "evidence/Record.json",
            str((base / "outside.json").resolve()),
        ):
            with pytest.raises(verifier_v32.V32EvidenceError):
                verifier_v32._assert_no_reparse(alias)


def test_v32_authoritative_path_rejects_symlinked_ancestor_and_workspace_root(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-ancestor-link-") as directory:
        base = Path(directory)
        external = base / "external"
        (external / "nested").mkdir(parents=True)
        (external / "nested" / "evidence.json").write_bytes(b"regular\n")
        project = base / "project"
        project.mkdir()
        ancestor = project / "linked"
        try:
            ancestor.symlink_to(external / "nested", target_is_directory=True)
        except (OSError, NotImplementedError) as exc:
            pytest.skip(f"directory symlinks are unavailable on this platform: {exc}")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._read_text("linked/evidence.json")

        workspace_alias = base / "workspace-alias"
        workspace_alias.symlink_to(project, target_is_directory=True)
        monkeypatch.setattr(verifier_v32, "PROJECT", workspace_alias)
        with pytest.raises(verifier_v32.V32EvidenceError, match="workspace root"):
            verifier_v32._assert_no_reparse("linked/evidence.json")


@pytest.mark.skipif(os.name != "nt", reason="Windows junction semantics only")
def test_v32_authoritative_path_rejects_windows_junction_ancestor(
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-junction-") as directory:
        base = Path(directory)
        external = base / "junction-target"
        external.mkdir()
        (external / "evidence.json").write_bytes(b"regular\n")
        project = base / "project"
        project.mkdir()
        junction = project / "junction"
        result = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode:
            pytest.skip(f"junction creation unavailable: {result.stderr or result.stdout}")
        monkeypatch.setattr(verifier_v32, "PROJECT", project)
        with pytest.raises(verifier_v32.V32EvidenceError, match="reparse"):
            verifier_v32._read_text("junction/evidence.json")


def test_frozen_history_proof_never_spawns_a_recursive_verifier():
    v14 = verifier_v32._validate_frozen_v14_proof()
    v15 = verifier_v32._validate_frozen_v15_proof()
    v16 = verifier_v32._validate_frozen_v16_proof()
    v17 = verifier_v32._validate_frozen_v17_proof()
    v18 = verifier_v32._validate_frozen_v18_proof()
    v19 = verifier_v32._validate_frozen_v19_proof()
    v20 = verifier_v32._validate_frozen_v20_proof()
    v21 = verifier_v32._validate_frozen_v21_proof()
    v22 = verifier_v32._validate_frozen_v22_proof()
    v23 = verifier_v32._validate_frozen_v23_proof()
    v24 = verifier_v32._validate_frozen_v24_proof()
    v25 = verifier_v32._validate_frozen_v25_proof()
    v26 = verifier_v32._validate_frozen_v26_proof()
    v27 = verifier_v32._validate_frozen_v27_proof()
    v28 = verifier_v32._validate_frozen_v28_proof()
    v29 = verifier_v32._validate_frozen_v29_proof()
    v30 = verifier_v32._validate_frozen_v30_proof()
    source = (ROOT / "scripts/verify_phase5_capability_nexus_v32_worker.py").read_text(
        encoding="utf-8"
    )
    assert all(
        item["marker_contract_bound"] is True
        for item in (
            v14,
            v15,
            v16,
            v17,
            v18,
            v19,
            v20,
            v21,
            v22,
            v23,
            v24,
            v25,
            v26,
            v27,
            v28,
            v29,
            v30,
        )
    )
    assert "_run_frozen_verifiers" not in source
    assert "import subprocess" not in source


def test_frozen_v14_proof_rejects_a_historical_hash_tamper(monkeypatch):
    original = verifier_v32._sha

    def tampered(path):
        if path == ROOT / verifier_v32.V14_ARTIFACT_MANIFEST:
            return "0" * 64
        return original(path)

    monkeypatch.setattr(verifier_v32, "_sha", tampered)
    with pytest.raises(
        verifier_v32.V32EvidenceError, match="historical recursive leaf mismatch"
    ):
        verifier_v32._validate_frozen_v14_proof()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job ABI")
def test_kernel32_job_abi_is_explicit_and_pointer_safe():
    api = parent_v32._kernel32()
    assert ctypes.sizeof(parent_v32.wintypes.HANDLE) == ctypes.sizeof(ctypes.c_void_p)
    for name in (
        "CreateJobObjectW",
        "SetInformationJobObject",
        "AssignProcessToJobObject",
        "TerminateJobObject",
        "QueryInformationJobObject",
        "CloseHandle",
        "OpenProcess",
        "GetExitCodeProcess",
        "CreateFileW",
        "CreateProcessW",
        "ResumeThread",
        "WaitForSingleObject",
        "TerminateProcess",
    ):
        function = getattr(api, name)
        assert function.argtypes
        assert function.restype is not None


@pytest.mark.parametrize(
    "raw", [True, 0, -1, 1 << (ctypes.sizeof(ctypes.c_void_p) * 8)]
)
def test_invalid_or_truncated_windows_handles_fail_closed(raw):
    with pytest.raises(parent_v32.V32ParentError, match="invalid or truncated"):
        parent_v32._validated_handle(raw)


def test_old_v19_bootstrap_invocation_path_is_absent_in_v32():
    source = (ROOT / "scripts/verify_phase5_capability_nexus_v32.py").read_text(
        encoding="utf-8"
    )
    assert "BOOTSTRAP" not in source
    assert "HELLO" not in source and "READY" not in source and "GO " not in source
    assert "ONYX_P53_V32" not in source


def test_worker_rejects_arbitrary_fresh_junit_path():
    with tempfile.TemporaryDirectory(prefix="onyx-v32-arbitrary-junit-") as directory:
        path = Path(directory) / "focused.junit.xml"
        path.write_text("fixture", encoding="utf-8")
        with pytest.raises(verifier_v32.V32EvidenceError, match="nonce-scoped"):
            verifier_v32._validated_fresh_focused_junit(path)


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended process")
def test_delayed_job_assignment_cannot_execute_target_before_resume(monkeypatch):
    entered = threading.Event()
    release = threading.Event()
    original = parent_v32._WindowsJob.assign_handle
    with tempfile.TemporaryDirectory(prefix="onyx-v32-delayed-assign-") as directory:
        marker = Path(directory) / "TARGET_RAN"
        target = Path(directory) / "target.py"
        target.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('ran')\n"
        )
        monkeypatch.setattr(
            parent_v32,
            "_phase_command",
            lambda _phase, _junit: [sys.executable, str(target), str(marker)],
        )

        def delayed(job, process_handle):
            entered.set()
            assert release.wait(2)
            return original(job, process_handle)

        monkeypatch.setattr(parent_v32._WindowsJob, "assign_handle", delayed)
        with (
            parent_v32._PrivateEvidence() as evidence_nonce,
            ThreadPoolExecutor(max_workers=1) as pool,
        ):
            future = pool.submit(
                parent_v32._windows_phase,
                "focused",
                evidence_nonce=evidence_nonce,
                label="delayed assignment",
                timeout=10,
                env=None,
                stdout_mode="pipe",
            )
            assert entered.wait(2)
            time.sleep(0.1)
            assert not marker.exists()
            release.set()
            assert future.result(timeout=12).returncode == 0
        assert marker.read_text() == "ran"


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended process")
def test_assign_failure_terminates_suspended_target_before_execution(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-assign-failure-") as directory:
        marker = Path(directory) / "TARGET_RAN"
        target = Path(directory) / "target.py"
        target.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('ran')\n"
        )
        monkeypatch.setattr(
            parent_v32,
            "_phase_command",
            lambda _phase, _junit: [sys.executable, str(target), str(marker)],
        )

        def rejected(_job, _process_handle):
            raise parent_v32.V32ParentError("injected AssignProcessToJobObject failure")

        monkeypatch.setattr(parent_v32._WindowsJob, "assign_handle", rejected)
        with parent_v32._PrivateEvidence() as evidence_nonce:
            with pytest.raises(parent_v32.V32ParentError, match="injected Assign"):
                parent_v32._windows_phase(
                    "focused",
                    evidence_nonce=evidence_nonce,
                    label="assign failure",
                    timeout=5,
                    env=None,
                    stdout_mode="pipe",
                )
        assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended process")
def test_resume_failure_terminates_target_before_execution(monkeypatch):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-resume-failure-") as directory:
        marker = Path(directory) / "TARGET_RAN"
        target = Path(directory) / "target.py"
        target.write_text(
            "from pathlib import Path\nimport sys\nPath(sys.argv[1]).write_text('ran')\n"
        )
        monkeypatch.setattr(
            parent_v32,
            "_phase_command",
            lambda _phase, _junit: [sys.executable, str(target), str(marker)],
        )
        real_job = parent_v32._WindowsJob()
        real_api = real_job.api

        class ApiProxy:
            def __getattr__(self, name):
                return getattr(real_api, name)

            def ResumeThread(self, _thread):
                return parent_v32._INFINITE_RESUME_FAILURE

        real_job.api = ApiProxy()
        monkeypatch.setattr(parent_v32, "_WindowsJob", lambda: real_job)
        with parent_v32._PrivateEvidence() as evidence_nonce:
            with pytest.raises(parent_v32.V32ParentError, match="ResumeThread"):
                parent_v32._windows_phase(
                    "focused",
                    evidence_nonce=evidence_nonce,
                    label="resume failure",
                    timeout=5,
                    env=None,
                    stdout_mode="pipe",
                )
        assert not marker.exists()


@pytest.mark.skipif(sys.platform != "win32", reason="Windows suspended process")
def test_createprocess_failure_closes_precreated_resources(monkeypatch):
    real_job = parent_v32._WindowsJob()
    real_api = real_job.api

    class ApiProxy:
        def __getattr__(self, name):
            return getattr(real_api, name)

        def CreateProcessW(self, *_args):
            return False

    real_job.api = ApiProxy()
    monkeypatch.setattr(parent_v32, "_WindowsJob", lambda: real_job)
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(parent_v32.V32ParentError, match="CreateProcessW"):
            parent_v32._windows_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="create failure",
                timeout=5,
                env=None,
                stdout_mode="pipe",
            )
    assert not parent_v32._RETAINED_HANDLES


def test_closehandle_failure_retains_ownership_until_eventual_cleanup():
    parent_v32._RETAINED_HANDLES.clear()

    class Api:
        attempts = 0

        def CloseHandle(self, _handle):
            self.attempts += 1
            return self.attempts > 1

    job = object.__new__(parent_v32._WindowsJob)
    job.api = Api()
    job.handle = parent_v32.wintypes.HANDLE(321)
    with pytest.raises(parent_v32.V32ParentError, match=r"CloseHandle\(Job\)"):
        job.close()
    assert job.handle.value == 321 and 321 in parent_v32._RETAINED_HANDLES
    parent_v32._cleanup_retained_handles()
    assert not parent_v32._RETAINED_HANDLES
    job.handle = parent_v32.wintypes.HANDLE()


def test_pid_exists_closehandle_failure_propagates_and_is_retained(monkeypatch):
    parent_v32._RETAINED_HANDLES.clear()

    class Api:
        allow_close = False

        def OpenProcess(self, *_args):
            return 456

        def GetExitCodeProcess(self, _handle, pointer):
            ctypes.cast(
                pointer, ctypes.POINTER(parent_v32.wintypes.DWORD)
            ).contents.value = 0
            return True

        def CloseHandle(self, _handle):
            return self.allow_close

    api = Api()
    monkeypatch.setattr(parent_v32, "_kernel32", lambda: api)
    monkeypatch.setattr(parent_v32.os, "name", "nt")
    with pytest.raises(parent_v32.V32ParentError, match=r"CloseHandle\(Process\)"):
        parent_v32._pid_exists(123)
    assert 456 in parent_v32._RETAINED_HANDLES
    api.allow_close = True
    parent_v32._cleanup_retained_handles()
    assert not parent_v32._RETAINED_HANDLES


@pytest.mark.parametrize("outcome", ["normal", "timeout", "exception", "residual"])
def test_posix_cleanup_state_machine_covers_every_communicate_path(
    monkeypatch, outcome
):
    events = []

    class Process:
        pid = 999
        returncode = 0

        def communicate(self, timeout=None):
            if outcome == "timeout" and timeout != parent_v32.POST_KILL_DRAIN_SECONDS:
                raise subprocess.TimeoutExpired(["fixed"], timeout)
            if outcome == "exception" and timeout != parent_v32.POST_KILL_DRAIN_SECONDS:
                raise RuntimeError("communicate exploded")
            return "ok", ""

    process = Process()
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(parent_v32.os, "getpgid", lambda _pid: 999, raising=False)
    exists = iter(([True, False, False] if outcome == "residual" else [False, False]))
    monkeypatch.setattr(
        parent_v32, "_posix_group_exists", lambda _pgid: next(exists, False)
    )
    monkeypatch.setattr(
        parent_v32, "_kill_posix_group", lambda pgid: events.append(("kill", pgid))
    )
    monkeypatch.setattr(
        parent_v32, "_drain", lambda _process: events.append(("drain", 999)) or ("", "")
    )
    with parent_v32._PrivateEvidence() as evidence_nonce:
        if outcome == "normal":
            assert (
                parent_v32._posix_phase(
                    "focused",
                    evidence_nonce=evidence_nonce,
                    label="posix",
                    timeout=1,
                    env=None,
                    stdout_mode="pipe",
                ).returncode
                == 0
            )
            assert events == []
        else:
            with pytest.raises((parent_v32.V32ParentError, RuntimeError)):
                parent_v32._posix_phase(
                    "focused",
                    evidence_nonce=evidence_nonce,
                    label="posix",
                    timeout=1,
                    env=None,
                    stdout_mode="pipe",
                )
            assert events == [("kill", 999), ("drain", 999)]


def _unowned_posix_process(events, *, kill_failure=False, communicate_failure=False):
    class Process:
        pid = 7331
        returncode = None

        def poll(self):
            events.append("poll")
            return self.returncode

        def kill(self):
            events.append("kill")
            if kill_failure:
                raise RuntimeError("direct kill exploded")
            self.returncode = -9

        def communicate(self, timeout=None):
            events.append(("communicate", timeout))
            if communicate_failure:
                raise UnicodeError("output decode exploded")
            if self.returncode is None:
                self.returncode = 0
            return "PASS", ""

    return Process()


def test_getpgid_failure_after_spawn_kills_reaps_and_never_accepts_pass(
    monkeypatch, capsys
):
    events = []
    process = _unowned_posix_process(events)
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("getpgid exploded")),
        raising=False,
    )
    monkeypatch.setattr(parent_v32, "_pid_exists", lambda _pid: False)
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(RuntimeError, match="getpgid exploded"):
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="reviewer reproducer",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    assert "kill" in events
    assert (
        sum(event[0] == "communicate" for event in events if isinstance(event, tuple))
        >= 1
    )
    assert process.poll() is not None
    assert "PASS" not in capsys.readouterr().out


def test_unexpected_getpgid_cleans_only_direct_child_and_fails_closed(monkeypatch):
    events = []
    process = _unowned_posix_process(events)
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os, "getpgid", lambda _pid: process.pid + 1, raising=False
    )
    monkeypatch.setattr(parent_v32, "_pid_exists", lambda _pid: False)
    monkeypatch.setattr(
        parent_v32, "_kill_posix_group", lambda _pgid: pytest.fail("wrong group killed")
    )
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(parent_v32.V32ParentError, match="ownership mismatch"):
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="wrong group",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    assert "kill" in events and any(
        isinstance(event, tuple) and event[0] == "communicate" for event in events
    )


def test_getpgid_failure_preserves_original_when_direct_kill_also_fails(monkeypatch):
    events = []
    process = _unowned_posix_process(events, kill_failure=True)
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("getpgid original")),
        raising=False,
    )
    monkeypatch.setattr(parent_v32, "_pid_exists", lambda _pid: False)
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(RuntimeError, match="getpgid original") as caught:
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="kill failure",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    assert "kill" in events
    assert any(
        "direct kill exploded" in note
        for note in getattr(caught.value, "__notes__", ())
    )


def test_getpgid_failure_preserves_original_when_direct_communicate_fails(monkeypatch):
    events = []
    process = _unowned_posix_process(events, communicate_failure=True)
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("getpgid original")),
        raising=False,
    )
    monkeypatch.setattr(parent_v32, "_pid_exists", lambda _pid: False)
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(RuntimeError, match="getpgid original") as caught:
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="communicate failure",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    assert any(
        isinstance(event, tuple) and event[0] == "communicate" for event in events
    )
    assert any(
        "output decode exploded" in note
        for note in getattr(caught.value, "__notes__", ())
    )


def test_successful_normal_posix_phase_retains_group_owned_path(monkeypatch):
    events = []
    process = _unowned_posix_process(events)
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os, "getpgid", lambda _pid: process.pid, raising=False
    )
    monkeypatch.setattr(parent_v32, "_posix_group_exists", lambda _pgid: False)
    with parent_v32._PrivateEvidence() as evidence_nonce:
        result = parent_v32._posix_phase(
            "focused",
            evidence_nonce=evidence_nonce,
            label="normal posix",
            timeout=1,
            env=None,
            stdout_mode="pipe",
        )
    assert result.returncode == 0 and result.stdout == "PASS"
    assert "kill" not in events


def test_reviewer_multifault_cleanup_preserves_every_flat_record(monkeypatch, capsys):
    class Process:
        pid = 7441
        returncode = None

        def poll(self):
            raise RuntimeError("poll exploded")

        def kill(self):
            raise OSError("kill exploded")

        def communicate(self, timeout=None):
            raise UnicodeError("decode exploded")

    process = Process()
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *args, **kwargs: process)
    monkeypatch.setattr(
        parent_v32.os,
        "getpgid",
        lambda _pid: (_ for _ in ()).throw(RuntimeError("getpgid exploded")),
        raising=False,
    )
    monkeypatch.setattr(
        parent_v32,
        "_pid_exists",
        lambda _pid: (_ for _ in ()).throw(PermissionError("PID proof exploded")),
    )
    with parent_v32._PrivateEvidence() as evidence_nonce:
        with pytest.raises(RuntimeError, match="getpgid exploded") as caught:
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=evidence_nonce,
                label="reviewer multifault",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    records = caught.value.cleanup_failures
    assert [item["operation"] for item in records] == [
        "direct.poll.initial",
        "direct.kill",
        "direct.communicate",
        "direct.poll.reap",
        "direct.pid.proof",
    ]
    assert [item["message"] for item in records] == [
        "poll exploded",
        "kill exploded",
        "decode exploded",
        "poll exploded",
        "PID proof exploded",
    ]
    assert len(caught.value.__notes__) == 5
    assert all(
        message in "\n".join(caught.value.__notes__)
        for message in (
            "poll exploded",
            "kill exploded",
            "decode exploded",
            "PID proof exploded",
        )
    )
    assert "PASS" not in capsys.readouterr().out


def test_cleanup_collector_order_and_exact_deduplication():
    failures = parent_v32._CleanupFailures()
    failures.add("second", RuntimeError("same"))
    failures.add("first", ValueError("different"))
    failures.add("second", RuntimeError("same"))
    failures.add("second", ValueError("same"))
    assert [
        (item.operation, item.exception_type, item.message) for item in failures.records
    ] == [
        ("second", "builtins.RuntimeError", "same"),
        ("first", "builtins.ValueError", "different"),
        ("second", "builtins.ValueError", "same"),
    ]


def test_cleanup_collector_without_primary_raises_one_payload_error():
    failures = parent_v32._CleanupFailures()
    failures.add("group.kill", OSError("kill failed"))
    failures.add("group.drain", UnicodeError("decode failed"))
    combined = failures.finish(None)
    assert isinstance(combined, parent_v32.V32ParentError)
    assert str(combined) == "cleanup failed closed"
    assert [item["operation"] for item in combined.cleanup_failures] == [
        "group.kill",
        "group.drain",
    ]
    assert len(combined.__notes__) == 2


def test_cleanup_collector_single_fault_returns_wrapper_snapshot():
    primary = RuntimeError("primary")
    failures = parent_v32._CleanupFailures()
    failures.add("direct.kill", OSError("single cleanup"))
    combined = failures.finish(primary)
    assert type(combined) is parent_v32.V32ParentError
    assert combined is not primary and combined.__cause__ is primary
    assert combined.primary_failure == {
        "operation": "primary",
        "type": "builtins.RuntimeError",
        "message": "primary",
    }
    assert combined.cleanup_failures == (
        {
            "operation": "direct.kill",
            "type": "builtins.OSError",
            "message": "single cleanup",
        },
    )
    assert combined.__notes__ == [
        "cleanup_failure operation=direct.kill type=builtins.OSError message=single cleanup"
    ]


def test_cleanup_flattens_exception_group_depth_first():
    failures = parent_v32._CleanupFailures()
    failures.add(
        "group.drain",
        ExceptionGroup("wrapper", [OSError("io"), UnicodeError("decode")]),
    )
    assert [(r.operation, r.exception_type, r.message) for r in failures.records] == [
        ("group.drain", "builtins.OSError", "io"),
        ("group.drain", "builtins.UnicodeError", "decode"),
    ]


def test_cleanup_recollects_existing_payload_without_wrapper_loss():
    prior = RuntimeError("wrapper")
    prior.cleanup_failures = (
        {"operation": "direct.kill", "type": "builtins.OSError", "message": "kill"},
    )
    failures = parent_v32._CleanupFailures()
    failures.add("outer", prior)
    assert [(r.operation, r.exception_type, r.message) for r in failures.records] == [
        ("direct.kill", "builtins.OSError", "kill")
    ]


def test_cleanup_nested_groups_causes_context_and_duplicates_are_flat():
    cause = OSError("cause")
    leaf = RuntimeError("leaf")
    leaf.__cause__ = cause
    context = ValueError("context")
    contextual = RuntimeError("outer")
    contextual.__context__ = context
    contextual.__suppress_context__ = False
    group = ExceptionGroup(
        "top", [ExceptionGroup("nested", [leaf]), contextual, OSError("cause")]
    )
    failures = parent_v32._CleanupFailures()
    failures.add("op", group)
    assert [(r.exception_type, r.message) for r in failures.records] == [
        ("builtins.OSError", "cause"),
        ("builtins.ValueError", "context"),
    ]


def test_cleanup_cycle_is_explicit_and_finite():
    failure = RuntimeError("cycle")
    failure.__cause__ = failure
    failures = parent_v32._CleanupFailures()
    failures.add("op", failure)
    assert failures.records == [
        parent_v32.CleanupFailureRecord(
            "collector.cycle", "onyx.cleanup.ExceptionCycle", "op"
        )
    ]


@pytest.mark.parametrize(
    "payload", ["bad", ({"operation": 1, "type": "x", "message": "y"},)]
)
def test_cleanup_malformed_payload_is_never_trusted(payload):
    failure = RuntimeError("wrapper")
    failure.cleanup_failures = payload
    failures = parent_v32._CleanupFailures()
    failures.add("op", failure)
    assert failures.records[0].operation == "op.payload"
    assert failures.records[0].exception_type == "onyx.cleanup.MalformedPayload"


def test_cleanup_depth_and_node_overflow_fail_closed():
    root = RuntimeError("0")
    current = root
    for index in range(25):
        child = RuntimeError(str(index + 1))
        current.__cause__ = child
        current = child
    failures = parent_v32._CleanupFailures()
    failures.add("deep", root)
    assert failures.overflowed
    combined = failures.finish(None)
    assert isinstance(combined, parent_v32.V32ParentError)
    assert combined.cleanup_failures == ()
    assert combined.cleanup_overflow["operation"] == "collector.overflow"


def test_cleanup_flat_payload_returns_complete_wrapper_and_blocks_output(capsys):
    failures = parent_v32._CleanupFailures()
    failures.add("op", ExceptionGroup("wrapper", [OSError("one"), UnicodeError("two")]))
    primary = RuntimeError("primary")
    combined = failures.finish(primary)
    assert type(combined) is parent_v32.V32ParentError
    assert combined is not primary and combined.__cause__ is primary
    assert len(combined.cleanup_failures) == len(combined.__notes__) == 2
    assert "PASS" not in capsys.readouterr().out


def test_cleanup_shared_dag_is_not_a_cycle_and_dedupes_exactly():
    leaf = OSError("shared")
    subgroup = ExceptionGroup("sub", [leaf])
    group = ExceptionGroup("top", [leaf, subgroup, subgroup])
    failures = parent_v32._CleanupFailures()
    failures.add("op", group)
    assert failures.records == [
        parent_v32.CleanupFailureRecord("op", "builtins.OSError", "shared")
    ]


@pytest.mark.parametrize("payload", [(), [], None, {}])
def test_cleanup_empty_payload_never_silently_consumes_wrapper(payload):
    failure = RuntimeError("wrapper leaf")
    failure.cleanup_failures = payload
    failures = parent_v32._CleanupFailures()
    failures.add("proof", failure)
    assert failures.records
    assert any(
        record.message
        in {
            "wrapper leaf",
            "cleanup_failures payload is empty",
            "cleanup_failures must be a list or tuple",
        }
        for record in failures.records
    )


def test_normal_posix_empty_cleanup_payload_proof_rejects_pass(monkeypatch, capsys):
    class Process:
        pid = 8111
        returncode = 0

        def communicate(self, timeout=None):
            return "PASS", ""

    proof = RuntimeError("proof wrapper")
    proof.cleanup_failures = ()
    monkeypatch.setattr(parent_v32.subprocess, "Popen", lambda *a, **k: Process())
    monkeypatch.setattr(parent_v32.os, "getpgid", lambda pid: pid, raising=False)
    monkeypatch.setattr(
        parent_v32, "_posix_group_exists", lambda _pgid: (_ for _ in ()).throw(proof)
    )
    monkeypatch.setattr(parent_v32, "_kill_posix_group", lambda _pgid: None)
    monkeypatch.setattr(parent_v32, "_drain", lambda _process: ("", ""))
    monkeypatch.setattr(
        parent_v32, "_wait_posix_group_empty", lambda _pgid, _label: None
    )
    with parent_v32._PrivateEvidence() as nonce:
        with pytest.raises(parent_v32.V32ParentError):
            parent_v32._posix_phase(
                "focused",
                evidence_nonce=nonce,
                label="integrity",
                timeout=1,
                env=None,
                stdout_mode="pipe",
            )
    assert "PASS" not in capsys.readouterr().out


def test_cleanup_real_cycle_only_when_currently_active():
    first = RuntimeError("first")
    second = RuntimeError("second")
    first.__cause__ = second
    second.__cause__ = first
    failures = parent_v32._CleanupFailures()
    failures.add("cycle", first)
    assert any(record.operation == "collector.cycle" for record in failures.records)


def test_cleanup_payload_subclass_is_rejected_without_len_or_iteration():
    class CountingList(list):
        len_calls = 0
        iter_calls = 0

        def __len__(self):
            type(self).len_calls += 1
            return super().__len__()

        def __iter__(self):
            type(self).iter_calls += 1
            return super().__iter__()

    failure = RuntimeError("wrapper")
    failure.cleanup_failures = CountingList([{"operation": "x", "type": "y", "message": "z"}] * 10_000)
    failures = parent_v32._CleanupFailures()
    failures.add("proof", failure)
    assert CountingList.len_calls == CountingList.iter_calls == 0
    assert failures.records == [
        parent_v32.CleanupFailureRecord(
            "proof.payload",
            "onyx.cleanup.MalformedPayload",
            "cleanup_failures must be a list or tuple",
        )
    ]
    assert not failures.overflowed


@pytest.mark.parametrize("factory", [list, tuple])
def test_cleanup_exact_large_payload_rejects_from_len_before_item_processing(factory):
    class Bomb(dict):
        def __getattribute__(self, name):
            if name not in {"__class__"}:
                raise AssertionError("payload item was inspected")
            return super().__getattribute__(name)

    failure = RuntimeError("wrapper")
    failure.cleanup_failures = factory(Bomb() for _ in range(10_000))
    failures = parent_v32._CleanupFailures()
    failures.add("proof", failure)
    assert failures.overflowed
    assert failures.records == []
    combined = failures.finish(None)
    assert combined.cleanup_failures == ()
    assert combined.cleanup_overflow["message"] == "cleanup_failures payload item budget exceeded"


def test_cleanup_generator_and_custom_iterable_are_rejected_without_iteration():
    visits = 0

    def generator():
        nonlocal visits
        visits += 1
        yield {"operation": "x", "type": "y", "message": "z"}

    for payload in (generator(), map(lambda value: value, ())):
        failure = RuntimeError("wrapper")
        failure.cleanup_failures = payload
        failures = parent_v32._CleanupFailures()
        failures.add("proof", failure)
        assert failures.records[0].exception_type == "onyx.cleanup.MalformedPayload"
        assert not failures.overflowed
    assert visits == 0


def test_cleanup_duplicate_payload_bomb_is_bounded_and_dedupes_before_capacity():
    item = {"operation": "same", "type": "builtins.OSError", "message": "same"}
    failure = RuntimeError("wrapper")
    failure.cleanup_failures = [item] * parent_v32._CleanupFailures.MAX_PAYLOAD_ITEMS
    failures = parent_v32._CleanupFailures()
    failures.add("proof", failure)
    assert failures.records == [
        parent_v32.CleanupFailureRecord("same", "builtins.OSError", "same")
    ]
    assert not failures.overflowed


def test_cleanup_record_capacity_dedup_boundary_and_129th_unique_fail_closed():
    failures = parent_v32._CleanupFailures()
    for index in range(parent_v32._CleanupFailures.MAX_RECORDS):
        failure = RuntimeError("wrapper")
        failure.cleanup_failures = (
            {"operation": f"op-{index}", "type": "builtins.OSError", "message": "x"},
        )
        failures.add("proof", failure)
    assert len(failures.records) == 128
    assert not failures.overflowed

    duplicate = RuntimeError("wrapper")
    duplicate.cleanup_failures = (
        {"operation": "op-0", "type": "builtins.OSError", "message": "x"},
    )
    failures.add("proof", duplicate)
    assert len(failures.records) == 128
    assert not failures.overflowed

    unique = RuntimeError("wrapper")
    unique.cleanup_failures = (
        {"operation": "op-128", "type": "builtins.OSError", "message": "x"},
    )
    failures.add("proof", unique)
    assert len(failures.records) == 128
    assert failures.overflowed
    combined = failures.finish(None)
    assert len(combined.cleanup_failures) == 128
    assert combined.cleanup_overflow["operation"] == "collector.overflow"
    notes = tuple(combined.__notes__)
    assert len(notes) == 129


def test_cleanup_overflow_short_circuits_all_future_traversal():
    failures = parent_v32._CleanupFailures()
    oversized = RuntimeError("wrapper")
    oversized.cleanup_failures = [None] * 10_000
    failures.add("proof", oversized)
    assert failures.overflowed and failures.records == []

    class BombError(RuntimeError):
        def __str__(self):
            raise AssertionError("overflowed collector traversed again")

    failures.add("later", BombError())
    assert failures.records == []


def test_cleanup_failures_getter_bomb_is_captured_with_original_leaf():
    class Unprintable(RuntimeError):
        def __str__(self):
            raise AssertionError("accessor error str executed")

        def __repr__(self):
            raise AssertionError("accessor error repr executed")

    class GetterBomb(RuntimeError):
        @property
        def cleanup_failures(self):
            raise Unprintable()

    failure = GetterBomb("original wrapper")
    collector = parent_v32._CleanupFailures()
    collector.add("proof", failure)
    assert any(
        record.operation == "proof" and record.message == "original wrapper"
        for record in collector.records
    )
    assert any(
        record.operation == "collector.cleanup_failures_access"
        and record.message.startswith("<message-unavailable:")
        for record in collector.records
    )
    assert any(record.operation == "collector.message_access" for record in collector.records)
    assert collector.finish(None) is not None


def test_cleanup_failures_attribute_error_getter_is_not_misread_as_absent():
    class GetterBomb(RuntimeError):
        @property
        def cleanup_failures(self):
            raise AttributeError("declared getter failed")

    collector = parent_v32._CleanupFailures()
    collector.add("proof", GetterBomb("wrapper"))
    assert any(record.operation == "collector.cleanup_failures_access" for record in collector.records)
    assert any(record.operation == "proof" for record in collector.records)


def test_cleanup_evil_str_fields_reject_before_truth_len_hash_or_equality():
    class EvilStr(str):
        calls = 0

        def _bomb(self, *_args):
            type(self).calls += 1
            raise AssertionError("EvilStr behavior executed")

        __bool__ = _bomb
        __len__ = _bomb
        __hash__ = _bomb
        __eq__ = _bomb
        __str__ = _bomb

    for field in ("operation", "type", "message"):
        item = {"operation": "safe", "type": "builtins.OSError", "message": "safe"}
        item[field] = EvilStr("hostile")
        failure = RuntimeError("wrapper")
        failure.cleanup_failures = (item,)
        collector = parent_v32._CleanupFailures()
        collector.add("proof", failure)
        assert collector.records == [
            parent_v32.CleanupFailureRecord(
                "proof.payload",
                "onyx.cleanup.MalformedPayload",
                "cleanup_failures record schema is invalid",
            )
        ]
    assert EvilStr.calls == 0


def test_cleanup_custom_mapping_item_is_rejected_without_invoking_mapping_code():
    class MappingBomb(dict):
        calls = 0

        def _bomb(self, *_args, **_kwargs):
            type(self).calls += 1
            raise AssertionError("mapping code executed")

        __iter__ = _bomb
        __len__ = _bomb
        __getitem__ = _bomb
        get = _bomb
        keys = _bomb

    failure = RuntimeError("wrapper")
    failure.cleanup_failures = (MappingBomb(),)
    collector = parent_v32._CleanupFailures()
    collector.add("proof", failure)
    assert MappingBomb.calls == 0
    assert collector.records[0].exception_type == "onyx.cleanup.MalformedPayload"


def test_cleanup_hostile_str_and_repr_use_pointer_free_fallback_and_render_record():
    class RenderBomb(RuntimeError):
        def __str__(self):
            raise RuntimeError("str failed")

        def __repr__(self):
            raise RuntimeError("repr failed")

    collector = parent_v32._CleanupFailures()
    collector.add("proof", RenderBomb())
    assert collector.records[0].operation == "proof"
    assert collector.records[0].message.startswith("<message-unavailable:")
    assert "0x" not in collector.records[0].message
    assert any(record.operation == "collector.message_access" for record in collector.records)


@pytest.mark.parametrize("field", ["__cause__", "__context__", "__suppress_context__"])
def test_cleanup_hostile_chain_accessors_are_captured_without_escape(field):
    class Unprintable(RuntimeError):
        def __str__(self):
            raise AssertionError("access error render")

        def __repr__(self):
            raise AssertionError("access error repr")

    class ChainBomb(RuntimeError):
        def __getattribute__(self, name):
            if name == field:
                raise Unprintable()
            return super().__getattribute__(name)

    failure = ChainBomb("wrapper")
    if field == "__suppress_context__":
        BaseException.__setattr__(failure, "__context__", RuntimeError("context"))
    collector = parent_v32._CleanupFailures()
    collector.add("proof", failure)
    canonical = field.strip("_")
    assert any(record.operation == f"collector.{canonical}_access" for record in collector.records)
    assert any(record.operation == "proof" for record in collector.records)
    assert collector.finish(None) is not None


def test_cleanup_hostile_exception_group_children_accessor_is_captured():
    class GroupBomb(ExceptionGroup):
        def __getattribute__(self, name):
            if name == "exceptions":
                raise RuntimeError("children unavailable")
            return super().__getattribute__(name)

    collector = parent_v32._CleanupFailures()
    collector.add("proof", GroupBomb("group", [OSError("leaf")]))
    assert any(record.operation == "collector.exceptions_access" for record in collector.records)
    assert any(record.operation == "proof" for record in collector.records)


def test_cleanup_safe_type_name_bypasses_hostile_metaclass_metadata():
    class HostileMeta(type):
        def __getattribute__(cls, name):
            if name in {"__module__", "__qualname__", "__name__"}:
                raise AssertionError("hostile metaclass metadata executed")
            return super().__getattribute__(name)

    class MetaError(RuntimeError, metaclass=HostileMeta):
        pass

    collector = parent_v32._CleanupFailures()
    collector.add("proof", MetaError("safe"))
    assert collector.records[0].exception_type.endswith(".MetaError")


def test_v32_primary_is_record_and_cause_but_never_returned_or_attached():
    primary = RuntimeError("primary")
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(primary)

    assert type(combined) is parent_v32.V32ParentError
    assert combined is not primary and combined.__cause__ is primary
    assert combined.primary_failure == {
        "operation": "primary",
        "type": "builtins.RuntimeError",
        "message": "primary",
    }
    assert combined.cleanup_failures == (
        {
            "operation": "direct.kill",
            "type": "builtins.OSError",
            "message": "kill failed",
        },
    )
    assert combined.attachment_failures == ()
    assert not hasattr(primary, "cleanup_failures")
    assert not hasattr(primary, "__notes__")


def test_v32_primary_attachment_surfaces_are_never_invoked():
    class Primary(RuntimeError):
        calls = 0

        def __setattr__(self, name, value):
            if name in {"cleanup_failures", "cleanup_overflow", "__notes__"}:
                type(self).calls += 1
                raise AssertionError("primary attachment attempted")
            return super().__setattr__(name, value)

        def add_note(self, _note):
            type(self).calls += 1
            raise AssertionError("primary note attempted")

    primary = Primary("primary")
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    collector._overflow("forced overflow")
    combined = collector.finish(primary)

    assert type(combined) is parent_v32.V32ParentError
    assert Primary.calls == 0
    assert combined.attachment_failures == ()
    assert combined.cleanup_overflow["message"] == "forced overflow"


def test_v32_one_shot_cleanup_failures_descriptor_cannot_create_toctou():
    class OneShotPrimary(RuntimeError):
        reads = 0

        @property
        def cleanup_failures(self):
            type(self).reads += 1
            if type(self).reads == 1:
                return ({"operation": "spoof", "type": "spoof", "message": "spoof"},)
            raise RuntimeError("payload vanished")

    primary = OneShotPrimary("primary")
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(primary)

    assert combined is not primary and OneShotPrimary.reads == 0
    assert combined.cleanup_failures[0]["message"] == "kill failed"
    assert combined.cleanup_failures[0]["message"] == "kill failed"


def test_v32_one_shot_notes_accessor_cannot_create_toctou():
    class OneShotNotes(RuntimeError):
        reads = 0

        def __getattribute__(self, name):
            if name == "__notes__":
                type(self).reads += 1
                if type(self).reads == 1:
                    return []
                raise RuntimeError("notes vanished")
            return super().__getattribute__(name)

    primary = OneShotNotes("primary")
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(primary)

    assert combined is not primary and OneShotNotes.reads == 0
    assert combined.cleanup_failures == combined.cleanup_failures


def test_v32_unprintable_primary_record_uses_pointer_free_fallback():
    class Primary(RuntimeError):
        def __str__(self):
            raise AssertionError("str unavailable")

        def __repr__(self):
            raise AssertionError("repr unavailable")

    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(Primary())
    assert combined.primary_failure["message"].startswith("<message-unavailable:")
    assert "0x" not in combined.primary_failure["message"]


def test_v32_no_primary_builds_wrapper_without_attachment_failure():
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(None)

    assert type(combined) is parent_v32.V32ParentError
    assert combined.__cause__ is None
    assert combined.primary_failure is None
    assert combined.attachment_failures == ()
    assert combined.cleanup_failures[0]["operation"] == "direct.kill"


def test_v32_snapshot_rejects_ordinary_assignment_and_delete():
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(RuntimeError("primary"))

    with pytest.raises(TypeError):
        combined.cleanup_failures[0]["message"] = "ordinary-write"
    with pytest.raises(TypeError):
        combined.primary_failure["message"] = "ordinary-write"
    with pytest.raises(AttributeError):
        combined.cleanup_failures = ()
    with pytest.raises(AttributeError):
        combined._v32_cleanup_failures = ()
    with pytest.raises(AttributeError):
        del combined.cleanup_failures
    with pytest.raises(AttributeError):
        del combined._v32_cleanup_failures
    assert type(combined.cleanup_failures) is tuple
    assert type(combined.attachment_failures) is tuple
    assert combined.cleanup_failures[0] == {
        "operation": "direct.kill",
        "type": "builtins.OSError",
        "message": "kill failed",
    }


def test_v32_str_subclass_attribute_names_reject_without_running_subclass_code():
    class S(str):
        calls = 0

        def _bomb(self, *_args, **_kwargs):
            type(self).calls += 1
            raise AssertionError("str subclass code executed")

        __eq__ = _bomb
        __hash__ = _bomb
        __str__ = _bomb
        encode = _bomb
        __getitem__ = _bomb

    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(None)
    before = combined.cleanup_failures
    hostile_name = S("_v32_cleanup_failures")

    with pytest.raises(TypeError, match="exact built-in str"):
        setattr(combined, hostile_name, ())
    with pytest.raises(TypeError, match="exact built-in str"):
        delattr(combined, hostile_name)

    assert S.calls == 0
    assert combined.cleanup_failures is before


def test_v32_non_string_and_all_exact_string_names_reject_after_construction():
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    combined = collector.finish(None)

    for name in (None, 1, object()):
        with pytest.raises(TypeError, match="exact built-in str"):
            combined.__setattr__(name, "value")
        with pytest.raises(TypeError, match="exact built-in str"):
            combined.__delattr__(name)
    for name in (
        "cleanup_failures",
        "_v32_cleanup_failures",
        "ordinary_non_evidence_field",
    ):
        with pytest.raises(AttributeError, match="read-only after construction"):
            combined.__setattr__(name, "value")
        with pytest.raises(AttributeError, match="read-only after construction"):
            combined.__delattr__(name)
    assert combined.cleanup_failures[0]["message"] == "kill failed"


def test_v32_reflection_is_documented_outside_runtime_object_contract():
    collector = parent_v32._CleanupFailures()
    collector.add("direct.kill", OSError("kill failed"))
    disposable = collector.finish(None)
    object.__setattr__(disposable, "_v32_cleanup_failures", ())
    assert disposable.cleanup_failures == ()
    assert parent_v32.V32ParentError.__doc__ is not None
    assert "not a same-process reflection security boundary" in parent_v32.V32ParentError.__doc__


def test_v32_current_candidate_contains_no_same_process_overclaim():
    paths = [
        ROOT / "core/capability_nexus_v32.py",
        ROOT / "tests/test_capability_nexus_v32.py",
        ROOT / "scripts/verify_phase5_capability_nexus_v32.py",
        ROOT / "scripts/verify_phase5_capability_nexus_v32_worker.py",
        ROOT / "scripts/phase5_capability_nexus_v32_subtest_reporter.py",
        ROOT / "scripts/check_phase5_capability_nexus_v32_whitespace.py",
    ]
    evidence = ROOT / "docs/onyx/checkpoints/phase5-capability-nexus-v32"
    paths.extend(
        path
        for path in (
            evidence / "PHASE5_3_CAPABILITY_NEXUS_V32_CHECKPOINT.md",
            evidence / "phase5-capability-nexus-v32.metrics.json",
            evidence / "phase5-capability-nexus-v32.bundle.json",
        )
        if path.is_file()
    )
    forbidden = (
        "im" + "mutable",
        "tamper" + "-proof",
        "cannot be " + "spoofed",
        "cannot be " + "mutated",
    )
    for path in paths:
        source = path.read_text(encoding="utf-8").casefold()
        assert not any(term in source for term in forbidden), path


def test_v32_manifests_supply_durable_integrity_not_runtime_wrapper():
    source = (ROOT / "scripts/verify_phase5_capability_nexus_v32_worker.py").read_text(
        encoding="utf-8"
    )
    assert "api_read_only_snapshot" in source
    assert "not_a_same_process_reflection_security_boundary" in source
    assert "hash_bound_manifests_supply_persisted_audit_integrity" in source
    assert verifier_v32.V31_ROOT_MANIFEST in verifier_v32.HISTORICAL_ROOTS
    root_manifest = ROOT / verifier_v32.V31_ROOT_MANIFEST
    digest, relative = root_manifest.read_text(encoding="ascii").strip().split("  ")
    assert hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() == digest


@pytest.mark.skipif(sys.platform != "win32", reason="Windows Job tree ownership")
@pytest.mark.parametrize("hang_phase", ["focused", "worker"])
@pytest.mark.parametrize("stdout_mode", ["devnull", "pipe"])
def test_hanging_child_and_grandchild_tree_is_killed_without_retry_or_marker(
    hang_phase,
    stdout_mode,
    capsys,
    monkeypatch,
):
    with tempfile.TemporaryDirectory(prefix="onyx-v32-process-tree-") as directory:
        pid_file = Path(directory) / "pids.txt"
        script = Path(directory) / "tree.py"
        script.write_text(
            "import os, subprocess, sys, time\n"
            "from pathlib import Path\n"
            "child=subprocess.Popen([sys.executable,'-c','import time; time.sleep(60)'])\n"
            f"Path(r'{pid_file}').write_text(f'{{os.getpid()}}\\n{{child.pid}}\\n',encoding='utf-8')\n"
            "print('tree-ready',flush=True)\n"
            "time.sleep(60)\n",
            encoding="utf-8",
        )
        monkeypatch.setattr(
            parent_v32,
            "_phase_command",
            lambda _phase, _junit: [sys.executable, str(script)],
        )
        started = time.monotonic()
        with parent_v32._PrivateEvidence() as evidence_nonce:
            if hang_phase == "worker":
                (
                    parent_v32.PRIVATE_BASE / evidence_nonce / "focused.junit.xml"
                ).write_text("fixture")
            with pytest.raises(parent_v32.V32ParentError, match="timed out"):
                parent_v32._run_phase(
                    hang_phase,
                    evidence_nonce=evidence_nonce,
                    label="tree fixture",
                    timeout=3,
                    stdout_mode=stdout_mode,
                )
        assert time.monotonic() - started < 7
        assert pid_file.is_file()
        direct_pid, grandchild_pid = [
            int(value) for value in pid_file.read_text(encoding="utf-8").splitlines()
        ]
        deadline = time.monotonic() + 2
        while (
            parent_v32._pid_exists(direct_pid) or parent_v32._pid_exists(grandchild_pid)
        ) and time.monotonic() < deadline:
            time.sleep(0.02)
        assert not parent_v32._pid_exists(direct_pid)
        assert not parent_v32._pid_exists(grandchild_pid)
        assert parent_v32.MARKER not in capsys.readouterr().out


@pytest.mark.parametrize(
    "tamper",
    [
        "base_count",
        "base_identity",
        "base_outcome",
        "base_duplicate",
        "subtest_count",
        "subtest_identity",
        "subtest_outcome",
        "subtest_duplicate",
        "subtest_parent",
        "subtest_context",
        "subtest_ordinal",
    ],
)
def test_regression_report_semantic_tamper_fails_closed(tamper):
    report = copy.deepcopy(verifier_v32._regression_report())
    if tamper == "base_count":
        report["base_tests"].pop()
    elif tamper == "base_identity":
        report["base_tests"][0]["identity"] = "0" * 64
    elif tamper == "base_outcome":
        report["base_tests"][0]["outcome"] = "failed"
    elif tamper == "base_duplicate":
        report["base_tests"][-1] = copy.deepcopy(report["base_tests"][0])
    elif tamper == "subtest_count":
        report["subtests"].pop()
    elif tamper == "subtest_identity":
        report["subtests"][0]["identity"] = "0" * 64
    elif tamper == "subtest_outcome":
        report["subtests"][0]["outcome"] = "failed"
    elif tamper == "subtest_duplicate":
        report["subtests"][-1] = copy.deepcopy(report["subtests"][0])
    elif tamper == "subtest_parent":
        report["subtests"][0]["parent_nodeid"] = "tests/missing.py::test_missing"
    elif tamper == "subtest_context":
        report["subtests"][0]["context"]["parameters"]["tampered"] = "yes"
    else:
        report["subtests"][0]["ordinal"] += 1
    with pytest.raises(verifier_v32.V32EvidenceError):
        verifier_v32._validate_regression_report(report)


@pytest.mark.parametrize(
    "tamper",
    [
        "suite_tests",
        "suite_failures",
        "missing_case",
        "extra_case",
        "case_identity",
        "case_outcome",
        "suite_extra_attr",
        "case_extra_attr",
        "case_time",
        "case_extra_child",
        "suite_extra_child",
        "root_extra_child",
    ],
)
def test_regression_junit_attribute_and_child_tamper_fails_closed(tamper):
    report = verifier_v32._regression_report()
    tree = ET.parse(ROOT / verifier_v32.REGRESSION_JUNIT)
    suite = tree.getroot().find("testsuite")
    cases = suite.findall("testcase")
    if tamper == "suite_tests":
        suite.set("tests", "324")
    elif tamper == "suite_failures":
        suite.set("failures", "1")
    elif tamper == "missing_case":
        suite.remove(cases[-1])
    elif tamper == "extra_case":
        suite.append(copy.deepcopy(cases[0]))
    elif tamper == "case_identity":
        cases[0].set("name", "test_tampered")
    elif tamper == "case_outcome":
        suite.set("failures", "1")
        ET.SubElement(cases[0], "failure")
    elif tamper == "suite_extra_attr":
        suite.set("unexpected", "1")
    elif tamper == "case_extra_attr":
        cases[0].set("unexpected", "1")
    elif tamper == "case_time":
        cases[0].set("time", "nan")
    elif tamper == "case_extra_child":
        ET.SubElement(cases[0], "unexpected")
    elif tamper == "suite_extra_child":
        ET.SubElement(suite, "unexpected")
    else:
        ET.SubElement(tree.getroot(), "unexpected")
    with tempfile.TemporaryDirectory(prefix="onyx-v32-junit-tamper-") as directory:
        path = Path(directory) / "tampered.junit.xml"
        tree.write(path, encoding="utf-8", xml_declaration=True)
        with pytest.raises(verifier_v32.V32EvidenceError):
            verifier_v32._junit_path(path, subtest_report=report)


def test_synthetic_junit_counter_requires_explicit_validated_subtest_report():
    with tempfile.TemporaryDirectory(prefix="onyx-v32-junit-synthetic-") as directory:
        path = Path(directory) / "synthetic.junit.xml"
        path.write_text(
            '<testsuites name="pytest tests"><testsuite name="pytest" tests="323" failures="0" errors="0" skipped="0" time="1.000" timestamp="2026-01-01T00:00:00+00:00" hostname="fixture">'
            '<testcase classname="tests.test_regressions" name="test_one" time="0.000" />'
            "</testsuite></testsuites>",
            encoding="utf-8",
        )
        with pytest.raises(
            verifier_v32.V32EvidenceError, match="lacks validated subtest evidence"
        ):
            verifier_v32._junit_path(path)


@pytest.mark.parametrize(
    "tamper",
    [
        "counter_0323",
        "time_exponent",
        "time_leading_zero",
        "root_text",
        "root_tail",
        "suite_tail",
        "case_tail",
        "outcome_text",
        "comment",
        "processing_instruction",
        "namespace",
    ],
)
def test_junit_lexical_text_tail_and_markup_tamper_fails_closed(tamper):
    base = (
        '<?xml version="1.0" encoding="utf-8"?>'
        '<testsuites name="pytest tests"><testsuite name="pytest" errors="0" failures="0" skipped="0" '
        'tests="1" time="1.000" timestamp="2026-01-01T00:00:00+00:00" hostname="fixture">'
        '<testcase classname="tests.test_fixture" name="test_one" time="0.000" />'
        "</testsuite></testsuites>"
    )
    if tamper == "counter_0323":
        raw = base.replace('tests="1"', 'tests="0323"')
    elif tamper == "time_exponent":
        raw = base.replace('time="1.000"', 'time="1e0"', 1)
    elif tamper == "time_leading_zero":
        raw = base.replace('time="1.000"', 'time="01.000"', 1)
    elif tamper == "root_text":
        raw = base.replace(
            '<testsuites name="pytest tests">', '<testsuites name="pytest tests">tamper'
        )
    elif tamper == "root_tail":
        raw = base + "tamper"
    elif tamper == "suite_tail":
        raw = base.replace(
            "</testsuite></testsuites>", "</testsuite>tamper</testsuites>"
        )
    elif tamper == "case_tail":
        raw = base.replace("/></testsuite>", "/>tamper</testsuite>")
    elif tamper == "outcome_text":
        raw = base.replace('failures="0"', 'failures="1"').replace(
            ' time="0.000" />',
            ' time="0.000"><failure>tamper</failure></testcase>',
        )
    elif tamper == "comment":
        raw = base.replace("<testsuite ", "<!--tamper--><testsuite ", 1)
    elif tamper == "processing_instruction":
        raw = base.replace("<testsuite ", "<?tamper value?><testsuite ", 1)
    else:
        raw = base.replace("<testsuites ", '<testsuites xmlns="urn:tamper" ', 1)
    with tempfile.TemporaryDirectory(prefix="onyx-v32-junit-lexical-") as directory:
        path = Path(directory) / "tampered.junit.xml"
        path.write_text(raw, encoding="utf-8")
        with pytest.raises(verifier_v32.V32EvidenceError):
            verifier_v32._junit_path(path)


_EVIDENCE_TAMPER_PATHS = (
    ("artifact", "entries"),
    ("artifact", "unique"),
    ("combined", "counts", "passed"),
    ("combined", "exit_code"),
    ("combined", "junit_sha256"),
    ("combined", "selected_suites"),
    ("combined", "unique_suites"),
    ("regressions", "base_tests_passed"),
    ("regressions", "subtests_passed"),
    ("regressions", "junit_counts", "passed"),
    ("regressions", "exit_code"),
    ("regressions", "junit_sha256"),
    ("regressions", "junit_testcase_elements"),
    ("regressions", "junit_duration_policy"),
    ("regressions", "junit_schema"),
    ("regressions", "report_sha256"),
    ("regressions", "subtest_records"),
    ("regressions", "selected_suites"),
    ("regressions", "unique_suites"),
    ("history", "frozen_candidates_cryptographically_validated"),
    ("history", "manifests_verified"),
    ("history", "unique_leaves_verified"),
    ("history", "roots"),
    ("history", "v14_proof", "artifact_entries"),
    ("history", "v14_proof", "bundle_status"),
    ("history", "v14_proof", "junit_passed"),
    ("history", "v14_proof", "live_scan_count"),
    ("history", "v14_proof", "marker_contract_bound"),
    ("history", "v14_proof", "static_gates"),
    ("history", "v15_proof", "artifact_entries"),
    ("history", "v15_proof", "bundle_status"),
    ("history", "v15_proof", "junit_passed"),
    ("history", "v15_proof", "live_scan_count"),
    ("history", "v15_proof", "marker_contract_bound"),
    ("history", "v15_proof", "static_gates"),
    ("history", "v16_proof", "artifact_entries"),
    ("history", "v16_proof", "bundle_status"),
    ("history", "v16_proof", "junit_passed"),
    ("history", "v16_proof", "live_scan_count"),
    ("history", "v16_proof", "marker_contract_bound"),
    ("history", "v16_proof", "static_gates"),
    ("history", "v17_proof", "artifact_entries"),
    ("history", "v17_proof", "bundle_status"),
    ("history", "v17_proof", "junit_passed"),
    ("history", "v17_proof", "live_scan_count"),
    ("history", "v17_proof", "marker_contract_bound"),
    ("history", "v17_proof", "static_gates"),
    ("history", "v18_proof", "artifact_entries"),
    ("history", "v18_proof", "bundle_status"),
    ("history", "v18_proof", "junit_passed"),
    ("history", "v18_proof", "live_scan_count"),
    ("history", "v18_proof", "marker_contract_bound"),
    ("history", "v18_proof", "static_gates"),
    ("history", "v19_proof", "artifact_entries"),
    ("history", "v19_proof", "bundle_status"),
    ("history", "v19_proof", "junit_passed"),
    ("history", "v19_proof", "live_scan_count"),
    ("history", "v19_proof", "marker_contract_bound"),
    ("history", "v19_proof", "static_gates"),
    ("history", "v20_proof", "artifact_entries"),
    ("history", "v20_proof", "bundle_status"),
    ("history", "v20_proof", "junit_passed"),
    ("history", "v20_proof", "live_scan_count"),
    ("history", "v20_proof", "marker_contract_bound"),
    ("history", "v20_proof", "static_gates"),
    ("history", "v21_proof", "artifact_entries"),
    ("history", "v21_proof", "bundle_status"),
    ("history", "v21_proof", "junit_passed"),
    ("history", "v21_proof", "live_scan_count"),
    ("history", "v21_proof", "marker_contract_bound"),
    ("history", "v21_proof", "static_gates"),
    ("history", "v31_proof", "artifact_entries"),
    ("history", "v31_proof", "bundle_status"),
    ("history", "v31_proof", "junit_passed"),
    ("history", "v31_proof", "live_scan_count"),
    ("history", "v31_proof", "marker_contract_bound"),
    ("history", "v31_proof", "static_gates"),
    ("tamper", "rejected"),
    ("tamper", "total"),
    ("tamper", "unique"),
    ("tamper", "fixtures"),
    ("static", "exit_codes", "RUFF"),
    ("static", "selected_gates"),
    ("live", "count"),
    ("live", "manifest_sha256"),
    ("live", "unique"),
    ("live", "anchors"),
    ("runtime", "architecture"),
    ("runtime", "parent_direct_phases"),
    ("runtime", "arbitrary_command_surfaces"),
    ("runtime", "phase_ids"),
    ("runtime", "windows_launch"),
    ("runtime", "closehandle_fail_closed"),
    ("runtime", "fresh_junit_scope"),
    ("runtime", "parent_owned_tree_roots"),
    ("runtime", "post_kill_drain_seconds"),
    ("runtime", "tree_ownership"),
    ("runtime", "tree_ownership", "windows"),
    ("runtime", "tree_ownership", "posix"),
    ("runtime", "worker_subprocesses"),
    ("runtime", "measured_full_verifier_seconds"),
    ("runtime", "total_timeout_seconds"),
    ("runtime", "windows_processes_per_phase"),
    ("path_integrity", "atomic_with_following_read_hash_or_launch"),
    ("path_integrity", "concurrent_writer_toctou_security_boundary"),
    ("path_integrity", "mode"),
    ("path_integrity", "race_reproduction"),
    ("path_integrity", "scope"),
    ("path_integrity", "trusted_state_requirement"),
)


def _evidence_fixture():
    return {
        "artifact": {"entries": 1, "unique": True},
        "combined": {
            "counts": {"errors": 0, "failed": 0, "passed": 2, "skipped": 0},
            "exit_code": 0,
            "junit_sha256": "a" * 64,
            "selected_suites": ["a.py", "b.py"],
            "unique_suites": True,
        },
        "regressions": {
            "base_tests_passed": 102,
            "exit_code": 0,
            "junit_counts": {"errors": 0, "failed": 0, "passed": 323, "skipped": 0},
            "junit_duration_policy": "canonical_millisecond_decimal_lexical_finite_nonnegative_not_summed",
            "junit_schema": "strict_single_pytest_suite_lexical_v32",
            "junit_sha256": "b" * 64,
            "junit_testcase_elements": 102,
            "report_sha256": "d" * 64,
            "selected_suites": ["tests/test_regressions.py"],
            "subtest_records": 221,
            "subtests_passed": 221,
            "unique_suites": True,
        },
        "history": {
            "frozen_candidates_cryptographically_validated": 21,
            "manifests_verified": 90,
            "roots": ["root.sha256"],
            "unique_leaves_verified": 425,
            "v14_proof": {
                "artifact_entries": 164,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1752,
                "live_scan_count": 93,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v15_proof": {
                "artifact_entries": 179,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1798,
                "live_scan_count": 94,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v16_proof": {
                "artifact_entries": 197,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1826,
                "live_scan_count": 95,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v17_proof": {
                "artifact_entries": 215,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1847,
                "live_scan_count": 96,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v18_proof": {
                "artifact_entries": 234,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1875,
                "live_scan_count": 97,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v19_proof": {
                "artifact_entries": 253,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1893,
                "live_scan_count": 98,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v20_proof": {
                "artifact_entries": 271,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1903,
                "live_scan_count": 99,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v21_proof": {
                "artifact_entries": 289,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 1916,
                "live_scan_count": 100,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
            "v31_proof": {
                "artifact_entries": 475,
                "bundle_status": "candidate-default-off-shadow-only-not-accepted",
                "junit_passed": 2006,
                "live_scan_count": 110,
                "marker_contract_bound": True,
                "static_gates": 8,
            },
        },
        "tamper": {"fixtures": ["core.py"], "rejected": 1, "total": 1, "unique": True},
        "static": {"exit_codes": {"RUFF": 0}, "selected_gates": ["RUFF"]},
        "live": {
            "anchors": ["core.py"],
            "count": 101,
            "manifest_sha256": "c" * 64,
            "unique": True,
        },
        "runtime": {
            "architecture": "fixed_phase_direct_createprocess_suspended_job_resume",
            "arbitrary_command_surfaces": 0,
            "phase_ids": ["focused", "worker"],
            "windows_launch": "CreateProcessW_CREATE_SUSPENDED_Assign_ResumeThread",
            "closehandle_fail_closed": True,
            "fresh_junit_scope": "fixed_private_nonce_directory_realpath_sentinel",
            "measured_full_verifier_seconds": 90.0,
            "parent_direct_phases": ["focused_pytest", "pure_artifact_worker"],
            "parent_owned_tree_roots": 2,
            "post_kill_drain_seconds": 2,
            "tree_ownership": {
                "posix": "popen_immediate_ownership_flat_cleanup_records",
                "windows": "create_suspended_assign_job_then_resume_checked_close",
            },
            "total_timeout_seconds": 300,
            "windows_processes_per_phase": 1,
            "worker_subprocesses": 0,
        },
        "path_integrity": copy.deepcopy(verifier_v32.PATH_INTEGRITY_CONTRACT),
    }


@pytest.mark.parametrize("path", _EVIDENCE_TAMPER_PATHS)
def test_every_structured_evidence_field_tamper_fails_closed(path):
    expected = _evidence_fixture()
    tampered = copy.deepcopy(expected)
    target = tampered
    for key in path[:-1]:
        target = target[key]
    key = path[-1]
    value = target[key]
    if type(value) is bool:
        target[key] = not value
    elif type(value) in {int, float}:
        target[key] = value + 1
    elif isinstance(value, str):
        target[key] = value + "x"
    else:
        target[key] = [*value, "tampered"]
    with pytest.raises(verifier_v32.V32EvidenceError):
        verifier_v32._assert_exact_evidence("fixture", tampered, expected)

"""Authenticated retirement boundary for obsolete Phase 5 Exit byte claims."""

from __future__ import annotations

import functools
import hashlib
import json
import subprocess
from pathlib import Path, PurePosixPath


PROJECT = Path(__file__).resolve().parents[1]
RECORD = PROJECT / "tests/fixtures/phase5_exit_retirement_v1.json"
RECORD_SHA256 = "23562c773b5e1acceadc6ba873b802eebc1d48bafd61ae40d4a9a23aa0635997"
ADDITIONAL_RECORD = PROJECT / "tests/fixtures/phase5_exit_retirement_v2.json"
ADDITIONAL_RECORD_SHA256 = (
    "4f56bbd460d3d96b10f476966e3a4de40ff2a024c48542ebfa57f5b921d9fce6"
)
TRANSITION_PREDECESSOR = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v8.json"
)
TRANSITION_PREDECESSOR_SHA256 = (
    "bea8ec2ce3f240e13750e08e1d7e006ef1d8a6bc0d023eba6ebb288f05734d5a"
)
TRANSITION = PROJECT / "tests/fixtures/phase5_current_successor_transition_v9.json"
TRANSITION_SHA256 = "27991fabab95e3220ab34d86aec00a29d84ba49a82dc6e1ea075dc8662ca2200"
TRANSITION_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V9\0"
CURRENT_TRANSITION_GRANDPREDECESSOR = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v10.json"
)
CURRENT_TRANSITION_GRANDPREDECESSOR_SHA256 = (
    "1e8b86fc3f9f7090180d7f11f45fc2ac6dc326dc2c55782c043ee75328d40e49"
)
CURRENT_TRANSITION_V11 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v11.json"
)
CURRENT_TRANSITION_V11_SHA256 = (
    "a6153df617e9af19f82a21ee00802a2a48c22af736a3b22e437b41705608cd89"
)
CURRENT_TRANSITION_V12 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v12.json"
)
CURRENT_TRANSITION_V12_SHA256 = (
    "e57480c4e52afb6e20aa336e4387b0dd4a5e77bf554eef4e5c7410683d7c16c7"
)
CURRENT_TRANSITION_V13 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v13.json"
)
CURRENT_TRANSITION_V13_SHA256 = (
    "3b7770fb458d2350028ec764418a5ad1071cb34282e0a9e342bfcc76a1d0da42"
)
CURRENT_TRANSITION_V14 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v14.json"
)
CURRENT_TRANSITION_V14_SHA256 = (
    "da0f6d07b7dadd22709147cdfb667bbb7d205949d276f82042f1e27a39225190"
)
CURRENT_TRANSITION_V15 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v15.json"
)
CURRENT_TRANSITION_V15_SHA256 = (
    "f80347f24b3fb2f20a3e7ed3729f7ec28a30947a1d4c3b823baa834a0e8ecb18"
)
CURRENT_TRANSITION_V16 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v16.json"
)
CURRENT_TRANSITION_V16_SHA256 = (
    "364b186c384ac964eab21034d4049536613f50597b67e9edb6604f9edb256901"
)
CURRENT_TRANSITION_V17 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v17.json"
)
CURRENT_TRANSITION_V17_SHA256 = (
    "03edb5ae160ae20ff42e0f7c434b9353637aa44b59fac0d01ea168e89c3e9319"
)
CURRENT_TRANSITION_V18 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v18.json"
)
CURRENT_TRANSITION_V18_SHA256 = (
    "d8f16a1ec8c239693f0c3fbecc234f09f499f2a6004df053d846af2dadaa4179"
)
CURRENT_TRANSITION_V19 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v19.json"
)
CURRENT_TRANSITION_V19_SHA256 = (
    "8c1332c1e33ccfc392abddec4c7863b0bffb9290428c02d77e2c42bbbec87782"
)
CURRENT_TRANSITION_V20 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v20.json"
)
CURRENT_TRANSITION_V20_SHA256 = (
    "8ea87bb7a12bd2343bc9d4bc381c627b27c9155a24aa1eb76f47466bea2773e6"
)
CURRENT_TRANSITION_V21 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v21.json"
)
CURRENT_TRANSITION_V21_SHA256 = (
    "a5f720f39421d68546d1ff8e248e893b174d1f9e7ef0e604c7e8743179531b17"
)
CURRENT_TRANSITION_V22 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v22.json"
)
CURRENT_TRANSITION_V22_SHA256 = (
    "c89cdc8e0782878da6d64ac337992e6a71187798a9e2b228dc354237a22cb2d4"
)
CURRENT_TRANSITION_V23 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v23.json"
)
CURRENT_TRANSITION_V23_SHA256 = (
    "0f3301d1d2d3ec425a7f3439feac6a160ccec0cae3dacc3f8d1bd4173e2a870f"
)
CURRENT_TRANSITION_V24 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v24.json"
)
CURRENT_TRANSITION_V24_SHA256 = (
    "69abcde1629a7a62be7021c5085a4c5a40eab2ed4b9c1175f042c7568af71308"
)
CURRENT_TRANSITION_V25 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v25.json"
)
CURRENT_TRANSITION_V25_SHA256 = (
    "8a3c301980520a89845a65a6933b3e34ea925c4d059f8c15043fe0cf4d3844ae"
)
CURRENT_TRANSITION_V26 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v26.json"
)
CURRENT_TRANSITION_V26_SHA256 = (
    "a0487e3fd397187a86544da6041c143baa6e79834c330ac0ecc9f05215c3fd30"
)
CURRENT_TRANSITION_V27 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v27.json"
)
CURRENT_TRANSITION_V27_SHA256 = (
    "b32fad5ab60091e423a42421f15dfa309f7a3cf34e10e5d56b6ebbf816bf859c"
)
CURRENT_TRANSITION_V28 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v28.json"
)
CURRENT_TRANSITION_V28_SHA256 = (
    "bf76a7eb28234f45e96b5dddfee8f53767cf0e8ef1389a044f8cad10904c2c11"
)
CURRENT_TRANSITION_V29 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v29.json"
)
CURRENT_TRANSITION_V29_SHA256 = (
    "23a8afb1fefba3636d213f0915cf0deefcb3acec98d4d7287b9577cbad02ffdd"
)
CURRENT_TRANSITION_V30 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v30.json"
)
CURRENT_TRANSITION_V30_SHA256 = (
    "a249c44b62e499bf4d8adeb99961be8ba04a49ba11d07269f4a868f93fe0681b"
)
CURRENT_TRANSITION_V31 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v31.json"
)
CURRENT_TRANSITION_V31_SHA256 = (
    "1cf1cd04e9d9cdb07b64cd98aaff051e9369596cf248099c4c293d5fce352ef4"
)
CURRENT_TRANSITION_V32 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v32.json"
)
CURRENT_TRANSITION_V32_SHA256 = (
    "597801d7c0ea273d132ced1e1d936279c68ac4963b3a1235afa742bb1d4afcef"
)
CURRENT_TRANSITION_V33 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v33.json"
)
CURRENT_TRANSITION_V33_SHA256 = (
    "bec66fa14417c871eb409493b5caeb34082a5fea126bdff5f81ee38fcbb93ff6"
)
CURRENT_TRANSITION_V34 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v34.json"
)
CURRENT_TRANSITION_V34_SHA256 = (
    "5d92f4253b7c0adc2afbc294cc36bfaaa474dae6ed35d427b972ea3f8750818e"
)
CURRENT_TRANSITION_V35 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v35.json"
)
CURRENT_TRANSITION_V35_SHA256 = (
    "10bae13d3f14767cf69d74d935783e306de675b098e06a6c175f254a5469ca2d"
)
CURRENT_TRANSITION_V36 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v36.json"
)
CURRENT_TRANSITION_V36_SHA256 = (
    "a1685eeeeaed0cdbcc7d4b1405036b64548733890e5bfc38c0e5053db6696546"
)
CURRENT_TRANSITION_V37 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v37.json"
)
CURRENT_TRANSITION_V37_SHA256 = (
    "7e6ad9282d101666953f80b11278349c95aed5715f2530c2870c18bebc9341af"
)
CURRENT_TRANSITION_V38 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v38.json"
)
CURRENT_TRANSITION_V38_SHA256 = (
    "9b2dfdefdec21b3181799937b8f41721a744cc3652d9ccbd2302eebf8997488f"
)
CURRENT_TRANSITION_V39 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v39.json"
)
CURRENT_TRANSITION_V39_SHA256 = (
    "0e245140f43fc4348f91d35281fa54276a0243f30d94c468bdfb564dc30dcd2a"
)
CURRENT_TRANSITION_V40 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v40.json"
)
CURRENT_TRANSITION_V40_SHA256 = (
    "e043cdb0aaf0e6218f34df2f0a1c214f1e90e62a7eb921ec9edb0634bbacd706"
)
CURRENT_TRANSITION_V41 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v41.json"
)
CURRENT_TRANSITION_V41_SHA256 = (
    "7b23628ec33513dc37357718fc6783fcc400f3d014307377d196570ddb4fc8cb"
)
CURRENT_TRANSITION_V42 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v42.json"
)
CURRENT_TRANSITION_V42_SHA256 = (
    "aa9436d6f7506f078e14f4339b91343c72c83de7381fc40b07d244045f79e91f"
)
CURRENT_TRANSITION_V43 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v43.json"
)
CURRENT_TRANSITION_V43_SHA256 = (
    "90decf307197888f9f4ee2ab54c5dd8105fbacaafcf0792048db6cecff264b27"
)
CURRENT_TRANSITION_V44 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v44.json"
)
CURRENT_TRANSITION_V44_SHA256 = (
    "fac94f38fd08f98e1699b73924c1ead59223228a118b8159152b0b5657942cb2"
)
CURRENT_TRANSITION_V45 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v45.json"
)
CURRENT_TRANSITION_V45_SHA256 = (
    "8fa01953bfd6a4dbda2623b9e20f71d06268dfa66907ac6b1019210459ad582a"
)
CURRENT_TRANSITION_V46 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v46.json"
)
CURRENT_TRANSITION_V46_SHA256 = (
    "4d34ffab0ddf0f2ad55f47d73a816183dd9351c98c741c919bbb2f7706fff3ef"
)
CURRENT_TRANSITION = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v47.json"
)
CURRENT_TRANSITION_PREDECESSOR = CURRENT_TRANSITION_V46
CURRENT_TRANSITION_PREDECESSOR_SHA256 = CURRENT_TRANSITION_V46_SHA256
CURRENT_TRANSITION_SHA256 = (
    "aabe894a896d89bfbdcda7d0c0e78d0952676612af0ee70512c706f1327f1e80"
)
CURRENT_TRANSITION_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V47\0"
CURRENT_TRANSITION_V48 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v48.json"
)
CURRENT_TRANSITION_V48_SHA256 = (
    "cceea900c4c4d0be782c61b675c30aa9771e5348cf8c1e406f1125f184e08dff"
)
CURRENT_TRANSITION_V48_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V48\0"
CURRENT_TRANSITION_V49 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v49.json"
)
CURRENT_TRANSITION_V49_SHA256 = (
    "123a0b772fb23cbc955e8db7fa989bfb404cc1f3193582bcb76748294e4483da"
)
CURRENT_TRANSITION_V49_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V49\0"
CURRENT_TRANSITION_V50 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v50.json"
)
CURRENT_TRANSITION_V50_SHA256 = (
    "5dfd1616743c6c41bf9a37d8d7a17f02928e284f1153d4e883a95460491f252f"
)
CURRENT_TRANSITION_V50_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V50\0"
CURRENT_TRANSITION_V51 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v51.json"
)
CURRENT_TRANSITION_V51_SHA256 = (
    "486228a5ea1780093f85640a4b80cf4ac0be40c2ec41bdac6cd84099822828db"
)
CURRENT_TRANSITION_V51_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V51\0"
CURRENT_TRANSITION_V52 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v52.json"
)
CURRENT_TRANSITION_V52_SHA256 = (
    "d5bd7626c8de73b2d25ca9733454ecbce3202a11df4990161db8102f83826f87"
)
CURRENT_TRANSITION_V52_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V52\0"
CURRENT_TRANSITION_V53 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v53.json"
)
CURRENT_TRANSITION_V53_SHA256 = (
    "7e448dd836e254831f09c4e36d23e726bdf69d425e9a93b77c8e44cef387708a"
)
CURRENT_TRANSITION_V53_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V53\0"
CURRENT_TRANSITION_V54 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v54.json"
)
CURRENT_TRANSITION_V54_SHA256 = (
    "eea1decc632039a4760fd63a127170bb3e27c87c40651337da873f33d141e5c7"
)
CURRENT_TRANSITION_V54_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V54\0"
CURRENT_TRANSITION_V55 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v55.json"
)
CURRENT_TRANSITION_V55_SHA256 = (
    "5357e8b792a99eff9f8d669f07e0bd221e2d4d3b93a9597649bc3fceb4000643"
)
CURRENT_TRANSITION_V55_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V55\0"
CURRENT_TRANSITION_V56 = (
    PROJECT / "tests/fixtures/phase5_current_successor_transition_v56.json"
)
CURRENT_TRANSITION_V56_SHA256 = (
    "b13b106bfb9e570d8e13dc176ce47de9b720586f60c357f59fd7fe2b9ed149f9"
)
CURRENT_TRANSITION_V56_DOMAIN = b"ONYX-PHASE5-CURRENT-SUCCESSOR-TRANSITION-V56\0"
RELEASE_TRANSITION_V1 = PROJECT / "tests/fixtures/release_workflow_transition_v1.json"
RELEASE_TRANSITION_V1_SHA256 = (
    "cd22f9d79b55d117e3bf2e5b49f6ea807fb0fbda367472cd2e40644e4eb305a1"
)
RELEASE_TRANSITION_V2 = PROJECT / "tests/fixtures/release_workflow_transition_v2.json"
RELEASE_TRANSITION_V2_SHA256 = (
    "b34e19a6a34ab8384588203ae73f642df81e5b583d1caf3babe73dd02573794b"
)
RELEASE_TRANSITION_V3 = PROJECT / "tests/fixtures/release_workflow_transition_v3.json"
RELEASE_TRANSITION_V3_SHA256 = (
    "ebe4cc60506b14ac6f41b7306078289e033eedfcb8308130d21b54d46c6d24c0"
)
RELEASE_TRANSITION_V4 = PROJECT / "tests/fixtures/release_workflow_transition_v4.json"
RELEASE_TRANSITION_V4_SHA256 = (
    "bec9658f723fc467d888b311780d013689f6a6ac09cda58ec01827c96b60f12d"
)
RELEASE_TRANSITION_V5 = PROJECT / "tests/fixtures/release_workflow_transition_v5.json"
RELEASE_TRANSITION_V5_SHA256 = (
    "cf271a0669cdc5379589c10285107c83098a573c4e2598442f21ea2d2122c998"
)
RELEASE_TRANSITION_V6 = PROJECT / "tests/fixtures/release_workflow_transition_v6.json"
RELEASE_TRANSITION_V6_SHA256 = (
    "7e1f8bbe71773a7a0f0f0a1d7b57601b119c343f8533d91b703ef4a88b195c44"
)
RELEASE_TRANSITION_V7 = PROJECT / "tests/fixtures/release_workflow_transition_v7.json"
RELEASE_TRANSITION_V7_SHA256 = (
    "67cc64a5f0cea8b3d3562ba2520771d294a6749dd152f30edd2e8c5f6ca92184"
)
RELEASE_TRANSITION_V8 = PROJECT / "tests/fixtures/release_workflow_transition_v8.json"
RELEASE_TRANSITION_V8_SHA256 = (
    "11aaf28a744c8e60db2b32373239ebafc1f2ee189bfbca2c0d899668f007dd68"
)
RELEASE_TRANSITION_V9 = PROJECT / "tests/fixtures/release_workflow_transition_v9.json"
RELEASE_TRANSITION_V9_SHA256 = (
    "841e79d6aeba881efb59d125665d90072784424e938f691bae66e33b4ca9e37c"
)
RELEASE_TRANSITION_V10 = PROJECT / "tests/fixtures/release_workflow_transition_v10.json"
RELEASE_TRANSITION_V10_SHA256 = (
    "1a853081a3c1aad40554e18016fbc9f9601fcbfdb139acb69179d5cb1d365102"
)
RELEASE_TRANSITION_V11 = PROJECT / "tests/fixtures/release_workflow_transition_v11.json"
RELEASE_TRANSITION_V11_SHA256 = (
    "4acd3a16ed58084ae606538babaf00d77172031ed3d3d67c10e3fa5064ee1189"
)
RELEASE_TRANSITION_V12 = PROJECT / "tests/fixtures/release_workflow_transition_v12.json"
RELEASE_TRANSITION_V12_SHA256 = (
    "24c02a99da1b9305648426242f3918008053d81487ab52bca83ca728e9daabf2"
)
RELEASE_TRANSITION_V13 = PROJECT / "tests/fixtures/release_workflow_transition_v13.json"
RELEASE_TRANSITION_V13_SHA256 = (
    "bdd798be370188650b0ae3cb99c849afb095345603276462891a848a9accc6bb"
)
RELEASE_TRANSITION_V14 = PROJECT / "tests/fixtures/release_workflow_transition_v14.json"
RELEASE_TRANSITION_V14_SHA256 = (
    "6cac3eb9da8acb8ce3a69b8af9ce2ab4d00a95e2b5f499012fd7ba491f414e8b"
)
RELEASE_TRANSITION_V15 = PROJECT / "tests/fixtures/release_workflow_transition_v15.json"
RELEASE_TRANSITION_V15_SHA256 = (
    "ed74d716e9d984ea0f410442ee7310e46d6332f051a3cd8e38e0284927fc9273"
)
RELEASE_TRANSITION_V16 = PROJECT / "tests/fixtures/release_workflow_transition_v16.json"
RELEASE_TRANSITION_V16_SHA256 = (
    "ba4b0b57061d121de352880a578d4f8c58eed96c2a353df0fee11f8bbf278e48"
)
RELEASE_TRANSITION_V17 = PROJECT / "tests/fixtures/release_workflow_transition_v17.json"
RELEASE_TRANSITION_V17_SHA256 = (
    "fcd7122bebd2b63dcd8fdcd7f79c2114b56b1a0e00a79a844b624f54fd8dbcbe"
)
RELEASE_TRANSITION_V18 = PROJECT / "tests/fixtures/release_workflow_transition_v18.json"
RELEASE_TRANSITION_V18_SHA256 = (
    "4a58cdaaa67915a0293277c20cf7e830f3fd94c663f81c9c091de72e65e6cbef"
)
RELEASE_TRANSITION_V19 = PROJECT / "tests/fixtures/release_workflow_transition_v19.json"
RELEASE_TRANSITION_V19_SHA256 = (
    "159c7e167b7340030930a9267b9a6754fbad1a5ec9a8e10534c24a90fc5b4ddc"
)
RELEASE_TRANSITION_V20 = PROJECT / "tests/fixtures/release_workflow_transition_v20.json"
RELEASE_TRANSITION_V20_SHA256 = (
    "ecac1556c7e2e40b930b4369c819336e16712f92c654cbee81988b258403bc6e"
)
RELEASE_TRANSITION_V21 = PROJECT / "tests/fixtures/release_workflow_transition_v21.json"
RELEASE_TRANSITION_V21_SHA256 = (
    "9c4fe6c305b1b8ca358db58e2b8c8d8fded65d9c2f5cc1451778e4b926d8f6e2"
)
RELEASE_TRANSITION_V22 = PROJECT / "tests/fixtures/release_workflow_transition_v22.json"
RELEASE_TRANSITION_V22_SHA256 = (
    "5663fa85ee42f0edb830fea0a6600b55f98f6ebc386eaf9608398762f7bcc80b"
)
RELEASE_TRANSITION_V23 = PROJECT / "tests/fixtures/release_workflow_transition_v23.json"
RELEASE_TRANSITION_V23_SHA256 = (
    "cc337f377afe9b8b752ae23bea6aa721f61b07898b1e4899655fa796234e09e7"
)
RELEASE_TRANSITION_V24 = PROJECT / "tests/fixtures/release_workflow_transition_v24.json"
RELEASE_TRANSITION_V24_SHA256 = (
    "93ae2a315815f4ab50f8631178728016870bf421b703eca7ef2ea5bf6668f5b1"
)
RELEASE_TRANSITION_V25 = PROJECT / "tests/fixtures/release_workflow_transition_v25.json"
RELEASE_TRANSITION_V25_SHA256 = (
    "218b61aa439da2ddbe32b162517c531fcae2adc698bb2f605f747a646f41e04a"
)
RELEASE_TRANSITION_V26 = PROJECT / "tests/fixtures/release_workflow_transition_v26.json"
RELEASE_TRANSITION_V26_SHA256 = (
    "185c17071c1c38157d947124483220d99c4eaa0590d374c8af5ae24c46a070c0"
)
RELEASE_TRANSITION_V27 = PROJECT / "tests/fixtures/release_workflow_transition_v27.json"
RELEASE_TRANSITION_V27_SHA256 = (
    "4c143bf67c748eb7116caf3e2165050c3f44eb6cc1f68691a3621478246346b1"
)
RELEASE_TRANSITION_V28 = PROJECT / "tests/fixtures/release_workflow_transition_v28.json"
RELEASE_TRANSITION_V28_SHA256 = (
    "9401f2e32029830528de0d6504cf65c70dc2686b8dd99be31cd05764db414d69"
)
RELEASE_TRANSITION_V29 = PROJECT / "tests/fixtures/release_workflow_transition_v29.json"
RELEASE_TRANSITION_V29_SHA256 = (
    "a9bccacb2e97f430614526bde1be9c5d98b078a72167f76d7348d69cbd4834b7"
)
RELEASE_TRANSITION_V30 = PROJECT / "tests/fixtures/release_workflow_transition_v30.json"
RELEASE_TRANSITION_V30_SHA256 = (
    "66d378407e5aac4782922c7a121eb5a29fea31ba70d01de4c2c08de7f7d288b2"
)
RELEASE_TRANSITION_PREDECESSOR = RELEASE_TRANSITION_V30
RELEASE_TRANSITION_PREDECESSOR_SHA256 = RELEASE_TRANSITION_V30_SHA256
RELEASE_TRANSITION_V31 = PROJECT / "tests/fixtures/release_workflow_transition_v31.json"
RELEASE_TRANSITION_V31_SHA256 = (
    "372e86d759f326fbc9198f9c6d1b49032f7db849f6e4bfb5bc7d93f6e6389307"
)
RELEASE_TRANSITION_V31_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V31\0"
RELEASE_TRANSITION_V30_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V30\0"
RELEASE_TRANSITION_V29_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V29\0"
RELEASE_TRANSITION_V28_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V28\0"
RELEASE_TRANSITION_V27_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V27\0"
RELEASE_TRANSITION_V26_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V26\0"
RELEASE_TRANSITION_V25_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V25\0"
RELEASE_TRANSITION_V24_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V24\0"
RELEASE_TRANSITION_V23_DOMAIN = b"ONYX-RELEASE-WORKFLOW-TRANSITION-V23\0"


class Phase5ExitRetirementError(RuntimeError):
    """An obsolete binding or its named current successor is not authentic."""


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _relative(relative: str) -> Path:
    parsed = PurePosixPath(relative)
    if (
        type(relative) is not str
        or not relative
        or "\\" in relative
        or parsed.is_absolute()
        or str(parsed) != relative
        or any(part in {"", ".", ".."} for part in parsed.parts)
    ):
        raise Phase5ExitRetirementError("noncanonical retirement path")
    return Path(*parsed.parts)


def _read(root: Path, relative: str) -> bytes:
    base = Path(root).resolve(strict=True)
    candidate = base / _relative(relative)
    if candidate.is_symlink():
        raise Phase5ExitRetirementError(f"retirement path is linked: {relative}")
    path = candidate.resolve(strict=True)
    try:
        path.relative_to(base)
    except ValueError as error:
        raise Phase5ExitRetirementError("retirement path escaped root") from error
    if path != candidate.absolute() or not path.is_file():
        raise Phase5ExitRetirementError(f"retirement path is not a file: {relative}")
    return path.read_bytes()


def _valid_sha(value: object) -> bool:
    return (
        type(value) is str
        and len(value) == 64
        and all(character in "0123456789abcdef" for character in value)
    )


def _frame(hasher: object, value: str) -> None:
    encoded = value.encode("utf-8")
    hasher.update(len(encoded).to_bytes(8, "big"))
    hasher.update(encoded)


def _recorded_release_root(transition: dict[str, object], domain: bytes) -> str:
    """Reproduce a release root from recorded hashes without reading old targets."""

    predecessor = transition.get("predecessor")
    entries = transition.get("current_release_paths")
    if (
        type(predecessor) is not dict
        or set(predecessor) != {"path", "sha256"}
        or not _valid_sha(predecessor.get("sha256"))
        or type(entries) is not list
        or not entries
    ):
        raise Phase5ExitRetirementError("recorded release root contract drifted")
    _relative(predecessor["path"])
    hasher = hashlib.sha256()
    hasher.update(domain)
    for value in (predecessor["path"], predecessor["sha256"]):
        _frame(hasher, value)
    paths: list[str] = []
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or not _valid_sha(entry.get("sha256"))
        ):
            raise Phase5ExitRetirementError("recorded release entry is malformed")
        relative = entry["path"]
        _relative(relative)
        paths.append(relative)
        _frame(hasher, relative)
        _frame(hasher, entry["sha256"])
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise Phase5ExitRetirementError("recorded release paths drifted")
    return hasher.hexdigest()


@functools.lru_cache(maxsize=1)
def load_current_successor_transition_v47() -> dict[str, object]:
    """Authenticate V47 as current while preserving V46 through V9 exactly."""

    raw = CURRENT_TRANSITION.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 successor transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError(
            "current Phase 5 successor transition is not canonical"
        )
    try:
        transition = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid current Phase 5 successor transition"
        ) from error
    expected_keys = {
        "schema",
        "issued_at",
        "predecessor_clock_anomaly",
        "predecessor",
        "policy",
        "historical_bindings",
        "named_successors",
        "current_root_sha256",
    }
    expected_policy = {
        "historical_bindings_are_rewritten": False,
        "historical_hashes_are_rebound": False,
        "predecessor_root_must_remain_reproducible": True,
        "current_paths_are_sha256_bound": True,
        "named_successors_are_sha256_bound": True,
        "runtime_authority_changes": True,
    }
    historical_policy = {**expected_policy, "runtime_authority_changes": False}
    if (
        type(transition) is not dict
        or set(transition) != expected_keys
        or transition["schema"] != "onyx.phase5-current-successor-transition.v47"
        or transition["predecessor_clock_anomaly"]
        != {
            "predecessor_issued_at": "2026-08-10T19:45:00-04:00",
            "observed_at": "2026-08-11T01:36:00-04:00",
            "reason": "security_dependency_successor",
        }
        or transition["policy"] != expected_policy
        or transition["predecessor"]
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v46.json",
            "sha256": CURRENT_TRANSITION_PREDECESSOR_SHA256,
        }
        or not _valid_sha(transition["current_root_sha256"])
    ):
        raise Phase5ExitRetirementError(
            "current Phase 5 successor transition policy drifted"
        )

    predecessor_raw = CURRENT_TRANSITION_PREDECESSOR.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_PREDECESSOR_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 successor predecessor drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "current Phase 5 successor predecessor is not canonical"
        )
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid current Phase 5 successor predecessor"
        ) from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema") != "onyx.phase5-current-successor-transition.v46"
        or predecessor.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v45.json",
            "sha256": CURRENT_TRANSITION_V45_SHA256,
        }
        or predecessor.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError(
            "current Phase 5 successor predecessor contract drifted"
        )
    v45_raw = CURRENT_TRANSITION_V45.read_bytes()
    if _sha(v45_raw) != CURRENT_TRANSITION_V45_SHA256:
        raise Phase5ExitRetirementError("V45 successor predecessor drifted")
    if (
        v45_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v45_raw
        or not v45_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V45 successor predecessor is not canonical")
    try:
        v45 = json.loads(v45_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V45 successor predecessor") from error
    if (
        type(v45) is not dict
        or v45.get("schema") != "onyx.phase5-current-successor-transition.v45"
        or v45.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v44.json",
            "sha256": CURRENT_TRANSITION_V44_SHA256,
        }
        or v45.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V45 successor predecessor contract drifted")
    v44_raw = CURRENT_TRANSITION_V44.read_bytes()
    if _sha(v44_raw) != CURRENT_TRANSITION_V44_SHA256:
        raise Phase5ExitRetirementError("V44 successor predecessor drifted")
    if (
        v44_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v44_raw
        or not v44_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V44 successor predecessor is not canonical")
    try:
        v44 = json.loads(v44_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V44 successor predecessor") from error
    if (
        type(v44) is not dict
        or v44.get("schema") != "onyx.phase5-current-successor-transition.v44"
        or v44.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v43.json",
            "sha256": CURRENT_TRANSITION_V43_SHA256,
        }
        or v44.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V44 successor predecessor contract drifted")
    v43_raw = CURRENT_TRANSITION_V43.read_bytes()
    if _sha(v43_raw) != CURRENT_TRANSITION_V43_SHA256:
        raise Phase5ExitRetirementError("V43 successor predecessor drifted")
    if (
        v43_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v43_raw
        or not v43_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V43 successor predecessor is not canonical")
    try:
        v43 = json.loads(v43_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V43 successor predecessor") from error
    if (
        type(v43) is not dict
        or v43.get("schema") != "onyx.phase5-current-successor-transition.v43"
        or v43.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v42.json",
            "sha256": CURRENT_TRANSITION_V42_SHA256,
        }
        or v43.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V43 successor predecessor contract drifted")
    v42_raw = CURRENT_TRANSITION_V42.read_bytes()
    if _sha(v42_raw) != CURRENT_TRANSITION_V42_SHA256:
        raise Phase5ExitRetirementError("V42 successor predecessor drifted")
    if (
        v42_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v42_raw
        or not v42_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V42 successor predecessor is not canonical")
    try:
        v42 = json.loads(v42_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V42 successor predecessor") from error
    if (
        type(v42) is not dict
        or v42.get("schema") != "onyx.phase5-current-successor-transition.v42"
        or v42.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v41.json",
            "sha256": CURRENT_TRANSITION_V41_SHA256,
        }
        or v42.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V42 successor predecessor contract drifted")
    v41_raw = CURRENT_TRANSITION_V41.read_bytes()
    if _sha(v41_raw) != CURRENT_TRANSITION_V41_SHA256:
        raise Phase5ExitRetirementError("V41 successor predecessor drifted")
    if (
        v41_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v41_raw
        or not v41_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V41 successor predecessor is not canonical")
    try:
        v41 = json.loads(v41_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V41 successor predecessor") from error
    if (
        type(v41) is not dict
        or v41.get("schema") != "onyx.phase5-current-successor-transition.v41"
        or v41.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v40.json",
            "sha256": CURRENT_TRANSITION_V40_SHA256,
        }
        or v41.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V41 successor predecessor contract drifted")
    v40_raw = CURRENT_TRANSITION_V40.read_bytes()
    if _sha(v40_raw) != CURRENT_TRANSITION_V40_SHA256:
        raise Phase5ExitRetirementError("V40 successor predecessor drifted")
    if (
        v40_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v40_raw
        or not v40_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V40 successor predecessor is not canonical")
    try:
        v40 = json.loads(v40_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V40 successor predecessor") from error
    if (
        type(v40) is not dict
        or v40.get("schema") != "onyx.phase5-current-successor-transition.v40"
        or v40.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v39.json",
            "sha256": CURRENT_TRANSITION_V39_SHA256,
        }
        or v40.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V40 successor predecessor contract drifted")
    v39_raw = CURRENT_TRANSITION_V39.read_bytes()
    if _sha(v39_raw) != CURRENT_TRANSITION_V39_SHA256:
        raise Phase5ExitRetirementError("V39 successor predecessor drifted")
    if (
        v39_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v39_raw
        or not v39_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V39 successor predecessor is not canonical")
    try:
        v39 = json.loads(v39_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V39 successor predecessor") from error
    if (
        type(v39) is not dict
        or v39.get("schema") != "onyx.phase5-current-successor-transition.v39"
        or v39.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v38.json",
            "sha256": CURRENT_TRANSITION_V38_SHA256,
        }
        or v39.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V39 successor predecessor contract drifted")

    v38_raw = CURRENT_TRANSITION_V38.read_bytes()
    if _sha(v38_raw) != CURRENT_TRANSITION_V38_SHA256:
        raise Phase5ExitRetirementError("V38 successor predecessor drifted")
    if (
        v38_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v38_raw
        or not v38_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V38 successor predecessor is not canonical")
    try:
        v38 = json.loads(v38_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V38 successor predecessor") from error
    if (
        type(v38) is not dict
        or v38.get("schema") != "onyx.phase5-current-successor-transition.v38"
        or v38.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v37.json",
            "sha256": CURRENT_TRANSITION_V37_SHA256,
        }
        or v38.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V38 successor predecessor contract drifted")
    v37_raw = CURRENT_TRANSITION_V37.read_bytes()
    if _sha(v37_raw) != CURRENT_TRANSITION_V37_SHA256:
        raise Phase5ExitRetirementError("V37 successor predecessor drifted")
    if (
        v37_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v37_raw
        or not v37_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V37 successor predecessor is not canonical")
    try:
        v37 = json.loads(v37_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V37 successor predecessor") from error
    if (
        type(v37) is not dict
        or v37.get("schema") != "onyx.phase5-current-successor-transition.v37"
        or v37.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v36.json",
            "sha256": CURRENT_TRANSITION_V36_SHA256,
        }
        or v37.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V37 successor predecessor contract drifted")
    v36_raw = CURRENT_TRANSITION_V36.read_bytes()
    if _sha(v36_raw) != CURRENT_TRANSITION_V36_SHA256:
        raise Phase5ExitRetirementError("V36 successor predecessor drifted")
    if (
        v36_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v36_raw
        or not v36_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V36 successor predecessor is not canonical")
    try:
        v36 = json.loads(v36_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V36 successor predecessor") from error
    if (
        type(v36) is not dict
        or v36.get("schema") != "onyx.phase5-current-successor-transition.v36"
        or v36.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v35.json",
            "sha256": CURRENT_TRANSITION_V35_SHA256,
        }
        or v36.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V36 successor predecessor contract drifted")
    v35_raw = CURRENT_TRANSITION_V35.read_bytes()
    if _sha(v35_raw) != CURRENT_TRANSITION_V35_SHA256:
        raise Phase5ExitRetirementError("V35 successor predecessor drifted")
    if (
        v35_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v35_raw
        or not v35_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V35 successor predecessor is not canonical")
    try:
        v35 = json.loads(v35_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V35 successor predecessor") from error
    if (
        type(v35) is not dict
        or v35.get("schema") != "onyx.phase5-current-successor-transition.v35"
        or v35.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v34.json",
            "sha256": CURRENT_TRANSITION_V34_SHA256,
        }
        or v35.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V35 successor predecessor contract drifted")
    v34_raw = CURRENT_TRANSITION_V34.read_bytes()
    if _sha(v34_raw) != CURRENT_TRANSITION_V34_SHA256:
        raise Phase5ExitRetirementError("V34 successor predecessor drifted")
    if (
        v34_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v34_raw
        or not v34_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V34 successor predecessor is not canonical")
    try:
        v34 = json.loads(v34_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V34 successor predecessor") from error
    if (
        type(v34) is not dict
        or v34.get("schema") != "onyx.phase5-current-successor-transition.v34"
        or v34.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v33.json",
            "sha256": CURRENT_TRANSITION_V33_SHA256,
        }
        or v34.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V34 successor predecessor contract drifted")
    v33_raw = CURRENT_TRANSITION_V33.read_bytes()
    if _sha(v33_raw) != CURRENT_TRANSITION_V33_SHA256:
        raise Phase5ExitRetirementError("V33 successor predecessor drifted")
    if (
        v33_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v33_raw
        or not v33_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V33 successor predecessor is not canonical")
    try:
        v33 = json.loads(v33_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V33 successor predecessor") from error
    if (
        type(v33) is not dict
        or v33.get("schema") != "onyx.phase5-current-successor-transition.v33"
        or v33.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v32.json",
            "sha256": CURRENT_TRANSITION_V32_SHA256,
        }
        or v33.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V33 successor predecessor contract drifted")
    v32_raw = CURRENT_TRANSITION_V32.read_bytes()
    if _sha(v32_raw) != CURRENT_TRANSITION_V32_SHA256:
        raise Phase5ExitRetirementError("V32 successor predecessor drifted")
    if (
        v32_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v32_raw
        or not v32_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V32 successor predecessor is not canonical")
    try:
        v32 = json.loads(v32_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V32 successor predecessor") from error
    if (
        type(v32) is not dict
        or v32.get("schema") != "onyx.phase5-current-successor-transition.v32"
        or v32.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v31.json",
            "sha256": CURRENT_TRANSITION_V31_SHA256,
        }
        or v32.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V32 successor predecessor contract drifted")
    v31_raw = CURRENT_TRANSITION_V31.read_bytes()
    if _sha(v31_raw) != CURRENT_TRANSITION_V31_SHA256:
        raise Phase5ExitRetirementError("V31 successor predecessor drifted")
    if (
        v31_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v31_raw
        or not v31_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V31 successor predecessor is not canonical")
    try:
        v31 = json.loads(v31_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V31 successor predecessor") from error
    if (
        type(v31) is not dict
        or v31.get("schema") != "onyx.phase5-current-successor-transition.v31"
        or v31.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v30.json",
            "sha256": CURRENT_TRANSITION_V30_SHA256,
        }
        or v31.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V31 successor predecessor contract drifted")
    v30_raw = CURRENT_TRANSITION_V30.read_bytes()
    if _sha(v30_raw) != CURRENT_TRANSITION_V30_SHA256:
        raise Phase5ExitRetirementError("V30 successor predecessor drifted")
    if (
        v30_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v30_raw
        or not v30_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V30 successor predecessor is not canonical")
    try:
        v30 = json.loads(v30_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V30 successor predecessor") from error
    if (
        type(v30) is not dict
        or v30.get("schema") != "onyx.phase5-current-successor-transition.v30"
        or v30.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v29.json",
            "sha256": CURRENT_TRANSITION_V29_SHA256,
        }
        or v30.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V30 successor predecessor contract drifted")
    v29_raw = CURRENT_TRANSITION_V29.read_bytes()
    if _sha(v29_raw) != CURRENT_TRANSITION_V29_SHA256:
        raise Phase5ExitRetirementError("V29 successor predecessor drifted")
    if (
        v29_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v29_raw
        or not v29_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V29 successor predecessor is not canonical")
    try:
        v29 = json.loads(v29_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V29 successor predecessor") from error
    if (
        type(v29) is not dict
        or v29.get("schema") != "onyx.phase5-current-successor-transition.v29"
        or v29.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v28.json",
            "sha256": CURRENT_TRANSITION_V28_SHA256,
        }
        or v29.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V29 successor predecessor contract drifted")
    v28_raw = CURRENT_TRANSITION_V28.read_bytes()
    if _sha(v28_raw) != CURRENT_TRANSITION_V28_SHA256:
        raise Phase5ExitRetirementError("V28 successor predecessor drifted")
    if (
        v28_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v28_raw
        or not v28_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V28 successor predecessor is not canonical")
    try:
        v28 = json.loads(v28_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V28 successor predecessor") from error
    if (
        type(v28) is not dict
        or v28.get("schema") != "onyx.phase5-current-successor-transition.v28"
        or v28.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v27.json",
            "sha256": CURRENT_TRANSITION_V27_SHA256,
        }
        or v28.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V28 successor predecessor contract drifted")
    v27_raw = CURRENT_TRANSITION_V27.read_bytes()
    if _sha(v27_raw) != CURRENT_TRANSITION_V27_SHA256:
        raise Phase5ExitRetirementError("V27 successor predecessor drifted")
    if (
        v27_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v27_raw
        or not v27_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V27 successor predecessor is not canonical")
    try:
        v27 = json.loads(v27_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V27 successor predecessor") from error
    if (
        type(v27) is not dict
        or v27.get("schema") != "onyx.phase5-current-successor-transition.v27"
        or v27.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v26.json",
            "sha256": CURRENT_TRANSITION_V26_SHA256,
        }
        or v27.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V27 successor predecessor contract drifted")
    v26_raw = CURRENT_TRANSITION_V26.read_bytes()
    if _sha(v26_raw) != CURRENT_TRANSITION_V26_SHA256:
        raise Phase5ExitRetirementError("V26 successor predecessor drifted")
    if (
        v26_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v26_raw
        or not v26_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V26 successor predecessor is not canonical")
    try:
        v26 = json.loads(v26_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V26 successor predecessor") from error
    if (
        type(v26) is not dict
        or v26.get("schema") != "onyx.phase5-current-successor-transition.v26"
        or v26.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v25.json",
            "sha256": CURRENT_TRANSITION_V25_SHA256,
        }
        or v26.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V26 successor predecessor contract drifted")
    v25_raw = CURRENT_TRANSITION_V25.read_bytes()
    if _sha(v25_raw) != CURRENT_TRANSITION_V25_SHA256:
        raise Phase5ExitRetirementError("V25 successor predecessor drifted")
    if (
        v25_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v25_raw
        or not v25_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V25 successor predecessor is not canonical")
    try:
        v25 = json.loads(v25_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V25 successor predecessor") from error
    if (
        type(v25) is not dict
        or v25.get("schema") != "onyx.phase5-current-successor-transition.v25"
        or v25.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v24.json",
            "sha256": CURRENT_TRANSITION_V24_SHA256,
        }
        or v25.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V25 successor predecessor contract drifted")
    v24_raw = CURRENT_TRANSITION_V24.read_bytes()
    if _sha(v24_raw) != CURRENT_TRANSITION_V24_SHA256:
        raise Phase5ExitRetirementError("V24 successor predecessor drifted")
    if (
        v24_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v24_raw
        or not v24_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V24 successor predecessor is not canonical")
    try:
        v24 = json.loads(v24_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V24 successor predecessor") from error
    if (
        type(v24) is not dict
        or v24.get("schema") != "onyx.phase5-current-successor-transition.v24"
        or v24.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v23.json",
            "sha256": CURRENT_TRANSITION_V23_SHA256,
        }
        or v24.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V24 successor predecessor contract drifted")
    v23_raw = CURRENT_TRANSITION_V23.read_bytes()
    if _sha(v23_raw) != CURRENT_TRANSITION_V23_SHA256:
        raise Phase5ExitRetirementError("V23 successor predecessor drifted")
    if (
        v23_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v23_raw
        or not v23_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V23 successor predecessor is not canonical")
    try:
        v23 = json.loads(v23_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V23 successor predecessor") from error
    if (
        type(v23) is not dict
        or v23.get("schema") != "onyx.phase5-current-successor-transition.v23"
        or v23.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v22.json",
            "sha256": CURRENT_TRANSITION_V22_SHA256,
        }
        or v23.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V23 successor predecessor contract drifted")
    v22_raw = CURRENT_TRANSITION_V22.read_bytes()
    if _sha(v22_raw) != CURRENT_TRANSITION_V22_SHA256:
        raise Phase5ExitRetirementError("V22 successor predecessor drifted")
    if (
        v22_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v22_raw
        or not v22_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V22 successor predecessor is not canonical")
    try:
        v22 = json.loads(v22_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V22 successor predecessor") from error
    if (
        type(v22) is not dict
        or v22.get("schema") != "onyx.phase5-current-successor-transition.v22"
        or v22.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v21.json",
            "sha256": CURRENT_TRANSITION_V21_SHA256,
        }
        or v22.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V22 successor predecessor contract drifted")
    v21_raw = CURRENT_TRANSITION_V21.read_bytes()
    if _sha(v21_raw) != CURRENT_TRANSITION_V21_SHA256:
        raise Phase5ExitRetirementError("V21 successor predecessor drifted")
    if (
        v21_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v21_raw
        or not v21_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V21 successor predecessor is not canonical")
    try:
        v21 = json.loads(v21_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V21 successor predecessor") from error
    if (
        type(v21) is not dict
        or v21.get("schema") != "onyx.phase5-current-successor-transition.v21"
        or v21.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v20.json",
            "sha256": CURRENT_TRANSITION_V20_SHA256,
        }
        or v21.get("policy") != expected_policy
    ):
        raise Phase5ExitRetirementError("V21 successor predecessor contract drifted")
    v20_raw = CURRENT_TRANSITION_V20.read_bytes()
    if _sha(v20_raw) != CURRENT_TRANSITION_V20_SHA256:
        raise Phase5ExitRetirementError("V20 successor predecessor drifted")
    if (
        v20_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v20_raw
        or not v20_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V20 successor predecessor is not canonical")
    try:
        v20 = json.loads(v20_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V20 successor predecessor") from error
    if (
        type(v20) is not dict
        or v20.get("schema") != "onyx.phase5-current-successor-transition.v20"
        or v20.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v19.json",
            "sha256": CURRENT_TRANSITION_V19_SHA256,
        }
        or v20.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V20 successor predecessor contract drifted")
    v19_raw = CURRENT_TRANSITION_V19.read_bytes()
    if _sha(v19_raw) != CURRENT_TRANSITION_V19_SHA256:
        raise Phase5ExitRetirementError("V19 successor predecessor drifted")
    if (
        v19_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v19_raw
        or not v19_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V19 successor predecessor is not canonical")
    try:
        v19 = json.loads(v19_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V19 successor predecessor") from error
    if (
        type(v19) is not dict
        or v19.get("schema") != "onyx.phase5-current-successor-transition.v19"
        or v19.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v18.json",
            "sha256": CURRENT_TRANSITION_V18_SHA256,
        }
        or v19.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V19 successor predecessor contract drifted")
    v18_raw = CURRENT_TRANSITION_V18.read_bytes()
    if _sha(v18_raw) != CURRENT_TRANSITION_V18_SHA256:
        raise Phase5ExitRetirementError("V18 successor predecessor drifted")
    if (
        v18_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v18_raw
        or not v18_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V18 successor predecessor is not canonical")
    try:
        v18 = json.loads(v18_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V18 successor predecessor") from error
    if (
        type(v18) is not dict
        or v18.get("schema") != "onyx.phase5-current-successor-transition.v18"
        or v18.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v17.json",
            "sha256": CURRENT_TRANSITION_V17_SHA256,
        }
        or v18.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V18 successor predecessor contract drifted")
    v17_raw = CURRENT_TRANSITION_V17.read_bytes()
    if _sha(v17_raw) != CURRENT_TRANSITION_V17_SHA256:
        raise Phase5ExitRetirementError("V17 successor predecessor drifted")
    if (
        v17_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v17_raw
        or not v17_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V17 successor predecessor is not canonical")
    try:
        v17 = json.loads(v17_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V17 successor predecessor") from error
    if (
        type(v17) is not dict
        or v17.get("schema") != "onyx.phase5-current-successor-transition.v17"
        or v17.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v16.json",
            "sha256": CURRENT_TRANSITION_V16_SHA256,
        }
        or v17.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V17 successor predecessor contract drifted")
    v16_raw = CURRENT_TRANSITION_V16.read_bytes()
    if _sha(v16_raw) != CURRENT_TRANSITION_V16_SHA256:
        raise Phase5ExitRetirementError("V16 successor predecessor drifted")
    if (
        v16_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v16_raw
        or not v16_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V16 successor predecessor is not canonical")
    try:
        v16 = json.loads(v16_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V16 successor predecessor") from error
    if (
        type(v16) is not dict
        or v16.get("schema") != "onyx.phase5-current-successor-transition.v16"
        or v16.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v15.json",
            "sha256": CURRENT_TRANSITION_V15_SHA256,
        }
        or v16.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V16 successor predecessor contract drifted")
    v15_raw = CURRENT_TRANSITION_V15.read_bytes()
    if _sha(v15_raw) != CURRENT_TRANSITION_V15_SHA256:
        raise Phase5ExitRetirementError("V15 successor predecessor drifted")
    if (
        v15_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v15_raw
        or not v15_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V15 successor predecessor is not canonical")
    try:
        v15 = json.loads(v15_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V15 successor predecessor") from error
    if (
        type(v15) is not dict
        or v15.get("schema") != "onyx.phase5-current-successor-transition.v15"
        or v15.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v14.json",
            "sha256": CURRENT_TRANSITION_V14_SHA256,
        }
        or v15.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V15 successor predecessor contract drifted")
    v14_raw = CURRENT_TRANSITION_V14.read_bytes()
    if _sha(v14_raw) != CURRENT_TRANSITION_V14_SHA256:
        raise Phase5ExitRetirementError("V14 successor predecessor drifted")
    if (
        v14_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v14_raw
        or not v14_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V14 successor predecessor is not canonical")
    try:
        v14 = json.loads(v14_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V14 successor predecessor") from error
    if (
        type(v14) is not dict
        or v14.get("schema") != "onyx.phase5-current-successor-transition.v14"
        or v14.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v13.json",
            "sha256": CURRENT_TRANSITION_V13_SHA256,
        }
        or v14.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V14 successor predecessor contract drifted")
    v13_raw = CURRENT_TRANSITION_V13.read_bytes()
    if _sha(v13_raw) != CURRENT_TRANSITION_V13_SHA256:
        raise Phase5ExitRetirementError("V13 successor predecessor drifted")
    if (
        v13_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v13_raw
        or not v13_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V13 successor predecessor is not canonical")
    try:
        v13 = json.loads(v13_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V13 successor predecessor") from error
    if (
        type(v13) is not dict
        or v13.get("schema") != "onyx.phase5-current-successor-transition.v13"
        or v13.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v12.json",
            "sha256": CURRENT_TRANSITION_V12_SHA256,
        }
        or v13.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V13 successor predecessor contract drifted")
    v12_raw = CURRENT_TRANSITION_V12.read_bytes()
    if _sha(v12_raw) != CURRENT_TRANSITION_V12_SHA256:
        raise Phase5ExitRetirementError("V12 successor predecessor drifted")
    if (
        v12_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v12_raw
        or not v12_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V12 successor predecessor is not canonical")
    try:
        v12 = json.loads(v12_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V12 successor predecessor") from error
    if (
        type(v12) is not dict
        or v12.get("schema") != "onyx.phase5-current-successor-transition.v12"
        or v12.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v11.json",
            "sha256": CURRENT_TRANSITION_V11_SHA256,
        }
        or v12.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V12 successor predecessor contract drifted")
    v11_raw = CURRENT_TRANSITION_V11.read_bytes()
    if _sha(v11_raw) != CURRENT_TRANSITION_V11_SHA256:
        raise Phase5ExitRetirementError("V11 successor predecessor drifted")
    if (
        v11_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in v11_raw
        or not v11_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("V11 successor predecessor is not canonical")
    try:
        v11 = json.loads(v11_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid V11 successor predecessor") from error
    if (
        type(v11) is not dict
        or v11.get("schema") != "onyx.phase5-current-successor-transition.v11"
        or v11.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v10.json",
            "sha256": CURRENT_TRANSITION_GRANDPREDECESSOR_SHA256,
        }
        or v11.get("policy") != historical_policy
    ):
        raise Phase5ExitRetirementError("V11 successor predecessor contract drifted")
    if _sha(CURRENT_TRANSITION_GRANDPREDECESSOR.read_bytes()) != (
        CURRENT_TRANSITION_GRANDPREDECESSOR_SHA256
    ):
        raise Phase5ExitRetirementError("V10 successor predecessor drifted")
    if _sha(TRANSITION.read_bytes()) != TRANSITION_SHA256:
        raise Phase5ExitRetirementError("V9 successor predecessor drifted")

    record_raw = RECORD.read_bytes()
    if _sha(record_raw) != RECORD_SHA256:
        raise Phase5ExitRetirementError("Phase 5 Exit predecessor root drifted")
    try:
        record = json.loads(record_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 Exit predecessor") from error

    historical = transition["historical_bindings"]
    successors = transition["named_successors"]
    prior_historical = predecessor.get("historical_bindings")
    prior_successors = predecessor.get("named_successors")
    if (
        type(historical) is not list
        or len(historical) != 18
        or type(successors) is not list
        or len(successors) != 7
        or type(prior_historical) is not list
        or type(prior_successors) is not list
        or [entry.get("path") for entry in historical]
        != [entry["path"] for entry in record["bindings"]]
        or [entry.get("path") for entry in successors] != sorted(record["successors"])
    ):
        raise Phase5ExitRetirementError(
            "current Phase 5 successor transition cardinality drifted"
        )

    hasher = hashlib.sha256()
    hasher.update(CURRENT_TRANSITION_DOMAIN)
    anomaly = transition["predecessor_clock_anomaly"]
    for value in (
        anomaly["predecessor_issued_at"],
        anomaly["observed_at"],
        anomaly["reason"],
    ):
        _frame(hasher, value)
    for current, prior, original in zip(
        historical, prior_historical, record["bindings"], strict=True
    ):
        if (
            type(current) is not dict
            or set(current)
            != {
                "path",
                "historical_sha256",
                "current_sha256",
                "state",
                "successor",
            }
            or (
                current["path"],
                current["historical_sha256"],
                current["state"],
                current["successor"],
            )
            != (
                prior.get("path"),
                prior.get("historical_sha256"),
                prior.get("state"),
                prior.get("successor"),
            )
            or (
                current["path"],
                current["historical_sha256"],
                current["state"],
                current["successor"],
            )
            != (
                original["path"],
                original["historical_sha256"],
                original["state"],
                original["successor"],
            )
            or not _valid_sha(current["current_sha256"])
            or _sha(_read(PROJECT, current["path"])) != current["current_sha256"]
        ):
            raise Phase5ExitRetirementError(
                f"current historical target drifted: {current.get('path')}"
            )
        for value in (
            "historical-binding",
            current["path"],
            current["historical_sha256"],
            current["current_sha256"],
            current["state"],
            current["successor"],
        ):
            _frame(hasher, value)
    for current, prior in zip(successors, prior_successors, strict=True):
        if (
            type(current) is not dict
            or set(current) != {"path", "predecessor_sha256", "current_sha256"}
            or (current["path"], current["predecessor_sha256"])
            != (prior.get("path"), prior.get("predecessor_sha256"))
            or record["successors"].get(current["path"])
            != current["predecessor_sha256"]
            or not _valid_sha(current["current_sha256"])
            or _sha(_read(PROJECT, current["path"])) != current["current_sha256"]
        ):
            raise Phase5ExitRetirementError(
                f"named current Phase 5 successor drifted: {current.get('path')}"
            )
        for value in (
            "named-successor",
            current["path"],
            current["predecessor_sha256"],
            current["current_sha256"],
        ):
            _frame(hasher, value)
    if hasher.hexdigest() != transition["current_root_sha256"]:
        raise Phase5ExitRetirementError(
            "current Phase 5 successor transition root drifted"
        )
    return transition


@functools.lru_cache(maxsize=1)
def _load_current_successor_transition_v49() -> dict[str, object]:
    """Authenticate the immutable V49 predecessor chain and then-current bytes."""

    predecessor_raw = CURRENT_TRANSITION.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V47 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V47 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V47 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v47"
        or predecessor.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v46.json",
            "sha256": CURRENT_TRANSITION_PREDECESSOR_SHA256,
        }
    ):
        raise Phase5ExitRetirementError("Phase 5 V47 predecessor contract drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_DOMAIN)
    anomaly = predecessor.get("predecessor_clock_anomaly")
    if type(anomaly) is not dict or set(anomaly) != {
        "predecessor_issued_at",
        "observed_at",
        "reason",
    }:
        raise Phase5ExitRetirementError("Phase 5 V47 clock record drifted")
    for value in (
        anomaly["predecessor_issued_at"],
        anomaly["observed_at"],
        anomaly["reason"],
    ):
        _frame(predecessor_root, value)
    for entry in predecessor.get("historical_bindings", []):
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor.get("named_successors", []):
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V47 recorded root drifted")

    raw = CURRENT_TRANSITION_V48.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V48_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V48 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V48 transition is not canonical")
    try:
        transition = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V48 transition") from error
    if (
        type(transition) is not dict
        or transition.get("schema")
        != "onyx.phase5-current-successor-transition.v48"
        or transition.get("predecessor_clock_anomaly") is not None
        or transition.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v47.json",
            "sha256": CURRENT_TRANSITION_SHA256,
        }
        or transition.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V48 policy drifted")
    historical = transition.get("historical_bindings")
    successors = transition.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (entry.get("path"), entry.get("historical_sha256"), entry.get("state"), entry.get("successor"))
            for entry in historical
        ]
        != [
            (entry.get("path"), entry.get("historical_sha256"), entry.get("state"), entry.get("successor"))
            for entry in predecessor["historical_bindings"]
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor["named_successors"]
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V48 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V48_DOMAIN)
    for entry in historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != transition.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V48 root drifted")

    raw = CURRENT_TRANSITION_V49.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V49_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V49 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V49 transition is not canonical")
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V49 transition") from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v49"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v48.json",
            "sha256": CURRENT_TRANSITION_V48_SHA256,
        }
        or current.get("policy") != transition.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V49 policy drifted")
    current_historical = current.get("historical_bindings")
    current_successors = current.get("named_successors")
    if (
        type(current_historical) is not list
        or type(current_successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in current_historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in transition["historical_bindings"]
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in current_successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in transition["named_successors"]
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V49 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V49_DOMAIN)
    for entry in current_historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V49 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in current_successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V49 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V49 root drifted")
    return current


@functools.lru_cache(maxsize=1)
def load_current_successor_transition_v51() -> dict[str, object]:
    """Authenticate additive Phase 5 V51 over immutable V50 current evidence."""

    predecessor_raw = CURRENT_TRANSITION_V50.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V50_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V50 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V50 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V50 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v50"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V50 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if type(predecessor_historical) is not list or type(predecessor_successors) is not list:
        raise Phase5ExitRetirementError("Phase 5 V50 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V50_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V50 predecessor root drifted")

    raw = CURRENT_TRANSITION_V51.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V51_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V51 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V51 transition is not canonical")
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V51 transition") from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v51"
        or current.get("issued_at") != "2026-08-11T13:05:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v50.json",
            "sha256": CURRENT_TRANSITION_V50_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V51 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V51 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V51_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V51 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V51 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V51 root drifted")
    return current


def load_current_successor_transition_v52() -> dict[str, object]:
    """Authenticate additive Phase 5 V52 over immutable V51 current evidence."""

    predecessor_raw = CURRENT_TRANSITION_V51.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V51_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V51 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V51 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V51 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v51"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V51 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if type(predecessor_historical) is not list or type(predecessor_successors) is not list:
        raise Phase5ExitRetirementError("Phase 5 V51 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V51_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V51 predecessor root drifted")

    raw = CURRENT_TRANSITION_V52.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V52_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V52 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V52 transition is not canonical")
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V52 transition") from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v52"
        or current.get("issued_at") != "2026-08-17T22:37:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v51.json",
            "sha256": CURRENT_TRANSITION_V51_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V52 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V52 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V52_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V52 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V52 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V52 root drifted")
    return current


def load_current_successor_transition_v53() -> dict[str, object]:
    """Authenticate additive Phase 5 V53 over immutable V52 current evidence."""

    predecessor_raw = CURRENT_TRANSITION_V52.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V52_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V52 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V52 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V52 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v52"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V52 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if type(predecessor_historical) is not list or type(predecessor_successors) is not list:
        raise Phase5ExitRetirementError("Phase 5 V52 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V52_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V52 predecessor root drifted")

    raw = CURRENT_TRANSITION_V53.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V53_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V53 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V53 transition is not canonical")
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V53 transition") from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v53"
        or current.get("issued_at") != "2026-08-18T08:36:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v52.json",
            "sha256": CURRENT_TRANSITION_V52_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V53 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V53 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V53_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V53 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V53 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V53 root drifted")
    return current


def load_current_successor_transition() -> dict[str, object]:
    """Authenticate additive Phase 5 V54 over immutable V53 current evidence."""

    predecessor_raw = CURRENT_TRANSITION_V53.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V53_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V53 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V53 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V53 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v53"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V53 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if type(predecessor_historical) is not list or type(predecessor_successors) is not list:
        raise Phase5ExitRetirementError("Phase 5 V53 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V53_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V53 predecessor root drifted")

    raw = CURRENT_TRANSITION_V54.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V54_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V54 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("current Phase 5 V54 transition is not canonical")
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid current Phase 5 V54 transition") from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v54"
        or current.get("issued_at") != "2026-08-19T13:25:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v53.json",
            "sha256": CURRENT_TRANSITION_V53_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V54 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V54 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V54_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V54 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V54 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V54 root drifted")
    return current


def load_current_successor_transition() -> dict[str, object]:
    """Authenticate additive Phase 5 V55 over immutable V54 current evidence.

    V54 recorded ``ui.py``, ``main.py`` and ``dashboard/server.py`` as
    tombstoned historical artifacts whose *current* form it tracked by digest.
    Those current forms have since advanced: the approval prompt now surfaces
    its window before blocking, because a prompt the owner never saw timed out
    and was recorded as a refusal; and the dashboard accepts a mesh address so
    a phone can reach this host from outside the LAN.

    V54 stays immutable and its root stays reproducible from its own recorded
    values, so nothing historical is rewritten.  Only V55 is measured against
    what is on disk, and it is bound under its own domain so a V55 root can
    never be mistaken for its predecessor's.
    """
    predecessor_raw = CURRENT_TRANSITION_V54.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V54_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V54 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V54 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V54 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v54"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V54 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if (
        type(predecessor_historical) is not list
        or type(predecessor_successors) is not list
    ):
        raise Phase5ExitRetirementError("Phase 5 V54 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V54_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V54 predecessor root drifted")

    raw = CURRENT_TRANSITION_V55.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V55_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V55 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError(
            "current Phase 5 V55 transition is not canonical"
        )
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid current Phase 5 V55 transition"
        ) from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v55"
        or current.get("issued_at") != "2026-08-22T00:30:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v54.json",
            "sha256": CURRENT_TRANSITION_V54_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V55 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V55 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V55_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V55 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V55 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V55 root drifted")
    return current


def load_current_successor_transition() -> dict[str, object]:
    """Authenticate additive Phase 5 V56 over immutable V55 current evidence.

    V55 recorded ``ui.py``, ``main.py`` and ``dashboard/server.py`` as
    tombstoned historical artifacts whose *current* form it tracked by digest.
    Those current forms have since advanced: the approval prompt now surfaces
    its window before blocking, because a prompt the owner never saw timed out
    and was recorded as a refusal; and the dashboard accepts a mesh address so
    a phone can reach this host from outside the LAN.

    V55 stays immutable and its root stays reproducible from its own recorded
    values, so nothing historical is rewritten.  Only V56 is measured against
    what is on disk, and it is bound under its own domain so a V56 root can
    never be mistaken for its predecessor's.
    """
    predecessor_raw = CURRENT_TRANSITION_V55.read_bytes()
    if _sha(predecessor_raw) != CURRENT_TRANSITION_V55_SHA256:
        raise Phase5ExitRetirementError("Phase 5 V55 predecessor digest drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("Phase 5 V55 predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 V55 predecessor") from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema")
        != "onyx.phase5-current-successor-transition.v55"
        or predecessor.get("predecessor_clock_anomaly") is not None
    ):
        raise Phase5ExitRetirementError("Phase 5 V55 predecessor contract drifted")
    predecessor_historical = predecessor.get("historical_bindings")
    predecessor_successors = predecessor.get("named_successors")
    if (
        type(predecessor_historical) is not list
        or type(predecessor_successors) is not list
    ):
        raise Phase5ExitRetirementError("Phase 5 V55 predecessor entries drifted")
    predecessor_root = hashlib.sha256()
    predecessor_root.update(CURRENT_TRANSITION_V55_DOMAIN)
    for entry in predecessor_historical:
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(predecessor_root, value)
    for entry in predecessor_successors:
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(predecessor_root, value)
    if predecessor_root.hexdigest() != predecessor.get("current_root_sha256"):
        raise Phase5ExitRetirementError("Phase 5 V55 predecessor root drifted")

    raw = CURRENT_TRANSITION_V56.read_bytes()
    if _sha(raw) != CURRENT_TRANSITION_V56_SHA256:
        raise Phase5ExitRetirementError("current Phase 5 V56 transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError(
            "current Phase 5 V56 transition is not canonical"
        )
    try:
        current = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid current Phase 5 V56 transition"
        ) from error
    if (
        type(current) is not dict
        or current.get("schema") != "onyx.phase5-current-successor-transition.v56"
        or current.get("issued_at") != "2026-08-22T12:30:00-04:00"
        or current.get("predecessor_clock_anomaly") is not None
        or current.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v55.json",
            "sha256": CURRENT_TRANSITION_V55_SHA256,
        }
        or current.get("policy") != predecessor.get("policy")
    ):
        raise Phase5ExitRetirementError("current Phase 5 V56 policy drifted")
    historical = current.get("historical_bindings")
    successors = current.get("named_successors")
    if (
        type(historical) is not list
        or type(successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in predecessor_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in predecessor_successors
        ]
    ):
        raise Phase5ExitRetirementError("current Phase 5 V56 identity drifted")
    current_root = hashlib.sha256()
    current_root.update(CURRENT_TRANSITION_V56_DOMAIN)
    for entry in historical:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V56 historical target drifted: {entry.get('path')}"
            )
        for value in (
            "historical-binding",
            entry["path"],
            entry["historical_sha256"],
            entry["current_sha256"],
            entry["state"],
            entry["successor"],
        ):
            _frame(current_root, value)
    for entry in successors:
        if _sha(_read(PROJECT, entry["path"])) != entry.get("current_sha256"):
            raise Phase5ExitRetirementError(
                f"current Phase 5 V56 named successor drifted: {entry.get('path')}"
            )
        for value in (
            "named-successor",
            entry["path"],
            entry["predecessor_sha256"],
            entry["current_sha256"],
        ):
            _frame(current_root, value)
    if current_root.hexdigest() != current.get("current_root_sha256"):
        raise Phase5ExitRetirementError("current Phase 5 V56 root drifted")
    return current


@functools.lru_cache(maxsize=1)
def load_release_workflow_transition_v31() -> dict[str, object]:
    """Authenticate release V31 while preserving V30 through V1 and Phase 5 V9."""

    load_current_successor_transition()
    verify_release_runtime_closure(PROJECT)
    raw = RELEASE_TRANSITION_V31.read_bytes()
    actual_transition_sha = _sha(raw)
    if actual_transition_sha != RELEASE_TRANSITION_V31_SHA256:
        raise Phase5ExitRetirementError("release workflow transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("release workflow transition is not canonical")
    try:
        transition = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow transition"
        ) from error
    if type(transition) is not dict or set(transition) != {
        "schema",
        "issued_at",
        "predecessor",
        "policy",
        "current_release_paths",
        "current_root_sha256",
    }:
        raise Phase5ExitRetirementError("release workflow transition contract drifted")
    if (
        transition["schema"] != "onyx.release-workflow-transition.v31"
        or transition["predecessor"]
        != {
            "path": "tests/fixtures/release_workflow_transition_v30.json",
            "sha256": RELEASE_TRANSITION_PREDECESSOR_SHA256,
        }
        or transition["policy"]
        != {
            "predecessor_is_immutable": True,
            "historical_hashes_are_rebound": False,
            "current_release_paths_are_sha256_bound": True,
            "unsigned_windows_may_be_formal": False,
            "diagnostic_candidates_may_be_published": False,
        }
        or not _valid_sha(transition["current_root_sha256"])
    ):
        raise Phase5ExitRetirementError("release workflow transition policy drifted")
    predecessor_raw = RELEASE_TRANSITION_PREDECESSOR.read_bytes()
    if _sha(predecessor_raw) != RELEASE_TRANSITION_PREDECESSOR_SHA256:
        raise Phase5ExitRetirementError("release workflow predecessor drifted")
    if (
        predecessor_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_raw
        or not predecessor_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError("release workflow predecessor is not canonical")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow predecessor"
        ) from error
    if (
        type(predecessor) is not dict
        or predecessor.get("schema") != "onyx.release-workflow-transition.v30"
        or predecessor.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v29.json",
            "sha256": RELEASE_TRANSITION_V29_SHA256,
        }
        or predecessor.get("policy") != transition["policy"]
        or _recorded_release_root(predecessor, RELEASE_TRANSITION_V30_DOMAIN)
        != predecessor.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError("release workflow predecessor contract drifted")
    release_v29_raw = RELEASE_TRANSITION_V29.read_bytes()
    if _sha(release_v29_raw) != RELEASE_TRANSITION_V29_SHA256:
        raise Phase5ExitRetirementError("release workflow V29 predecessor drifted")
    if (
        release_v29_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v29_raw
        or not release_v29_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V29 predecessor is not canonical"
        )
    try:
        release_v29 = json.loads(release_v29_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V29 predecessor"
        ) from error
    if (
        type(release_v29) is not dict
        or release_v29.get("schema") != "onyx.release-workflow-transition.v29"
        or release_v29.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v28.json",
            "sha256": RELEASE_TRANSITION_V28_SHA256,
        }
        or release_v29.get("policy") != transition["policy"]
        or _recorded_release_root(release_v29, RELEASE_TRANSITION_V29_DOMAIN)
        != release_v29.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V29 predecessor contract drifted"
        )
    release_v28_raw = RELEASE_TRANSITION_V28.read_bytes()
    if _sha(release_v28_raw) != RELEASE_TRANSITION_V28_SHA256:
        raise Phase5ExitRetirementError("release workflow V28 predecessor drifted")
    if (
        release_v28_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v28_raw
        or not release_v28_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V28 predecessor is not canonical"
        )
    try:
        release_v28 = json.loads(release_v28_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V28 predecessor"
        ) from error
    if (
        type(release_v28) is not dict
        or release_v28.get("schema") != "onyx.release-workflow-transition.v28"
        or release_v28.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v27.json",
            "sha256": RELEASE_TRANSITION_V27_SHA256,
        }
        or release_v28.get("policy") != transition["policy"]
        or _recorded_release_root(release_v28, RELEASE_TRANSITION_V28_DOMAIN)
        != release_v28.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V28 predecessor contract drifted"
        )
    release_v27_raw = RELEASE_TRANSITION_V27.read_bytes()
    if _sha(release_v27_raw) != RELEASE_TRANSITION_V27_SHA256:
        raise Phase5ExitRetirementError("release workflow V27 predecessor drifted")
    if (
        release_v27_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v27_raw
        or not release_v27_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V27 predecessor is not canonical"
        )
    try:
        release_v27 = json.loads(release_v27_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V27 predecessor"
        ) from error
    if (
        type(release_v27) is not dict
        or release_v27.get("schema") != "onyx.release-workflow-transition.v27"
        or release_v27.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v26.json",
            "sha256": RELEASE_TRANSITION_V26_SHA256,
        }
        or release_v27.get("policy") != transition["policy"]
        or _recorded_release_root(release_v27, RELEASE_TRANSITION_V27_DOMAIN)
        != release_v27.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V27 predecessor contract drifted"
        )
    release_v26_raw = RELEASE_TRANSITION_V26.read_bytes()
    if _sha(release_v26_raw) != RELEASE_TRANSITION_V26_SHA256:
        raise Phase5ExitRetirementError("release workflow V26 predecessor drifted")
    if (
        release_v26_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v26_raw
        or not release_v26_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V26 predecessor is not canonical"
        )
    try:
        release_v26 = json.loads(release_v26_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V26 predecessor"
        ) from error
    if (
        type(release_v26) is not dict
        or release_v26.get("schema") != "onyx.release-workflow-transition.v26"
        or release_v26.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v25.json",
            "sha256": RELEASE_TRANSITION_V25_SHA256,
        }
        or release_v26.get("policy") != transition["policy"]
        or _recorded_release_root(release_v26, RELEASE_TRANSITION_V26_DOMAIN)
        != release_v26.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V26 predecessor contract drifted"
        )
    release_v25_raw = RELEASE_TRANSITION_V25.read_bytes()
    if _sha(release_v25_raw) != RELEASE_TRANSITION_V25_SHA256:
        raise Phase5ExitRetirementError("release workflow V25 predecessor drifted")
    if (
        release_v25_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v25_raw
        or not release_v25_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V25 predecessor is not canonical"
        )
    try:
        release_v25 = json.loads(release_v25_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V25 predecessor"
        ) from error
    if (
        type(release_v25) is not dict
        or release_v25.get("schema") != "onyx.release-workflow-transition.v25"
        or release_v25.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v24.json",
            "sha256": RELEASE_TRANSITION_V24_SHA256,
        }
        or release_v25.get("policy") != transition["policy"]
        or _recorded_release_root(release_v25, RELEASE_TRANSITION_V25_DOMAIN)
        != release_v25.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V25 predecessor contract drifted"
        )
    release_v24_raw = RELEASE_TRANSITION_V24.read_bytes()
    if _sha(release_v24_raw) != RELEASE_TRANSITION_V24_SHA256:
        raise Phase5ExitRetirementError("release workflow V24 predecessor drifted")
    if (
        release_v24_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v24_raw
        or not release_v24_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V24 predecessor is not canonical"
        )
    try:
        release_v24 = json.loads(release_v24_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V24 predecessor"
        ) from error
    if (
        type(release_v24) is not dict
        or release_v24.get("schema") != "onyx.release-workflow-transition.v24"
        or release_v24.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v23.json",
            "sha256": RELEASE_TRANSITION_V23_SHA256,
        }
        or release_v24.get("policy") != transition["policy"]
        or _recorded_release_root(release_v24, RELEASE_TRANSITION_V24_DOMAIN)
        != release_v24.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V24 predecessor contract drifted"
        )
    release_v23_raw = RELEASE_TRANSITION_V23.read_bytes()
    if _sha(release_v23_raw) != RELEASE_TRANSITION_V23_SHA256:
        raise Phase5ExitRetirementError("release workflow V23 predecessor drifted")
    if (
        release_v23_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v23_raw
        or not release_v23_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V23 predecessor is not canonical"
        )
    try:
        release_v23 = json.loads(release_v23_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V23 predecessor"
        ) from error
    if (
        type(release_v23) is not dict
        or release_v23.get("schema") != "onyx.release-workflow-transition.v23"
        or release_v23.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v22.json",
            "sha256": RELEASE_TRANSITION_V22_SHA256,
        }
        or release_v23.get("policy") != transition["policy"]
        or _recorded_release_root(release_v23, RELEASE_TRANSITION_V23_DOMAIN)
        != release_v23.get("current_root_sha256")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V23 predecessor contract drifted"
        )
    release_v22_raw = RELEASE_TRANSITION_V22.read_bytes()
    if _sha(release_v22_raw) != RELEASE_TRANSITION_V22_SHA256:
        raise Phase5ExitRetirementError("release workflow V22 predecessor drifted")
    if (
        release_v22_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v22_raw
        or not release_v22_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V22 predecessor is not canonical"
        )
    try:
        release_v22 = json.loads(release_v22_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V22 predecessor"
        ) from error
    if (
        type(release_v22) is not dict
        or release_v22.get("schema") != "onyx.release-workflow-transition.v22"
        or release_v22.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v21.json",
            "sha256": RELEASE_TRANSITION_V21_SHA256,
        }
        or release_v22.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V22 predecessor contract drifted"
        )
    release_v21_raw = RELEASE_TRANSITION_V21.read_bytes()
    if _sha(release_v21_raw) != RELEASE_TRANSITION_V21_SHA256:
        raise Phase5ExitRetirementError("release workflow V21 predecessor drifted")
    if (
        release_v21_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v21_raw
        or not release_v21_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V21 predecessor is not canonical"
        )
    try:
        release_v21 = json.loads(release_v21_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V21 predecessor"
        ) from error
    if (
        type(release_v21) is not dict
        or release_v21.get("schema") != "onyx.release-workflow-transition.v21"
        or release_v21.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v20.json",
            "sha256": RELEASE_TRANSITION_V20_SHA256,
        }
        or release_v21.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V21 predecessor contract drifted"
        )
    release_v20_raw = RELEASE_TRANSITION_V20.read_bytes()
    if _sha(release_v20_raw) != RELEASE_TRANSITION_V20_SHA256:
        raise Phase5ExitRetirementError("release workflow V20 predecessor drifted")
    if (
        release_v20_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v20_raw
        or not release_v20_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V20 predecessor is not canonical"
        )
    try:
        release_v20 = json.loads(release_v20_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V20 predecessor"
        ) from error
    if (
        type(release_v20) is not dict
        or release_v20.get("schema") != "onyx.release-workflow-transition.v20"
        or release_v20.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v19.json",
            "sha256": RELEASE_TRANSITION_V19_SHA256,
        }
        or release_v20.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V20 predecessor contract drifted"
        )
    release_v19_raw = RELEASE_TRANSITION_V19.read_bytes()
    if _sha(release_v19_raw) != RELEASE_TRANSITION_V19_SHA256:
        raise Phase5ExitRetirementError("release workflow V19 predecessor drifted")
    if (
        release_v19_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v19_raw
        or not release_v19_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V19 predecessor is not canonical"
        )
    try:
        release_v19 = json.loads(release_v19_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V19 predecessor"
        ) from error
    if (
        type(release_v19) is not dict
        or release_v19.get("schema") != "onyx.release-workflow-transition.v19"
        or release_v19.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v18.json",
            "sha256": RELEASE_TRANSITION_V18_SHA256,
        }
        or release_v19.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V19 predecessor contract drifted"
        )
    release_v18_raw = RELEASE_TRANSITION_V18.read_bytes()
    if _sha(release_v18_raw) != RELEASE_TRANSITION_V18_SHA256:
        raise Phase5ExitRetirementError("release workflow V18 predecessor drifted")
    if (
        release_v18_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v18_raw
        or not release_v18_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V18 predecessor is not canonical"
        )
    try:
        release_v18 = json.loads(release_v18_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V18 predecessor"
        ) from error
    if (
        type(release_v18) is not dict
        or release_v18.get("schema") != "onyx.release-workflow-transition.v18"
        or release_v18.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v17.json",
            "sha256": RELEASE_TRANSITION_V17_SHA256,
        }
        or release_v18.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V18 predecessor contract drifted"
        )
    release_v17_raw = RELEASE_TRANSITION_V17.read_bytes()
    if _sha(release_v17_raw) != RELEASE_TRANSITION_V17_SHA256:
        raise Phase5ExitRetirementError("release workflow V17 predecessor drifted")
    if (
        release_v17_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v17_raw
        or not release_v17_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V17 predecessor is not canonical"
        )
    try:
        release_v17 = json.loads(release_v17_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V17 predecessor"
        ) from error
    if (
        type(release_v17) is not dict
        or release_v17.get("schema") != "onyx.release-workflow-transition.v17"
        or release_v17.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v16.json",
            "sha256": RELEASE_TRANSITION_V16_SHA256,
        }
        or release_v17.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V17 predecessor contract drifted"
        )
    release_v16_raw = RELEASE_TRANSITION_V16.read_bytes()
    if _sha(release_v16_raw) != RELEASE_TRANSITION_V16_SHA256:
        raise Phase5ExitRetirementError("release workflow V16 predecessor drifted")
    if (
        release_v16_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v16_raw
        or not release_v16_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V16 predecessor is not canonical"
        )
    try:
        release_v16 = json.loads(release_v16_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V16 predecessor"
        ) from error
    if (
        type(release_v16) is not dict
        or release_v16.get("schema") != "onyx.release-workflow-transition.v16"
        or release_v16.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v15.json",
            "sha256": RELEASE_TRANSITION_V15_SHA256,
        }
        or release_v16.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V16 predecessor contract drifted"
        )
    release_v15_raw = RELEASE_TRANSITION_V15.read_bytes()
    if _sha(release_v15_raw) != RELEASE_TRANSITION_V15_SHA256:
        raise Phase5ExitRetirementError("release workflow V15 predecessor drifted")
    if (
        release_v15_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v15_raw
        or not release_v15_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V15 predecessor is not canonical"
        )
    try:
        release_v15 = json.loads(release_v15_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V15 predecessor"
        ) from error
    if (
        type(release_v15) is not dict
        or release_v15.get("schema") != "onyx.release-workflow-transition.v15"
        or release_v15.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v14.json",
            "sha256": RELEASE_TRANSITION_V14_SHA256,
        }
        or release_v15.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V15 predecessor contract drifted"
        )
    release_v14_raw = RELEASE_TRANSITION_V14.read_bytes()
    if _sha(release_v14_raw) != RELEASE_TRANSITION_V14_SHA256:
        raise Phase5ExitRetirementError("release workflow V14 predecessor drifted")
    if (
        release_v14_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v14_raw
        or not release_v14_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V14 predecessor is not canonical"
        )
    try:
        release_v14 = json.loads(release_v14_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V14 predecessor"
        ) from error
    if (
        type(release_v14) is not dict
        or release_v14.get("schema") != "onyx.release-workflow-transition.v14"
        or release_v14.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v13.json",
            "sha256": RELEASE_TRANSITION_V13_SHA256,
        }
        or release_v14.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V14 predecessor contract drifted"
        )
    release_v13_raw = RELEASE_TRANSITION_V13.read_bytes()
    if _sha(release_v13_raw) != RELEASE_TRANSITION_V13_SHA256:
        raise Phase5ExitRetirementError("release workflow V13 predecessor drifted")
    if (
        release_v13_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v13_raw
        or not release_v13_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V13 predecessor is not canonical"
        )
    try:
        release_v13 = json.loads(release_v13_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V13 predecessor"
        ) from error
    if (
        type(release_v13) is not dict
        or release_v13.get("schema") != "onyx.release-workflow-transition.v13"
        or release_v13.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v12.json",
            "sha256": RELEASE_TRANSITION_V12_SHA256,
        }
        or release_v13.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V13 predecessor contract drifted"
        )
    release_v12_raw = RELEASE_TRANSITION_V12.read_bytes()
    if _sha(release_v12_raw) != RELEASE_TRANSITION_V12_SHA256:
        raise Phase5ExitRetirementError("release workflow V12 predecessor drifted")
    if (
        release_v12_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v12_raw
        or not release_v12_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V12 predecessor is not canonical"
        )
    try:
        release_v12 = json.loads(release_v12_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V12 predecessor"
        ) from error
    if (
        type(release_v12) is not dict
        or release_v12.get("schema") != "onyx.release-workflow-transition.v12"
        or release_v12.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v11.json",
            "sha256": RELEASE_TRANSITION_V11_SHA256,
        }
        or release_v12.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V12 predecessor contract drifted"
        )
    release_v11_raw = RELEASE_TRANSITION_V11.read_bytes()
    if _sha(release_v11_raw) != RELEASE_TRANSITION_V11_SHA256:
        raise Phase5ExitRetirementError("release workflow V11 predecessor drifted")
    if (
        release_v11_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v11_raw
        or not release_v11_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V11 predecessor is not canonical"
        )
    try:
        release_v11 = json.loads(release_v11_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V11 predecessor"
        ) from error
    if (
        type(release_v11) is not dict
        or release_v11.get("schema") != "onyx.release-workflow-transition.v11"
        or release_v11.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v10.json",
            "sha256": RELEASE_TRANSITION_V10_SHA256,
        }
        or release_v11.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V11 predecessor contract drifted"
        )
    release_v10_raw = RELEASE_TRANSITION_V10.read_bytes()
    if _sha(release_v10_raw) != RELEASE_TRANSITION_V10_SHA256:
        raise Phase5ExitRetirementError("release workflow V10 predecessor drifted")
    if (
        release_v10_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v10_raw
        or not release_v10_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V10 predecessor is not canonical"
        )
    try:
        release_v10 = json.loads(release_v10_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V10 predecessor"
        ) from error
    if (
        type(release_v10) is not dict
        or release_v10.get("schema") != "onyx.release-workflow-transition.v10"
        or release_v10.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v9.json",
            "sha256": RELEASE_TRANSITION_V9_SHA256,
        }
        or release_v10.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V10 predecessor contract drifted"
        )
    release_v9_raw = RELEASE_TRANSITION_V9.read_bytes()
    if _sha(release_v9_raw) != RELEASE_TRANSITION_V9_SHA256:
        raise Phase5ExitRetirementError("release workflow V9 predecessor drifted")
    if (
        release_v9_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v9_raw
        or not release_v9_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V9 predecessor is not canonical"
        )
    try:
        release_v9 = json.loads(release_v9_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V9 predecessor"
        ) from error
    if (
        type(release_v9) is not dict
        or release_v9.get("schema") != "onyx.release-workflow-transition.v9"
        or release_v9.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v8.json",
            "sha256": RELEASE_TRANSITION_V8_SHA256,
        }
        or release_v9.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V9 predecessor contract drifted"
        )
    release_v8_raw = RELEASE_TRANSITION_V8.read_bytes()
    if _sha(release_v8_raw) != RELEASE_TRANSITION_V8_SHA256:
        raise Phase5ExitRetirementError("release workflow V8 predecessor drifted")
    if (
        release_v8_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v8_raw
        or not release_v8_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V8 predecessor is not canonical"
        )
    try:
        release_v8 = json.loads(release_v8_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V8 predecessor"
        ) from error
    if (
        type(release_v8) is not dict
        or release_v8.get("schema") != "onyx.release-workflow-transition.v8"
        or release_v8.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v7.json",
            "sha256": RELEASE_TRANSITION_V7_SHA256,
        }
        or release_v8.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V8 predecessor contract drifted"
        )
    release_v7_raw = RELEASE_TRANSITION_V7.read_bytes()
    if _sha(release_v7_raw) != RELEASE_TRANSITION_V7_SHA256:
        raise Phase5ExitRetirementError("release workflow V7 predecessor drifted")
    if (
        release_v7_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v7_raw
        or not release_v7_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V7 predecessor is not canonical"
        )
    try:
        release_v7 = json.loads(release_v7_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V7 predecessor"
        ) from error
    if (
        type(release_v7) is not dict
        or release_v7.get("schema") != "onyx.release-workflow-transition.v7"
        or release_v7.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v6.json",
            "sha256": RELEASE_TRANSITION_V6_SHA256,
        }
        or release_v7.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V7 predecessor contract drifted"
        )
    release_v6_raw = RELEASE_TRANSITION_V6.read_bytes()
    if _sha(release_v6_raw) != RELEASE_TRANSITION_V6_SHA256:
        raise Phase5ExitRetirementError("release workflow V6 predecessor drifted")
    if (
        release_v6_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v6_raw
        or not release_v6_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V6 predecessor is not canonical"
        )
    try:
        release_v6 = json.loads(release_v6_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V6 predecessor"
        ) from error
    if (
        type(release_v6) is not dict
        or release_v6.get("schema") != "onyx.release-workflow-transition.v6"
        or release_v6.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v5.json",
            "sha256": RELEASE_TRANSITION_V5_SHA256,
        }
        or release_v6.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V6 predecessor contract drifted"
        )
    release_v5_raw = RELEASE_TRANSITION_V5.read_bytes()
    if _sha(release_v5_raw) != RELEASE_TRANSITION_V5_SHA256:
        raise Phase5ExitRetirementError("release workflow V5 predecessor drifted")
    if (
        release_v5_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v5_raw
        or not release_v5_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V5 predecessor is not canonical"
        )
    try:
        release_v5 = json.loads(release_v5_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V5 predecessor"
        ) from error
    if (
        type(release_v5) is not dict
        or release_v5.get("schema") != "onyx.release-workflow-transition.v5"
        or release_v5.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v4.json",
            "sha256": RELEASE_TRANSITION_V4_SHA256,
        }
        or release_v5.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V5 predecessor contract drifted"
        )
    release_v4_raw = RELEASE_TRANSITION_V4.read_bytes()
    if _sha(release_v4_raw) != RELEASE_TRANSITION_V4_SHA256:
        raise Phase5ExitRetirementError("release workflow V4 predecessor drifted")
    if (
        release_v4_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v4_raw
        or not release_v4_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V4 predecessor is not canonical"
        )
    try:
        release_v4 = json.loads(release_v4_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V4 predecessor"
        ) from error
    if (
        type(release_v4) is not dict
        or release_v4.get("schema") != "onyx.release-workflow-transition.v4"
        or release_v4.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v3.json",
            "sha256": RELEASE_TRANSITION_V3_SHA256,
        }
        or release_v4.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V4 predecessor contract drifted"
        )
    release_v3_raw = RELEASE_TRANSITION_V3.read_bytes()
    if _sha(release_v3_raw) != RELEASE_TRANSITION_V3_SHA256:
        raise Phase5ExitRetirementError("release workflow V3 predecessor drifted")
    if (
        release_v3_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v3_raw
        or not release_v3_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V3 predecessor is not canonical"
        )
    try:
        release_v3 = json.loads(release_v3_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V3 predecessor"
        ) from error
    if (
        type(release_v3) is not dict
        or release_v3.get("schema") != "onyx.release-workflow-transition.v3"
        or release_v3.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v2.json",
            "sha256": RELEASE_TRANSITION_V2_SHA256,
        }
        or release_v3.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V3 predecessor contract drifted"
        )
    release_v2_raw = RELEASE_TRANSITION_V2.read_bytes()
    if _sha(release_v2_raw) != RELEASE_TRANSITION_V2_SHA256:
        raise Phase5ExitRetirementError("release workflow V2 predecessor drifted")
    if (
        release_v2_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v2_raw
        or not release_v2_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V2 predecessor is not canonical"
        )
    try:
        release_v2 = json.loads(release_v2_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V2 predecessor"
        ) from error
    if (
        type(release_v2) is not dict
        or release_v2.get("schema") != "onyx.release-workflow-transition.v2"
        or release_v2.get("predecessor")
        != {
            "path": "tests/fixtures/release_workflow_transition_v1.json",
            "sha256": RELEASE_TRANSITION_V1_SHA256,
        }
        or release_v2.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V2 predecessor contract drifted"
        )
    release_v1_raw = RELEASE_TRANSITION_V1.read_bytes()
    if _sha(release_v1_raw) != RELEASE_TRANSITION_V1_SHA256:
        raise Phase5ExitRetirementError("release workflow V1 predecessor drifted")
    if (
        release_v1_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in release_v1_raw
        or not release_v1_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "release workflow V1 predecessor is not canonical"
        )
    try:
        release_v1 = json.loads(release_v1_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid release workflow V1 predecessor"
        ) from error
    if (
        type(release_v1) is not dict
        or release_v1.get("schema") != "onyx.release-workflow-transition.v1"
        or release_v1.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v9.json",
            "sha256": TRANSITION_SHA256,
        }
        or release_v1.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "release workflow V1 predecessor contract drifted"
        )
    if _sha(TRANSITION.read_bytes()) != TRANSITION_SHA256:
        raise Phase5ExitRetirementError("Phase 5 successor transition drifted")
    entries = transition["current_release_paths"]
    if type(entries) is not list or not entries:
        raise Phase5ExitRetirementError("release workflow transition is empty")
    predecessor_hashes = {
        entry["path"]: entry["sha256"] for entry in predecessor["current_release_paths"]
    }
    # Historical V31 paths may now have exact V32/V33 successors.  Delegate
    # those deltas to the independent V33 authority without rebinding either
    # immutable predecessor.
    from scripts.verify_release_workflow_v33 import verify_release_workflow_v33

    verified_current = verify_release_workflow_v33(PROJECT)
    successor_hashes = {
        entry["path"]: entry["sha256"]
        for entry in verified_current["predecessor"]["current_release_paths"]
    }
    successor_hashes.update(
        {
            entry["path"]: entry["sha256"]
            for entry in verified_current["transition"]["current_release_paths"]
        }
    )
    paths: list[str] = []
    hasher = hashlib.sha256()
    hasher.update(RELEASE_TRANSITION_V31_DOMAIN)
    for value in (
        transition["predecessor"]["path"],
        transition["predecessor"]["sha256"],
    ):
        _frame(hasher, value)
    for entry in entries:
        if (
            type(entry) is not dict
            or set(entry) != {"path", "sha256"}
            or not _valid_sha(entry.get("sha256"))
        ):
            raise Phase5ExitRetirementError(
                "release workflow transition entry is malformed"
            )
        relative = entry["path"]
        _relative(relative)
        paths.append(relative)
        actual_sha256 = _sha(_read(PROJECT, relative))
        if (
            actual_sha256 != entry["sha256"]
            and successor_hashes.get(relative) != actual_sha256
        ):
            raise Phase5ExitRetirementError(
                f"current release policy target drifted: {relative}"
            )
        if predecessor_hashes.get(relative) == entry["sha256"]:
            raise Phase5ExitRetirementError(
                f"release workflow delta contains unchanged target: {relative}"
            )
        _frame(hasher, relative)
        _frame(hasher, entry["sha256"])
    if paths != sorted(paths) or len(paths) != len(set(paths)):
        raise Phase5ExitRetirementError("release workflow transition paths drifted")
    if hasher.hexdigest() != transition["current_root_sha256"]:
        raise Phase5ExitRetirementError("release workflow transition root drifted")
    return transition


def verify_release_runtime_closure(project: Path = PROJECT) -> dict[str, object]:
    """Authenticate the full-source V30 closure used to curate frozen data."""

    from core.onyx_hud_current_acceptance_v31 import verify_current_hud_acceptance

    return verify_current_hud_acceptance(Path(project))


@functools.lru_cache(maxsize=1)
def load_release_workflow_transition() -> dict[str, object]:
    """Select the independently authenticated current Release V53 record."""

    from scripts.verify_release_workflow_v53 import verify_release_workflow_v53

    return verify_release_workflow_v53(PROJECT)["transition"]


@functools.lru_cache(maxsize=1)
def load_successor_transition() -> dict[str, object]:
    """Authenticate immutable V9 while allowing only V19-bound current bytes."""

    current_transition = load_current_successor_transition()
    current_historical_digests = {
        entry["path"]: entry["current_sha256"]
        for entry in current_transition["historical_bindings"]
    }
    current_successor_digests = {
        entry["path"]: entry["current_sha256"]
        for entry in current_transition["named_successors"]
    }
    release_transition = load_release_workflow_transition()
    release_digests = {
        entry["path"]: entry["sha256"]
        for entry in release_transition["current_release_paths"]
    }
    raw = TRANSITION.read_bytes()
    if _sha(raw) != TRANSITION_SHA256:
        raise Phase5ExitRetirementError("Phase 5 successor transition drifted")
    if raw.startswith(b"\xef\xbb\xbf") or b"\r" in raw or not raw.endswith(b"\n"):
        raise Phase5ExitRetirementError("Phase 5 successor transition is not canonical")
    try:
        transition = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid Phase 5 successor transition"
        ) from error
    if type(transition) is not dict or set(transition) != {
        "schema",
        "issued_at",
        "predecessor",
        "policy",
        "historical_bindings",
        "named_successors",
        "current_root_sha256",
    }:
        raise Phase5ExitRetirementError("Phase 5 successor transition contract drifted")
    if (
        transition["schema"] != "onyx.phase5-current-successor-transition.v9"
        or transition["policy"]
        != {
            "historical_bindings_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "predecessor_root_must_remain_reproducible": True,
            "current_paths_are_sha256_bound": True,
            "named_successors_are_sha256_bound": True,
            "runtime_authority_changes": False,
        }
        or transition["predecessor"]
        != {
            "path": "tests/fixtures/phase5_current_successor_transition_v8.json",
            "sha256": TRANSITION_PREDECESSOR_SHA256,
        }
        or not _valid_sha(transition["current_root_sha256"])
    ):
        raise Phase5ExitRetirementError("Phase 5 successor transition policy drifted")
    predecessor_transition_raw = TRANSITION_PREDECESSOR.read_bytes()
    if _sha(predecessor_transition_raw) != TRANSITION_PREDECESSOR_SHA256:
        raise Phase5ExitRetirementError("Phase 5 successor predecessor drifted")
    if (
        predecessor_transition_raw.startswith(b"\xef\xbb\xbf")
        or b"\r" in predecessor_transition_raw
        or not predecessor_transition_raw.endswith(b"\n")
    ):
        raise Phase5ExitRetirementError(
            "Phase 5 successor predecessor is not canonical"
        )
    try:
        predecessor_transition = json.loads(predecessor_transition_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid Phase 5 successor predecessor"
        ) from error
    if (
        type(predecessor_transition) is not dict
        or predecessor_transition.get("schema")
        != "onyx.phase5-current-successor-transition.v8"
        or predecessor_transition.get("predecessor")
        != {
            "path": "tests/fixtures/phase5_exit_retirement_v1.json",
            "sha256": RECORD_SHA256,
        }
        or predecessor_transition.get("policy") != transition["policy"]
    ):
        raise Phase5ExitRetirementError(
            "Phase 5 successor predecessor contract drifted"
        )
    predecessor_raw = RECORD.read_bytes()
    if _sha(predecessor_raw) != RECORD_SHA256:
        raise Phase5ExitRetirementError("Phase 5 Exit predecessor root drifted")
    try:
        predecessor = json.loads(predecessor_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError("invalid Phase 5 Exit predecessor") from error

    historical = transition["historical_bindings"]
    successors = transition["named_successors"]
    if (
        type(historical) is not list
        or len(historical) != 18
        or type(successors) is not list
        or len(successors) != 7
    ):
        raise Phase5ExitRetirementError(
            "Phase 5 successor transition cardinality drifted"
        )
    if [entry.get("path") for entry in historical] != [
        entry["path"] for entry in predecessor["bindings"]
    ]:
        raise Phase5ExitRetirementError("historical transition order drifted")
    if [entry.get("path") for entry in successors] != sorted(predecessor["successors"]):
        raise Phase5ExitRetirementError("named successor transition order drifted")
    prior_historical = predecessor_transition.get("historical_bindings")
    prior_successors = predecessor_transition.get("named_successors")
    if (
        type(prior_historical) is not list
        or type(prior_successors) is not list
        or [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in historical
        ]
        != [
            (
                entry.get("path"),
                entry.get("historical_sha256"),
                entry.get("state"),
                entry.get("successor"),
            )
            for entry in prior_historical
        ]
        or [
            (entry.get("path"), entry.get("predecessor_sha256")) for entry in successors
        ]
        != [
            (entry.get("path"), entry.get("predecessor_sha256"))
            for entry in prior_successors
        ]
    ):
        raise Phase5ExitRetirementError("Phase 5 successor chain identity drifted")

    hasher = hashlib.sha256()
    hasher.update(TRANSITION_DOMAIN)
    for current, prior in zip(historical, predecessor["bindings"], strict=True):
        if type(current) is not dict or set(current) != {
            "path",
            "historical_sha256",
            "current_sha256",
            "state",
            "successor",
        }:
            raise Phase5ExitRetirementError("historical transition entry is malformed")
        if (
            current["path"] != prior["path"]
            or current["historical_sha256"] != prior["historical_sha256"]
            or current["state"] != prior["state"]
            or current["successor"] != prior["successor"]
            or not _valid_sha(current["current_sha256"])
            or _sha(_read(PROJECT, current["path"]))
            != current_historical_digests.get(
                current["path"],
                release_digests.get(current["path"], current["current_sha256"]),
            )
        ):
            raise Phase5ExitRetirementError(
                f"current historical target drifted: {current.get('path')}"
            )
        for value in (
            "historical-binding",
            current["path"],
            current["historical_sha256"],
            current["current_sha256"],
            current["state"],
            current["successor"],
        ):
            _frame(hasher, value)
    for current in successors:
        if type(current) is not dict or set(current) != {
            "path",
            "predecessor_sha256",
            "current_sha256",
        }:
            raise Phase5ExitRetirementError("named successor transition is malformed")
        path = current["path"]
        if (
            predecessor["successors"].get(path) != current["predecessor_sha256"]
            or not _valid_sha(current["current_sha256"])
            or _sha(_read(PROJECT, path))
            != current_successor_digests.get(path, current["current_sha256"])
        ):
            raise Phase5ExitRetirementError(f"named Phase 5 successor drifted: {path}")
        for value in (
            "named-successor",
            path,
            current["predecessor_sha256"],
            current["current_sha256"],
        ):
            _frame(hasher, value)
    if hasher.hexdigest() != transition["current_root_sha256"]:
        raise Phase5ExitRetirementError("Phase 5 successor transition root drifted")
    return transition


def _successor_digest(relative: str, predecessor_digest: str) -> str:
    for successor in load_current_successor_transition()["named_successors"]:
        if successor["path"] == relative:
            if successor["predecessor_sha256"] != predecessor_digest:
                break
            return successor["current_sha256"]
    raise Phase5ExitRetirementError(
        f"named successor lacks an authenticated transition: {relative}"
    )


@functools.lru_cache(maxsize=1)
def load_record() -> dict[str, object]:
    raw = RECORD.read_bytes()
    if _sha(raw) != RECORD_SHA256:
        raise Phase5ExitRetirementError("Phase 5 Exit retirement record drifted")
    try:
        record = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid Phase 5 Exit retirement record"
        ) from error
    if (
        type(record) is not dict
        or set(record) != {"schema", "disposition", "policy", "bindings", "successors"}
        or record["schema"] != "onyx.test.phase5-exit-retirement.v1"
        or record["disposition"] != "superseded-historical-bindings-not-rebound"
        or record["policy"]
        != {
            "current_bytes_may_satisfy_historical_hash": False,
            "historical_manifests_remain_immutable": True,
            "missing_historical_bytes_may_be_fabricated": False,
            "named_successor_must_be_authenticated": True,
        }
    ):
        raise Phase5ExitRetirementError("Phase 5 Exit retirement contract drifted")
    additional_raw = ADDITIONAL_RECORD.read_bytes()
    if _sha(additional_raw) != ADDITIONAL_RECORD_SHA256:
        raise Phase5ExitRetirementError(
            "Phase 5 Exit additive retirement record drifted"
        )
    try:
        additional_record = json.loads(additional_raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as error:
        raise Phase5ExitRetirementError(
            "invalid Phase 5 Exit additive retirement record"
        ) from error
    if (
        type(additional_record) is not dict
        or set(additional_record)
        != {
            "schema",
            "disposition",
            "predecessor",
            "policy",
            "additional_bindings",
        }
        or additional_record["schema"]
        != "onyx.test.phase5-exit-retirement.v2"
        or additional_record["disposition"]
        != "additive-successor-retirement-not-rebound"
        or additional_record["predecessor"]
        != {
            "path": "tests/fixtures/phase5_exit_retirement_v1.json",
            "sha256": RECORD_SHA256,
        }
        or additional_record["policy"]
        != {
            "historical_bindings_are_rewritten": False,
            "historical_hashes_are_rebound": False,
            "named_successor_must_be_authenticated": True,
        }
        or type(additional_record["additional_bindings"]) is not list
        or len(additional_record["additional_bindings"]) != 2
    ):
        raise Phase5ExitRetirementError(
            "Phase 5 Exit additive retirement contract drifted"
        )
    bindings = [*record["bindings"], *additional_record["additional_bindings"]]
    successors = record["successors"]
    if (
        type(bindings) is not list
        or len(bindings) != 20
        or type(successors) is not dict
    ):
        raise Phase5ExitRetirementError("Phase 5 Exit retirement cardinality drifted")
    keys: set[tuple[str, str]] = set()
    for entry in bindings:
        if type(entry) is not dict or set(entry) != {
            "path",
            "historical_sha256",
            "state",
            "successor",
        }:
            raise Phase5ExitRetirementError("invalid Phase 5 Exit retirement binding")
        key = (entry["path"], entry["historical_sha256"])
        _relative(entry["path"])
        if (
            key in keys
            or entry["state"] not in {"recoverable-exact", "unavailable-tombstoned"}
            or entry["successor"] not in successors
        ):
            raise Phase5ExitRetirementError("invalid Phase 5 Exit retirement binding")
        keys.add(key)
    for relative, digest in successors.items():
        if _sha(_read(PROJECT, relative)) != _successor_digest(relative, digest):
            raise Phase5ExitRetirementError(
                f"named Phase 5 Exit successor drifted: {relative}"
            )
    merged = dict(record)
    merged["bindings"] = bindings
    return merged


def _entry(relative: str, historical_sha256: str) -> dict[str, str]:
    for candidate in load_record()["bindings"]:
        if (
            candidate["path"] == relative
            and candidate["historical_sha256"] == historical_sha256
        ):
            return candidate
    raise Phase5ExitRetirementError(
        f"unregistered historical Phase 5 Exit binding: {relative}"
    )


def authenticate_successor(relative: str) -> str:
    successors = load_record()["successors"]
    predecessor = successors.get(relative)
    if type(predecessor) is not str:
        raise Phase5ExitRetirementError(f"named successor drifted: {relative}")
    expected = _successor_digest(relative, predecessor)
    if _sha(_read(PROJECT, relative)) != expected:
        raise Phase5ExitRetirementError(f"named successor drifted: {relative}")
    return expected


@functools.lru_cache(maxsize=32)
def _head_bytes(relative: str, expected: str) -> bytes:
    _relative(relative)
    from scripts.verify_r11_projection_retirement_v1 import (
        R11ProjectionRetirementError,
        historical_head_file,
    )

    try:
        return historical_head_file(relative, expected)
    except R11ProjectionRetirementError as exc:
        raise Phase5ExitRetirementError(
            f"authenticated packed bytes do not match historical binding: {relative}"
        ) from exc


def classify(root: Path, relative: str, expected: str) -> str:
    """Reject current drift and delegate the obsolete edge to named evidence."""

    current = _sha(_read(root, relative))
    if current == expected:
        return "current-exact"
    if Path(root).resolve() != PROJECT.resolve():
        raise Phase5ExitRetirementError(f"non-authoritative tree drifted: {relative}")
    entry = _entry(relative, expected)
    successor = entry["successor"]
    predecessor_digest = load_record()["successors"][successor]
    successor_digest = _successor_digest(successor, predecessor_digest)
    if _sha(_read(PROJECT, successor)) != successor_digest:
        raise Phase5ExitRetirementError(f"named successor drifted: {successor}")
    if entry["state"] == "recoverable-exact":
        _head_bytes(relative, expected)
        return "archived-exact"
    try:
        _head_bytes(relative, expected)
    except (Phase5ExitRetirementError, subprocess.SubprocessError):
        return f"retired-delegated:{successor}"
    raise Phase5ExitRetirementError(
        f"tombstoned bytes unexpectedly became recoverable: {relative}"
    )


def historical_bytes(root: Path, relative: str, expected: str) -> bytes:
    state = classify(root, relative, expected)
    if state == "current-exact":
        return _read(root, relative)
    if state == "archived-exact":
        return _head_bytes(relative, expected)
    raise Phase5ExitRetirementError(
        f"tombstoned historical bytes cannot be executed: {relative}"
    )

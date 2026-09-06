# Onyx Capability Expansion V1 — Clean-room provenance

Date: 2026-08-23  
Story: `ONYX-MARK-LI-BROWNFIELD-GAPS-V1`

Current-reference reconciliation: 2026-09-01. The public README, repository
tree, license and commit metadata at `d3238af8bd4203cc960e3c758f7d83440eef96f8`
were used to refresh the behavior inventory. No reference implementation file
was opened, copied, translated, imported or used to produce the additions below.

## Decision

The Mark-LI repository was used only to identify observable capability ideas.
No Mark-LI source file was copied, translated, vendored, mechanically transformed
or imported. Implementation was produced against the Onyx story, ADR-0063 and
existing Onyx authority contracts.

## Original Cyryx implementation set

- `core/enhanced_live_audio_v1.py`
- `core/plugin_runtime_v1.py`
- `core/clipboard_intelligence_v1.py`
- `core/wellness_tracker_v1.py`
- `core/vision_repetition_counter_v1.py`
- `core/governed_personalization_v1.py`
- `core/social_publish_v1.py`
- `core/social_video_asset_v1.py`
- `core/capability_expansion_runtime_v1.py`
- `core/capability_expansion_service_v1.py`
- `scripts/onyx_plugin_cli.py`
- `scripts/onyx_personal_tools_cli.py`
- `scripts/onyx_personalization_cli.py`
- `scripts/onyx_social_cli.py`
- `scripts/onyx_vision_repetition_cli.py`
- corresponding `tests/test_*_v1.py` files
- `plugins/_template.py`

## Dependency and license review

The new runtime modules use Python standard-library facilities and existing Onyx
dependencies already present in the product. No new third-party package was
introduced by this capability expansion. Provider and native-sandbox adapters
are injected contracts; no provider SDK or sandbox implementation was vendored.
The repetition estimator accepts only normalized numeric observations and has
no camera/image dependency. The video broker uses only Python standard-library
path, MIME, hashing and ephemeral-lease facilities.

## Packaged-source boundary

`main.py` imports the capability service, so PyInstaller source discovery reaches
the runtime modules through the normal import graph. Developer CLIs and the
plugin template are engineering surfaces and do not prove packaged inclusion.
No third-party plugin code is bundled. A future release still requires a fresh
package build, exact-artifact manifest, installed-host smoke and license review.
The two 2026-09-01 additions are CLI/source candidates and are not represented
as composed in the sealed HUD/runtime or installed package.

## 2026-09-01 substantive-file digests

- `core/vision_repetition_counter_v1.py` — `4EB7C1CBB6DFCF18C5E8B21928F3870ED9C44B9FB9676349AAD08C78D3D82122`
- `core/social_video_asset_v1.py` — `A0F39947A605F852FA173C43D5EE7F4F90BB3478B24A2C7F22726CD34C3B70A7`
- `scripts/onyx_vision_repetition_cli.py` — `3EFFF578C6BE42009828EBF7DF5390FCB3B37F38F8B1B53EF80EA7EFFA046716`
- `scripts/onyx_social_cli.py` — `475C1CDDACA97784C5A6C8EF88C1233DEAAD140E0726F10FC7B0606ED85D58F9`
- `tests/test_vision_repetition_counter_v1.py` — `C8E32311209F37556D0F079A2E0354E33964773BAEB533AEAE47DE07437C0C17`
- `tests/test_social_video_asset_v1.py` — `7D43255EE579BD44F85B1493C088E24E693C7E8C31F2363AE60BE32518FBE217`

## Evidence limit

This record proves the declared source/provenance boundary. It does not prove a
live Gemini preview feature, native sandbox availability, social-provider access,
provider certification, package signing or public release.

## 2026-09-01 functional-parity closure

The follow-on story `ONYX-REFERENCE-FUNCTIONAL-PARITY-V1` used the same public
behavior/file-name-only clean-room boundary at reference HEAD
`d3238af8bd4203cc960e3c758f7d83440eef96f8`. No reference implementation file
was opened. A product-code scan over the new/modified parity surfaces found no
reference-project, creator, foreign assistant, or foreign license branding.

Original Cyryx additions and exact SHA-256 digests:

- `core/spoken_language_memory_v1.py` — `5041911EBDD89F5F5CC3DEA241F93C022B9E8750B5A7B7E7135A7DF5B72D6BAB`
- `core/assistant_identity_profile_v1.py` — `E6D5596F5F82A4C5D2C2694355FFA30EB1E21F5EE97409920B5CAB65A4BFF4F0`
- `core/social_content_strategy_v1.py` — `B5F99E2AE5316B528C92E9946A7D831A3657CF30B219AD7435505A936479A25B`
- `core/capability_parity_v1.py` — `317F27E4B0931700081951052D1657DAFB0AAAEC6CFCC979B5B50D245A183739`
- `scripts/onyx_identity_cli.py` — `9115CC89B868B7ED6FBF38D2574859DC3589ED912E0EEC4C9E50E8FD2080F920`
- `scripts/onyx_parity_cli.py` — `634A229164CEC9608BE312DB2E8D1A2CA93A19E93D73FC58F4FF1E769AF197F3`
- `main.py` — `0A5565D0CA97D05BD9A8E12DD871E9A08F10351BC7EE6108CA3F0D897C4E3918`
- `scripts/onyx_social_cli.py` — `A38126672240AFAE619962394266578D5789E072F930EAB02A41606709A8BE1F`

The root Cyryx Labs license remained unchanged at SHA-256
`E045278221225C8F0EF82A4332770B6ECB1DCC96BBEFC64E976C9CC15E8B7D95`.
The accepted package spec was not resealed by this closure. Package, installed,
native-sandbox, OAuth/account, physical-camera/audio and live-provider parity
remain separate evidence gates.

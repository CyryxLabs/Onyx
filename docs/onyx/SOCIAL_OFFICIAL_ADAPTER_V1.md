# Official social adapter V1 — Facebook Pages text only

## Actual capability and audit

This change implements an official Facebook Pages HTTP adapter, integrates it
with the **existing owner CLI**, and tests its governed publication flow with
synthetic responses. It does **not** establish that a Facebook account is
connected, that permissions were granted, that a post was published live, or that
six platforms are operational. No authenticated HTTP call or vault provisioning
was performed during development.

In the inspected source snapshot, `actions/social` does not exist. Social actions
in `actions/send_message.py` open browser messaging pages; `actions/youtube_video.py`
searches/opens videos rather than publishing through an official API. The inspected
`config/api_keys.json` contains general application settings, not a social account
configuration. Only property names were inspected, with no credential disclosure.
No reusable official social publishing client was found in actions/core/scripts.

`core/social_publish_v1.py` already provides the durable publication ledger and
provider protocol. `core/native_vault.py` supplies the secure OS vault primitive.
Those implementations are reused unchanged. The new provider is a deliberate,
bounded fallback because no configured official social publishing platform was
found; **missing Page configuration or vault token remains a real blocker**.

The model-facing `CapabilityExpansionServiceV1` social operations remain exactly
`status`, `generate`, `preview`, and `video_inspect`. This change does not add a
publishing operation to that tool or increase its operation count. Adapter presence
must not be reported as model-tool publishing availability.

## Parent integration contracts

```python
from core.social_official_adapter_v1 import (
    FacebookPageConfigV1,
    create_social_official_publication_v1,
)
from core.social_publish_v1 import SocialPublishFeatureGateV1

# Call only for an explicitly requested owner publication session.
publication = create_social_official_publication_v1(
    gate=SocialPublishFeatureGateV1.from_environ(),
    config=FacebookPageConfigV1(page_id=operator_supplied_page_id),
    ledger_path=absolute_trusted_ledger_path,
)
```

The factory returns `SocialPublicationV1 | None`. Its default gate is disabled;
disabled construction returns `None` before vault, filesystem, or HTTP access.
Enabled construction validates explicit Page configuration and reads its vault
token, then creates the existing durable service. Construction never performs
HTTP. The existing `ONYX_SOCIAL_PUBLISH_V1=true` flag enables this factory; it does
not provide publication consent. Missing configuration raises a sanitized error.
Do not construct an enabled publication session unconditionally during app startup.

The parent-owned service hook now selects this factory with explicit
`ONYX_SOCIAL_OFFICIAL_FACEBOOK_V1` boolean settings and
`ONYX_SOCIAL_FACEBOOK_PAGE_ID`, using `root/capability_social_v1.sqlite3`.
Pass that same absolute file through the owner's existing `--ledger-path` option;
do not create a second ledger. `owner-cli-ready` means local configuration is
available, not authenticated publishing verification or LLM dispatch authority.
This integration was inspected read-only; the service file remains parent-owned.

**Bootstrap route:** forward `Onyx.exe --social ...` arguments to
`scripts.onyx_social_cli.cli_main(argv[2:])`. This is the safe process entry point
in the existing CLI, not a duplicate command implementation. `main(argv, ...)`
retains historical exception behavior for imported Python callers; passing
`structured_errors=True` makes it equivalent to the wrapper for operation errors.
`cli_main` also converts argparse help exits into integer return codes.

## Owner CLI path

`scripts/onyx_social_cli.py` now accepts global `--facebook-page-id PAGE_ID` and
`--output NEW_FILE.json` options before its existing subcommand. Existing injected
provider/runtime callers continue to work; mixing injection with explicit official
Page selection is rejected. An offline `generate` or `preview` never activates
the official provider, even when a Page option is present.

Prepare a Page access token through the operator's approved Meta account/app
workflow, with permission to create and read that Page's posts. This adapter does
not acquire/refresh OAuth tokens, request app review, or claim permissions are
granted. The token is UTF-8/ASCII bytes stored through the existing native vault
under the reference returned by
`facebook_page_vault_reference_v1(operator_supplied_page_id)`:

- service: `Onyx.Social.FacebookPage`
- account: the exact numeric Page ID
- no environment-token, JSON-token, or command-line-token fallback

The following is an owner-run workflow; the last step publishes if deliberately
invoked with real configuration. It was **not run live** during development.

```powershell
$env:ONYX_SOCIAL_PUBLISH_V1 = 'true'
# Set $page, $ledger, $workspace, $owner and $caption to operator-approved values.
$common = @('--facebook-page-id', $page, '--ledger-path', $ledger)
$fields = @('--workspace-id', $workspace, '--principal-id', $owner,
            '--account-id', $page, '--target', 'facebook-page-feed', '--caption', $caption)
python scripts/onyx_social_cli.py @common --output preview.json publish-preview @fields
# Read/review preview.json. Copy the exact consent_text manually after approval.
python scripts/onyx_social_cli.py @common --output consent.json publish-consent @fields --exact-consent $exactReviewedConsent
# LIVE mutation: the existing service permits one dispatch for this exact request.
python scripts/onyx_social_cli.py @common --output result.json publish-dispatch @fields
python scripts/onyx_social_cli.py @common --output status.json publish-status --request-digest $requestDigest
# If a receipt exists but readback was uncertain, this performs GET only:
python scripts/onyx_social_cli.py @common --output reconcile.json publish-reconcile --request-digest $requestDigest
```

Use fresh output filenames in a trusted existing directory. Output uses exclusive
creation, rejects symlinks/junctions, reserved/device names, non-JSON suffixes,
alternate data streams and the ledger path. It never overwrites an existing file
or creates parent directories. Output is reserved **before** provider work. As
with the existing ledger, a malicious local process rewriting trusted directories
or local Python internals is outside this boundary.

When stdout/stderr are absent, operations still return exit codes; JSON is retained
in `--output` if supplied. `--help` prints where a console exists and returns zero
without a console; it does not create an output file. Parsed operation errors are
written to the reserved output and stderr when available, without raw exception
strings, provider response bodies or credentials. Argument/output-reservation
errors occur before a writable output exists and return 2 with stderr JSON when
available. Success returns 0. If an output write fails after dispatch, inspect the
durable ledger before any next action; output failure does not undo a publication.

Consent is the existing exact-preview phrase, bound to unchanged account, target,
caption, media list and provenance. This is an owner CLI workflow; exact text is
not cryptographic proof that a human typed it. Do not expose it as an autonomous
model tool or have a model generate its own consent. The internal adapter is a
trusted implementation boundary and must be called through `SocialPublicationV1`.

## Provider and failure boundaries

- Only `facebook-page-feed`, with `account_id` equal to the configured Page ID and
  no media digests, is supported. No images, videos, reels, scheduling, deletion,
  other platforms or browser automation are added.
- Fixed HTTPS host `graph.facebook.com`, port 443, pinned version `v26.0`.
  Allowed requests: `POST /v26.0/{page-id}/feed` with exact message and
  `published=true`; `GET /v26.0/{page-id}_{post-id}` requesting
  `id,message,from,is_published`. No configurable URL, redirects, proxy environment,
  pagination, automatic retries or background requests.
- Native-vault token goes in the Authorization header, never the URL or ledger.
  Standard TLS certificate/hostname verification is required. Socket timeout is
  15 seconds by default, configurable from 1 to 60; response body limit is 64 KiB.
  This is a per-socket timeout, not a hard end-to-end wall-clock deadline.
- The adapter rechecks the existing ledger's consent, dispatch state and exact
  persisted request before POST. The existing service owns durable at-most-once
  dispatch. No claim is made that Facebook provides server-side idempotency for
  this call; no synthetic idempotency header or automatic retry is added.
- Provider post ID becomes the receipt. Verification requires a separate GET
  matching post ID, Page author, exact caption and boolean published status.
  Missing or mismatched fields yield unknown, never verified. The expected payload
  is recovered from the ledger, so reconciliation works after adapter restart.
- HTTP rejection, timeout, malformed response, invalid ID and failed readback
  preserve the service's uncertain state. It denies a blind re-dispatch. A POST
  timeout without a receipt requires manual provider reconciliation. No broad
  feed search or fabricated absence claim is used to permit another POST.
- Operator configuration, vault provisioning, granted provider permissions,
  authenticated acceptance, packaged execution and release remain unverified
  external/integration gates. Keep the ledger; do not create another ledger to
  bypass an uncertain result.

## Primary-source verification

Checked 2026-09-05. Meta documentation endpoints returned HTTP 429, so protocol
details were checked against Meta's own maintained SDK source, not third-party
API summaries. No SDK dependency was installed or code copied.

- [Meta Page API source](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/page.py): `create_feed`, POST edge, message and published parameters.
- [Meta Post API source](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/adobjects/post.py): GET and ID/message/from/is_published fields.
- [Meta API configuration](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/apiconfig.py): v26.0 at inspection time.
- [Meta session source](https://github.com/facebook/facebook-python-business-sdk/blob/main/facebook_business/session.py): official Graph HTTPS origin.
- [Meta's Postman collection](https://www.postman.com/meta/instagram/documentation/6yqw8pt/instagram-api?entity=request-23987686-a71fb850-457c-4b82-a56a-1dea1785f2a2): bearer authentication examples on Graph. This is authentication evidence, not a claim that this module supports Instagram publishing.

## Implementation log and validation

IDS searches covered social/network/provider filenames and official API URLs in
actions, core, scripts, configuration and existing tests. No existing official
social client was found. Decisions:

| File | Decision | Rationale |
| --- | --- | --- |
| `core/social_official_adapter_v1.py` | CREATE, REUSE existing social ledger and native vault | Concrete bounded provider implementation without new dependencies |
| `tests/test_social_official_adapter_v1.py` | CREATE, ADAPT existing pytest/fake-provider conventions | Hermetic provider/CLI coverage, no live publication |
| `scripts/onyx_social_cli.py` | ADAPT after explicit user authorization | Reuse owner CLI; safe factory selection and windowless output |
| `docs/onyx/SOCIAL_OFFICIAL_ADAPTER_V1.md` | CREATE | Audit, owner path, limitations, primary sources and decisions |

[AUTO-DECISION] No configured official platform found → Facebook Page text only,
disabled until explicit configuration (reason: narrow mapping onto existing caption
and receipt protocol; no media transport invented). This was announced before coding.

Skill self-critique 5.5 considered duplicate POST after timeout, forged/cross-Page
receipt verification and credentials leaking through HTTP exceptions. Existing
durable dispatch plus no retries, ledger-bound exact readback, and sanitized errors
address these. Edge cases covered include empty/malformed vault values, redirects,
body overflow, wrong platform/media, missing console and pre-existing output files.
Step 6.5 confirmed existing service tests and CLI semantics remain intact, with the
new safe process wrapper used for structured failures. Documentation/IDS review is
kept here under the bounded file scope; shared story/release artifacts are untouched.

Validation: **80 tests passed** across the new test file and the unchanged
`tests/test_social_publish_v1.py`; Ruff passed on the adapter, tests and edited CLI.
The tests inject every vault and HTTP dependency. Run with plugin autoload disabled,
`--noconftest`, and a fresh unique `--basetemp` to avoid this host's existing global
pytest temporary-directory ACL failure. This result is not the full application suite.

Required npm lint/typecheck/test commands were attempted with `--prefix .`; all
reported ENOENT because this Python snapshot has no package.json. Git status/log
also report absent repository metadata. No manifests, release files, main.py,
capability operation catalog, original social protocol or dependencies were changed.

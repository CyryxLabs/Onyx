"""CLI for offline social caption previews; publication is disabled by default."""

from __future__ import annotations

import argparse
import json
import os
import re
from contextlib import suppress
from dataclasses import asdict, replace
from pathlib import Path
import sys


if __package__ in {None, ""}:
    project_root = str(Path(__file__).resolve().parents[1])
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

from core.social_publish_v1 import (
    CaptionGenerationRequestV1,
    CaptionRequestV1,
    SocialProviderAdapterV1,
    SocialPublishFeatureGateV1,
    SocialPublicationV1,
    create_social_publication_v1,
    generate_caption_draft,
    preview_caption,
)
from core.social_video_asset_v1 import SocialVideoAssetBrokerV1
from core.social_content_strategy_v1 import (
    GeminiCaptionProviderV1,
    SocialStrategyRequestV1,
    generate_strategic_caption_v1,
)
from core.social_official_adapter_v1 import (
    FacebookPageConfigV1,
    SocialOfficialAdapterError,
    TARGET as FACEBOOK_TARGET,
    create_social_official_publication_v1,
)


class _CLIArgumentError(ValueError):
    pass


class _SocialParser(argparse.ArgumentParser):
    def error(self, message):
        # Invalid arguments can themselves contain secrets; do not echo them.
        raise _CLIArgumentError("invalid_arguments")


def _add_request_arguments(parser: argparse.ArgumentParser) -> None:
    for name in ("workspace-id", "principal-id", "account-id", "target", "caption"):
        parser.add_argument(f"--{name}", required=True)
    parser.add_argument("--media-digest", action="append", default=[])
    parser.add_argument("--provenance", action="append", default=[])
    parser.add_argument("--warning", action="append", default=[])


def _request(args: argparse.Namespace) -> CaptionRequestV1:
    return CaptionRequestV1(
        workspace_id=args.workspace_id,
        principal_id=args.principal_id,
        account_id=args.account_id,
        target=args.target,
        caption=args.caption,
        media_digests=tuple(args.media_digest),
        provenance=tuple(args.provenance),
        warnings=tuple(args.warning),
    )


def _publication(runtime: SocialPublicationV1 | None) -> SocialPublicationV1:
    if runtime is None:
        raise RuntimeError(
            "publication unavailable: inject an explicitly enabled provider adapter"
        )
    return runtime


def build_parser() -> argparse.ArgumentParser:
    parser = _SocialParser(prog="onyx-social")
    parser.add_argument("--ledger-path", type=Path)
    parser.add_argument("--facebook-page-id", help="Explicit official Facebook Page text publisher")
    parser.add_argument("--output", type=Path, help="Create a NEW JSON output file; never overwrite")
    sub = parser.add_subparsers(dest="command", required=True)
    generate = sub.add_parser("generate", help="generate a deterministic local draft")
    generate.add_argument("--brief", required=True)
    generate.add_argument("--brand", required=True)
    generate.add_argument("--platform", required=True)
    generate.add_argument("--source-ref", action="append", default=[])
    generate.add_argument("--audience", default="global business leaders")
    generate.add_argument(
        "--objective",
        choices=("awareness", "education", "engagement", "lead", "launch"),
        default="education",
    )
    generate.add_argument("--tone", default="authoritative")
    generate.add_argument("--provider", choices=("local", "gemini"), default="local")
    generate.add_argument("--allow-provider-network", action="store_true")
    generate.add_argument("--model", default="gemini-2.5-flash")
    preview = sub.add_parser("preview", help="create an offline caption preview")
    _add_request_arguments(preview)
    video_preview = sub.add_parser(
        "video-preview",
        help="inspect a local video lease and bind it to an offline publication preview",
    )
    _add_request_arguments(video_preview)
    video_preview.add_argument("--controlled-root", type=Path, required=True)
    video_preview.add_argument("--media-file", type=Path, required=True)
    video_preview.add_argument("--lease-seconds", type=float, default=300.0)
    publish_preview = sub.add_parser(
        "publish-preview", help="bind a preview in an injected publication session"
    )
    _add_request_arguments(publish_preview)
    consent = sub.add_parser("publish-consent", help="record exact preview consent")
    _add_request_arguments(consent)
    consent.add_argument("--exact-consent", required=True)
    dispatch = sub.add_parser(
        "publish-dispatch", help="perform the one allowed dispatch"
    )
    _add_request_arguments(dispatch)
    publish = sub.add_parser(
        "publish", help="run preview, exact consent, and one dispatch"
    )
    _add_request_arguments(publish)
    publish.add_argument("--exact-consent", required=True)
    status = sub.add_parser("publish-status", help="read publication state")
    status.add_argument("--request-digest", required=True)
    reconcile = sub.add_parser(
        "publish-reconcile", help="read back an uncertain effect"
    )
    reconcile.add_argument("--request-digest", required=True)
    return parser


def _execute(
    args: argparse.Namespace,
    *,
    publication: SocialPublicationV1 | None = None,
    provider_adapter: SocialProviderAdapterV1 | None = None,
    feature_gate: SocialPublishFeatureGateV1 | None = None,
) -> object:
    if args.facebook_page_id and args.command.startswith("publish"):
        if publication is not None or provider_adapter is not None:
            raise _CLIArgumentError("conflicting_provider_selection")
        if hasattr(args, "account_id") and (
            args.account_id != args.facebook_page_id or args.target != FACEBOOK_TARGET
            or args.media_digest
        ):
            raise _CLIArgumentError("facebook_text_request_binding_invalid")
        publication = create_social_official_publication_v1(
            gate=feature_gate or SocialPublishFeatureGateV1.from_environ(),
            config=FacebookPageConfigV1(args.facebook_page_id),
            ledger_path=args.ledger_path.resolve() if args.ledger_path else None,
        )
    if publication is None and provider_adapter is not None:
        publication = create_social_publication_v1(
            gate=feature_gate or SocialPublishFeatureGateV1.from_environ(),
            adapter=provider_adapter,
            ledger_path=args.ledger_path.resolve() if args.ledger_path else None,
        )
    if args.command == "generate":
        if args.provider == "local" and args.audience == "global business leaders" and args.objective == "education" and args.tone == "authoritative":
            output = generate_caption_draft(
                CaptionGenerationRequestV1(
                    brief=args.brief,
                    brand=args.brand,
                    platform=args.platform,
                    source_refs=tuple(args.source_ref),
                )
            )
        else:
            provider = None
            if args.provider == "gemini":
                from google import genai
                from core.credentials import get as get_gemini_credential

                provider = GeminiCaptionProviderV1(
                    client_factory=lambda key: genai.Client(api_key=key),
                    api_key_getter=lambda: get_gemini_credential(required=True) or "",
                    model=args.model,
                )
            output = generate_strategic_caption_v1(
                SocialStrategyRequestV1(
                    brief=args.brief,
                    brand=args.brand,
                    platform=args.platform,
                    audience=args.audience,
                    objective=args.objective,
                    tone=args.tone,
                    source_refs=tuple(args.source_ref),
                ),
                provider=provider,
                allow_provider=args.allow_provider_network,
            )
    elif args.command == "preview":
        output = preview_caption(_request(args))
    elif args.command == "video-preview":
        root = args.controlled_root.expanduser().resolve()
        media_file = args.media_file.expanduser()
        if not media_file.is_absolute():
            media_file = (Path.cwd() / media_file).resolve()
        broker = SocialVideoAssetBrokerV1((root,))
        descriptor = broker.inspect(
            media_file,
            workspace_id=args.workspace_id,
            principal_id=args.principal_id,
            lease_seconds=args.lease_seconds,
        )
        request = _request(args)
        request = replace(
            request,
            media_digests=(*request.media_digests, descriptor.binding),
        )
        output = {
            "video_asset": descriptor.to_dict(),
            "preview": asdict(preview_caption(request)),
        }
    elif args.command == "publish-preview":
        output = _publication(publication).create_preview(_request(args))
    elif args.command == "publish-consent":
        output = _publication(publication).consent(
            _request(args), exact_consent=args.exact_consent
        )
    elif args.command == "publish-dispatch":
        output = _publication(publication).dispatch(_request(args))
    elif args.command == "publish":
        runtime = _publication(publication)
        request = _request(args)
        runtime.create_preview(request)
        runtime.consent(request, exact_consent=args.exact_consent)
        output = runtime.dispatch(request)
    elif args.command == "publish-status":
        output = _publication(publication).status(args.request_digest)
    else:
        output = _publication(publication).reconcile(args.request_digest)
    return output if isinstance(output, dict) else asdict(output)


def _open_output(path: Path, ledger: Path | None):
    if (path.suffix.lower() != ".json" or ":" in path.name
            or re.match(r"(?i)^(con|prn|aux|nul|com[1-9]|lpt[1-9])(?:\.|$)", path.name)
            or (ledger is not None and path.resolve() == ledger.resolve())):
        raise _CLIArgumentError("unsafe_output_path")
    # Reject links/junctions; the caller must choose a trusted existing directory.
    for part in (path.absolute(), *path.absolute().parents):
        if part.is_symlink() or (hasattr(part, "is_junction") and part.is_junction()):
            raise _CLIArgumentError("unsafe_output_path")
    if hasattr(os.path, "isreserved") and os.path.isreserved(str(path)):
        raise _CLIArgumentError("unsafe_output_path")
    return path.open("x", encoding="utf-8")


def main(
    argv: list[str] | None = None, *,
    publication: SocialPublicationV1 | None = None,
    provider_adapter: SocialProviderAdapterV1 | None = None,
    feature_gate: SocialPublishFeatureGateV1 | None = None,
    structured_errors: bool = False,
) -> int:
    """Reusable CLI; cli_main is the safe process/bootstrap entry point.

    Legacy imported callers retain exception semantics unless structured_errors
    is enabled. Output is reserved before any provider work, using exclusive create.
    """
    sink = None
    try:
        args = build_parser().parse_args(argv)
        if args.output is not None:
            sink = _open_output(args.output, args.ledger_path)
        output = _execute(args, publication=publication, provider_adapter=provider_adapter,
                          feature_gate=feature_gate)
        text = json.dumps(output, sort_keys=True) + "\n"
        if sink is not None:
            sink.write(text)
            sink.flush()
        elif sys.stdout is not None:
            sys.stdout.write(text)
        return 0
    except Exception as exc:
        if not structured_errors:
            raise
        from core.social_publish_v1 import SocialPublishDenied, SocialPublishUncertain

        if isinstance(exc, _CLIArgumentError):
            code = str(exc)
        elif isinstance(exc, SocialOfficialAdapterError):
            code = "official_provider_unavailable"
        elif isinstance(exc, SocialPublishUncertain):
            code = "publication_uncertain_reconcile_before_retry"
        elif isinstance(exc, SocialPublishDenied):
            code = "publication_denied"
        elif isinstance(exc, OSError):
            code = "local_io_unavailable"
        else:
            code = "social_operation_unavailable"
        error = json.dumps({"status": "error", "error": code}) + "\n"
        if sink is not None:
            with suppress(Exception):
                sink.write(error)
                sink.flush()
        if sys.stderr is not None:
            with suppress(Exception):
                sys.stderr.write(error)
        return 2
    finally:
        if sink is not None:
            with suppress(Exception):
                sink.close()


def cli_main(argv: list[str] | None = None, **dependencies) -> int:
    """Bootstrap hook: windowless-safe output and structured nonzero failures."""
    try:
        return main(argv, structured_errors=True, **dependencies)
    except SystemExit as exc:
        return exc.code if isinstance(exc.code, int) else 2


if __name__ == "__main__":
    raise SystemExit(cli_main())

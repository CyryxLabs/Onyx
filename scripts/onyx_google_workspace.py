"""Isolated CLI-first source surface for Google Workspace host v1."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Callable, Sequence

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.google_workspace_connector_v1 import (  # noqa: E402
    GoogleProviderReceiptV1,
    GoogleReadResultV1,
    GoogleWorkspaceBindingV1,
    GoogleWorkspaceFeatureGateV1,
    GoogleWorkspaceV1ContractError,
    GoogleWorkspaceV1Denied,
    GoogleWorkspaceV1UnknownOutcome,
)
from core.google_workspace_host_v1 import (  # noqa: E402
    GoogleWorkspaceHostConfigurationV1,
    GoogleWorkspaceHostStatusV1,
    GoogleWorkspaceHostV1ContractError,
    GoogleWorkspaceHostV1Denied,
    GoogleWorkspaceHostV1UnknownOutcome,
    configure_google_workspace_host_v1,
    create_google_workspace_host_service_v1,
    read_google_workspace_host_status_v1,
)


CLI_SCHEMA = "OnyxGoogleWorkspaceCliResult.v1"
EXIT_OK = 0
EXIT_CONTRACT = 2
EXIT_DENIED = 3
EXIT_UNKNOWN = 4
CLI_COMMANDS = frozenset(
    {"status", "configure", "connect", "disconnect", "test-gmail", "test-calendar"}
)


class _SafeArgumentParser(argparse.ArgumentParser):
    def error(self, _message: str) -> None:
        raise GoogleWorkspaceHostV1ContractError(
            "Google CLI arguments are invalid"
        ) from None


def _parser() -> argparse.ArgumentParser:
    parser = _SafeArgumentParser(
        prog="onyx-google-workspace", allow_abbrev=False
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    def output_options(command):
        command.add_argument("--json", action="store_true", dest="json_output")

    def host_options(command, *, enabled=True):
        if enabled:
            command.add_argument("--enabled", action="store_true", required=True)
        command.add_argument("--owner-id", required=True)
        command.add_argument("--workspace-id", required=True)
        command.add_argument("--account-id", required=True)
        command.add_argument("--client-id", required=True)
        command.add_argument("--callback-port", type=int, required=True)
        output_options(command)

    status = subparsers.add_parser("status", allow_abbrev=False)
    status.add_argument("--enabled", action="store_true")
    status.add_argument("--owner-id")
    status.add_argument("--workspace-id")
    status.add_argument("--account-id")
    status.add_argument("--client-id")
    status.add_argument("--callback-port", type=int)
    output_options(status)

    configure = subparsers.add_parser("configure", allow_abbrev=False)
    host_options(configure, enabled=False)

    for name in ("connect", "disconnect", "test-gmail"):
        command = subparsers.add_parser(name, allow_abbrev=False)
        host_options(command)

    calendar = subparsers.add_parser("test-calendar", allow_abbrev=False)
    host_options(calendar)
    calendar.add_argument("--time-min", required=True)
    calendar.add_argument("--time-max", required=True)
    return parser


def _configuration(args) -> GoogleWorkspaceHostConfigurationV1:
    values = (
        args.owner_id,
        args.workspace_id,
        args.account_id,
        args.client_id,
        args.callback_port,
    )
    if any(value is None for value in values):
        raise GoogleWorkspaceHostV1ContractError(
            "complete explicit host configuration is required"
        )
    return GoogleWorkspaceHostConfigurationV1(
        GoogleWorkspaceBindingV1(
            args.owner_id, args.workspace_id, args.account_id.casefold()
        ),
        args.client_id,
        args.callback_port,
    )


def _receipt(value: GoogleProviderReceiptV1) -> dict[str, object]:
    return {
        "operation": value.operation,
        "status": value.status,
        "binding_digest": value.binding_digest,
        "request_digest": value.request_digest,
        "response_digest": value.response_digest,
        "grant_digest": value.grant_digest,
        "item_count": value.item_count,
        "page_count": value.page_count,
    }


def _status(value: GoogleWorkspaceHostStatusV1) -> dict[str, object]:
    return {
        "enabled": value.enabled,
        "configured": value.configured,
        "connected": value.connected,
        "supported_backend": value.supported_backend,
        "binding_digest": value.binding_digest,
        "anchor_generation": value.anchor_generation,
        "anchor_health": value.anchor_health,
        "scopes": list(value.scopes),
        "pending_loopback": value.pending_loopback,
        "reconciliation": value.reconciliation,
        "trust_limit": value.trust_limit,
    }


def _result(command: str, ok: bool, payload: dict[str, object]) -> dict[str, object]:
    return {
        "schema": CLI_SCHEMA,
        "command": command,
        "ok": ok,
        "result": payload,
    }


def _human(value: dict[str, object]) -> str:
    result = value["result"]
    assert isinstance(result, dict)
    if value["ok"]:
        facts = " ".join(f"{key}={json.dumps(item, ensure_ascii=True)}" for key, item in result.items())
        return f"{value['command']}: ok {facts}".rstrip()
    return f"{value['command']}: {result.get('code', 'denied')}"


def _emit(value: dict[str, object], *, json_output: bool, output: Callable[[str], None]) -> None:
    if json_output:
        output(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True))
    else:
        output(_human(value))


def run_cli_v1(
    argv: Sequence[str],
    *,
    output: Callable[[str], None] = print,
    _configure_port: Callable[[GoogleWorkspaceHostConfigurationV1], bool] | None = None,
    _factory_port: Callable[..., object] | None = None,
    _status_port: Callable[[GoogleWorkspaceHostConfigurationV1], GoogleWorkspaceHostStatusV1] | None = None,
) -> int:
    """Run the CLI. Underscored ports are explicit source-test seams only."""
    raw_argv = list(argv)
    command = raw_argv[0] if raw_argv and raw_argv[0] in CLI_COMMANDS else "invalid"
    json_output = "--json" in raw_argv
    configure_port = configure_google_workspace_host_v1 if _configure_port is None else _configure_port
    factory_port = create_google_workspace_host_service_v1 if _factory_port is None else _factory_port
    status_port = read_google_workspace_host_status_v1 if _status_port is None else _status_port
    try:
        args = _parser().parse_args(raw_argv)
        command = args.command
        json_output = bool(args.json_output)
        if command == "status" and not args.enabled:
            value = _result(
                command,
                True,
                {
                    "enabled": False,
                    "configured": False,
                    "connected": False,
                    "supported_backend": "not-opened",
                    "binding_digest": "",
                    "anchor_generation": None,
                    "anchor_health": "not-opened",
                    "scopes": [],
                    "pending_loopback": False,
                    "reconciliation": "disabled",
                    "trust_limit": "cooperating-process-cas-only",
                },
            )
            _emit(value, json_output=json_output, output=output)
            return EXIT_OK

        configuration = _configuration(args)
        if command == "configure":
            created = configure_port(configuration)
            if type(created) is not bool:
                raise GoogleWorkspaceHostV1UnknownOutcome(
                    "Google configuration outcome is unknown"
                )
            value = _result(
                command,
                True,
                {"configured": True, "created": created},
            )
            _emit(value, json_output=json_output, output=output)
            return EXIT_OK

        if command == "status" and _factory_port is None:
            value = _result(command, True, _status(status_port(configuration)))
            _emit(value, json_output=json_output, output=output)
            return EXIT_OK

        service = factory_port(
            gate=GoogleWorkspaceFeatureGateV1(True), configuration=configuration
        )
        if service is None:
            raise GoogleWorkspaceHostV1Denied("Google Workspace host is unavailable")
        try:
            if command == "status":
                payload = _status(service.status())
            elif command == "connect":
                payload = _receipt(service.connect())
            elif command == "disconnect":
                payload = _receipt(service.disconnect())
            elif command == "test-gmail":
                result = service.test_gmail()
                if type(result) is not GoogleReadResultV1:
                    raise GoogleWorkspaceHostV1UnknownOutcome("Google Gmail test outcome is unknown")
                payload = {
                    "item_count": len(result.items),
                    "has_more": result.has_more,
                    "receipt": _receipt(result.receipt),
                }
            elif command == "test-calendar":
                result = service.test_calendar(
                    time_min=args.time_min, time_max=args.time_max
                )
                if type(result) is not GoogleReadResultV1:
                    raise GoogleWorkspaceHostV1UnknownOutcome("Google Calendar test outcome is unknown")
                payload = {
                    "item_count": len(result.items),
                    "has_more": result.has_more,
                    "receipt": _receipt(result.receipt),
                }
            else:  # argparse makes this unreachable; keep the command set closed.
                raise GoogleWorkspaceHostV1ContractError("Google CLI command is invalid")
        finally:
            close = getattr(service, "close", None)
            if callable(close):
                close()
        value = _result(command, True, payload)
        _emit(value, json_output=json_output, output=output)
        return EXIT_OK
    except (GoogleWorkspaceHostV1ContractError, GoogleWorkspaceV1ContractError):
        value = _result(command, False, {"code": "invalid-input"})
        _emit(value, json_output=json_output, output=output)
        return EXIT_CONTRACT
    except (GoogleWorkspaceHostV1Denied, GoogleWorkspaceV1Denied):
        value = _result(command, False, {"code": "denied"})
        _emit(value, json_output=json_output, output=output)
        return EXIT_DENIED
    except (GoogleWorkspaceHostV1UnknownOutcome, GoogleWorkspaceV1UnknownOutcome):
        value = _result(command, False, {"code": "unknown-outcome"})
        _emit(value, json_output=json_output, output=output)
        return EXIT_UNKNOWN
    except Exception:
        value = _result(command, False, {"code": "denied"})
        _emit(value, json_output=json_output, output=output)
        return EXIT_DENIED


def main(argv: Sequence[str] | None = None) -> int:
    return run_cli_v1(sys.argv[1:] if argv is None else argv)


if __name__ == "__main__":
    raise SystemExit(main())

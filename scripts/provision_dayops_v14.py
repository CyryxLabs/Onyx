"""Provision the Onyx DayOps V14 Microsoft read-only binding."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path
from typing import Final, Sequence


# Keep the packaged helper from compiling the immutable integrity-source files
# that share its PyInstaller extraction directory.
sys.dont_write_bytecode = True
os.environ.setdefault("PYTHONDONTWRITEBYTECODE", "1")

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.dayops_provisioning_v14 import (  # noqa: E402
    DEFAULT_SIGN_IN_TIMEOUT_SECONDS,
    DayOpsProvisionerV14,
    DayOpsProvisioningConfigV14,
    DayOpsProvisioningV14Cancelled,
    DayOpsProvisioningV14ContractError,
    DayOpsProvisioningV14Error,
    DayOpsProvisioningV14Timeout,
)


FORBIDDEN_SECRET_OPTIONS: Final = (
    "--client-secret",
    "--password",
    "--passwd",
    "--access-token",
    "--refresh-token",
)


def _reject_secret_arguments(argv: Sequence[str]) -> None:
    for argument in argv:
        lowered = argument.casefold()
        if any(
            lowered == option or lowered.startswith(option + "=")
            for option in FORBIDDEN_SECRET_OPTIONS
        ):
            raise DayOpsProvisioningV14ContractError(
                "secret arguments are forbidden; use native sign-in"
            )


def _add_public_bindings(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--client-id",
        default=os.environ.get("ONYX_PHASE8_MS_GRAPH_CLIENT_ID"),
        required=os.environ.get("ONYX_PHASE8_MS_GRAPH_CLIENT_ID") is None,
    )
    parser.add_argument(
        "--tenant-id",
        default=os.environ.get("ONYX_PHASE8_MS_GRAPH_TENANT_ID"),
        required=os.environ.get("ONYX_PHASE8_MS_GRAPH_TENANT_ID") is None,
    )
    parser.add_argument(
        "--account-id",
        default=os.environ.get("ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID"),
        required=os.environ.get("ONYX_PHASE8_MS_GRAPH_ACCOUNT_ID") is None,
    )
    parser.add_argument(
        "--workspace-id",
        default=os.environ.get("ONYX_DAYOPS_WORKSPACE_ID"),
        required=os.environ.get("ONYX_DAYOPS_WORKSPACE_ID") is None,
    )
    parser.add_argument(
        "--principal-id",
        default=os.environ.get("ONYX_DAYOPS_PRINCIPAL_ID"),
        required=os.environ.get("ONYX_DAYOPS_PRINCIPAL_ID") is None,
    )
    parser.add_argument(
        "--alias",
        dest="credential_alias_name",
        default=os.environ.get("ONYX_DAYOPS_CREDENTIAL_ALIAS"),
        required=os.environ.get("ONYX_DAYOPS_CREDENTIAL_ALIAS") is None,
    )


def build_parser() -> argparse.ArgumentParser:
    program = (
        "Onyx-DayOps"
        if getattr(sys, "frozen", False)
        else "provision_dayops_v14"
    )
    parser = argparse.ArgumentParser(
        prog=program,
        description=(
            "Prepare the local Onyx DayOps V14 Microsoft Graph read-only binding"
        ),
        allow_abbrev=False,
    )
    commands = parser.add_subparsers(dest="command", required=True)
    for command in ("status", "prepare", "sign-in", "disconnect"):
        child = commands.add_parser(command, allow_abbrev=False)
        _add_public_bindings(child)
        if command == "sign-in":
            child.add_argument(
                "--timeout-seconds",
                type=int,
                default=DEFAULT_SIGN_IN_TIMEOUT_SECONDS,
            )
    return parser


def _config(args: argparse.Namespace) -> DayOpsProvisioningConfigV14:
    return DayOpsProvisioningConfigV14(
        args.client_id,
        args.tenant_id,
        args.account_id,
        args.workspace_id,
        args.principal_id,
        args.credential_alias_name,
    )


def _print_status(command: str, status: dict[str, str]) -> None:
    print(
        json.dumps(
            {"command": command, "result": "ok", **status},
            sort_keys=True,
            separators=(",", ":"),
        )
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    provisioner_factory=DayOpsProvisionerV14,
) -> int:
    selected = list(sys.argv[1:] if argv is None else argv)
    try:
        _reject_secret_arguments(selected)
        args = build_parser().parse_args(selected)
        provisioner = provisioner_factory(_config(args))
        now_ms = time.time_ns() // 1_000_000
        if args.command == "status":
            _print_status("status", provisioner.status(now_ms=now_ms).as_dict())
        elif args.command == "prepare":
            _print_status("prepare", provisioner.prepare(now_ms=now_ms).as_dict())
        elif args.command == "disconnect":
            _print_status(
                "disconnect", provisioner.disconnect(now_ms=now_ms).as_dict()
            )
        else:
            provisioner.sign_in(
                echo=print,
                now_ms=now_ms,
                timeout_seconds=args.timeout_seconds,
            )
            _print_status(
                "sign-in", provisioner.status(now_ms=now_ms).as_dict()
            )
        return 0
    except KeyboardInterrupt:
        print("DayOps sign-in cancelled.", file=sys.stderr)
        return 130
    except DayOpsProvisioningV14Cancelled:
        print("DayOps sign-in cancelled.", file=sys.stderr)
        return 130
    except DayOpsProvisioningV14Timeout:
        print("DayOps sign-in timed out.", file=sys.stderr)
        return 124
    except (DayOpsProvisioningV14ContractError, DayOpsProvisioningV14Error):
        print("DayOps provisioning failed closed.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

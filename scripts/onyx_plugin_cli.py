"""Machine-readable CLI for the default-off PluginHost V1 contract."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from core.plugin_runtime_v1 import PluginContractError, PluginHostV1  # noqa: E402
from core.plugin_docker_sandbox_v1 import (  # noqa: E402
    PluginDockerSandboxError,
    create_plugin_docker_sandbox_v1,
)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--registry", type=Path, required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument(
        "--allow-trusted-test-plugins", action="store_true", help=argparse.SUPPRESS
    )
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("status")
    commands.add_parser("list")
    for name in ("inspect", "enable", "disable", "remove"):
        item = commands.add_parser(name)
        item.add_argument("plugin_id")
    for name in ("install", "update"):
        item = commands.add_parser(name)
        item.add_argument("manifest", type=Path)
        item.add_argument("--approve", action="append", default=[])
    execute = commands.add_parser("execute")
    execute.add_argument("plugin_id")
    execute.add_argument("capability")
    execute.add_argument("--payload", default="null")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        native_sandbox, attestation_key = create_plugin_docker_sandbox_v1()
        host = PluginHostV1(
            args.registry,
            workspace_id=args.workspace,
            allow_trusted_test_plugins=args.allow_trusted_test_plugins,
            native_sandbox=native_sandbox,
            native_sandbox_attestation_key=attestation_key,
        )
        if args.command == "status":
            result: Any = host.status()
        elif args.command == "list":
            result = host.list()
        elif args.command == "inspect":
            result = host.inspect(args.plugin_id)
        elif args.command == "enable":
            result = host.enable(args.plugin_id)
        elif args.command == "disable":
            result = host.disable(args.plugin_id)
        elif args.command == "remove":
            result = host.remove(args.plugin_id)
        elif args.command in {"install", "update"}:
            result = getattr(host, args.command)(
                args.manifest, approved_capabilities=args.approve
            )
        else:
            try:
                payload = json.loads(args.payload)
            except json.JSONDecodeError as exc:
                raise PluginContractError(
                    "invalid_payload", "payload must be JSON"
                ) from exc
            result = host.execute(args.plugin_id, args.capability, payload)
        print(json.dumps({"ok": True, "result": result}, sort_keys=True))
        return 0
    except (PluginContractError, PluginDockerSandboxError) as exc:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": getattr(exc, "code", "sandbox_configuration_invalid"),
                        "message": str(exc),
                    },
                },
                sort_keys=True,
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

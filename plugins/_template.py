"""Original trusted-test plugin template for the Onyx PluginHost V1 protocol.

This template is not a sandbox and has no host authority. Production/untrusted
plugin execution remains blocked by PluginHost V1.
"""

from __future__ import annotations

import json
import sys

PROTOCOL_VERSION = "onyx.plugin/v1"


def main() -> int:
    try:
        request = json.loads(sys.stdin.readline())
        if (
            not isinstance(request, dict)
            or request.get("protocol_version") != PROTOCOL_VERSION
            or request.get("type") != "request"
            or request.get("capability") != "test.echo"
            or not isinstance(request.get("auth"), str)
        ):
            return 2
        response = {
            "protocol_version": PROTOCOL_VERSION,
            "type": "response",
            "auth": request["auth"],
            "ok": True,
            "result": request.get("payload"),
        }
        sys.stdout.write(json.dumps(response, separators=(",", ":")) + "\n")
        return 0
    except (EOFError, json.JSONDecodeError, OSError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

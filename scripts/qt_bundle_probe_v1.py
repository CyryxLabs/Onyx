"""Minimal frozen-runtime probe for the active PySide6/Qt toolchain."""

from __future__ import annotations

import json

from PySide6 import QtCore


def main() -> int:
    print(
        json.dumps(
            {
                "contract": "OnyxQtBundleProbe.v1",
                "qt_version": QtCore.qVersion(),
                "binding_version": QtCore.__version__,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

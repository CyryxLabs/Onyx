"""Action package bootstrap shared by every tool module."""

import sys


def _make_console_output_safe() -> None:
    """Prevent legacy Windows consoles from crashing on Unicode diagnostics."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(errors="replace")
            except (OSError, ValueError):
                pass


_make_console_output_safe()

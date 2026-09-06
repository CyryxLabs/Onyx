from __future__ import annotations

import ast
import asyncio
import importlib
from pathlib import Path
from unittest.mock import AsyncMock, patch

import actions.computer_control as computer_control
import actions.flight_finder as flight_finder
import actions.youtube_video as youtube_video
import core.paths as paths


ACTION_FILES = (
    "actions/browser_control.py",
    "actions/computer_control.py",
    "actions/dev_agent.py",
    "actions/flight_finder.py",
    "actions/youtube_video.py",
)


def test_five_desktop_consumers_do_not_construct_home_desktop() -> None:
    root = Path(__file__).parents[1]
    for relative in ACTION_FILES:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"))
        forbidden = [
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.BinOp)
            and isinstance(node.op, ast.Div)
            and isinstance(node.right, ast.Constant)
            and node.right.value == "Desktop"
            and "Path.home()" in ast.unparse(node.left)
        ]
        assert not forbidden, f"{relative} hardcodes Path.home() / Desktop"
        assert "user_desktop_dir" in (root / relative).read_text(encoding="utf-8")


def test_user_desktop_uses_onedrive_when_known_folder_is_unavailable(tmp_path) -> None:
    desktop = tmp_path / "Desktop"
    desktop.mkdir()
    with (
        patch.object(paths.platform, "system", return_value="Windows"),
        patch.object(paths, "_windows_known_folder", return_value=None),
        patch.dict(paths.os.environ, {"OneDriveCommercial": str(tmp_path)}, clear=False),
    ):
        assert paths.user_desktop_dir() == desktop


def test_desktop_behaviors_use_injected_resolution(tmp_path) -> None:
    page = AsyncMock()
    page.is_closed.return_value = False

    class Browser:
        async def _get_page(self):
            return page

    from actions.browser_control import _BrowserSession

    browser = _BrowserSession.__new__(_BrowserSession)
    browser._get_page = Browser()._get_page
    with patch("core.paths.user_desktop_dir", return_value=tmp_path):
        result = asyncio.run(browser.screenshot())
    expected = tmp_path / "onyx_screenshot.png"
    page.screenshot.assert_awaited_once_with(path=str(expected), full_page=False)
    assert str(expected) in result

    with patch("core.paths.user_desktop_dir", return_value=tmp_path):
        assert computer_control._safe_screenshot_path(None) == expected

    with (
        patch("core.paths.user_desktop_dir", return_value=tmp_path),
        patch.object(flight_finder.subprocess, "Popen"),
    ):
        flight_path = Path(flight_finder._save_to_desktop("data", "MCO", "JFK"))
    assert flight_path.parent == tmp_path

    with (
        patch("core.paths.user_desktop_dir", return_value=tmp_path),
        patch.object(youtube_video.subprocess, "Popen"),
    ):
        summary_path = Path(youtube_video._save_summary("summary", "https://youtu.be/x"))
    assert summary_path.parent == tmp_path

    with patch("core.paths.user_desktop_dir", return_value=tmp_path):
        import actions.dev_agent as dev_agent

        dev_agent = importlib.reload(dev_agent)
        assert dev_agent.ONYX_PROJECTS_DIR == tmp_path / "OnyxProjects"

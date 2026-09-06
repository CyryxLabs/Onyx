"""Read-only code assistance plus exact, host-approved local-file execution.

Model-generated source is never written or executed here. Project generation is
owned by ``dev_agent``, whose approval covers the complete immutable artifact set.
"""

from __future__ import annotations

import copy
import os
import tempfile
from pathlib import Path

from core.approved_execution import (
    execute_materialized_source,
    materialize_source_request,
    validate_materialized_source_request,
)
from core.paths import config_file, resource_root


def get_base_dir() -> Path:
    return resource_root()


BASE_DIR = get_base_dir()
API_CONFIG_PATH = config_file()
GEMINI_MODEL = "gemini-2.5-flash"
READ_ONLY_ACTIONS = frozenset({"explain", "screen_debug"})
EXECUTION_ACTIONS = frozenset({"run"})
SUPPORTED_ACTIONS = READ_ONLY_ACTIONS | EXECUTION_ACTIONS
DISABLED_GENERATIVE_ACTIONS = frozenset({"auto", "write", "edit", "build", "optimize"})


def _get_api_key() -> str:
    from core.credentials import get
    return get(required=True) or ""


def _get_gemini(model: str = GEMINI_MODEL):
    from google import genai

    client = genai.Client(api_key=_get_api_key())

    class _Model:
        def generate_content(self, contents):
            return client.models.generate_content(model=model, contents=contents)

    return _Model()


def _canonical_existing_file(value: object) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("an exact file path is required")
    path = Path(raw).expanduser().resolve(strict=True)
    if not path.is_file():
        raise ValueError(f"not a regular file: {path}")
    return str(path)


def materialize_code_helper_request(parameters: dict | None) -> dict:
    """Return the exact request that must be approved and then dispatched."""
    request = copy.deepcopy(dict(parameters or {}))
    action = str(request.get("action", "")).lower().strip().replace("-", "_")
    request["action"] = action

    if action == "run":
        request = materialize_source_request(request)
    elif action in READ_ONLY_ACTIONS and request.get("file_path"):
        request["file_path"] = _canonical_existing_file(request["file_path"])

    return request


def _read_file(file_path: str) -> tuple[str, str]:
    if not file_path:
        return "", "No file path provided."
    try:
        path = Path(file_path)
        if not path.is_absolute() or not path.is_file():
            return "", "An exact absolute file path is required."
        return path.read_text(encoding="utf-8"), ""
    except Exception as exc:
        return "", f"Could not read file: {exc}"


def _run_file(
    path: Path,
    args: list[str],
    timeout: int,
    approved_request: dict | None = None,
) -> str:
    """Compatibility wrapper that always reaches the identity-bound executor."""
    request = approved_request or materialize_source_request({
        "file_path": str(path), "args": args, "timeout": timeout,
    })
    return execute_materialized_source(request)


def _explain_action(file_path: str, code: str, player=None) -> str:
    if file_path and not code:
        code, error = _read_file(file_path)
        if error:
            return error
    if not code:
        return "Please provide code or an exact file path to explain."
    if player:
        player.write_log("[Code] Analyzing code (read-only)...")

    prompt = f"""Explain what this code does in simple, clear language.
Focus on what it does, how it works, risks, and important details.
Do not return a replacement file or claim that anything was changed.

Code:
{code[:6000]}

Explanation:"""
    try:
        return _get_gemini().generate_content(prompt).text.strip()
    except Exception as exc:
        return f"Could not explain code: {exc}"


def _take_screenshot() -> Path | None:
    try:
        import pyautogui

        descriptor, name = tempfile.mkstemp(prefix="onyx_debug_", suffix=".png")
        os.close(descriptor)
        path = Path(name)
        pyautogui.screenshot().save(str(path))
        return path
    except Exception as exc:
        print(f"[Code] Screenshot failed: {exc}")
        return None


def _screen_debug_action(description: str, file_path: str, player=None) -> str:
    if player:
        player.write_log("[Code] Capturing screen for read-only analysis...")
    screenshot_path = _take_screenshot()
    if not screenshot_path:
        return "Could not take a screenshot. Make sure PyAutoGUI is installed."

    try:
        from google import genai
        from google.genai import types

        context = ""
        if file_path:
            file_content, error = _read_file(file_path)
            if error:
                return error
            context = f"\n\nRelated file (read-only):\n```\n{file_content[:4000]}\n```"
        prompt = f"""Analyze this screenshot as a programmer and debugger.
Question: {description or 'What problem is visible and how should the user fix it?'}{context}

Identify visible errors, explain the likely cause, and suggest a fix. This is
analysis only: do not claim that any file was changed or executed."""
        client = genai.Client(api_key=_get_api_key())
        response = client.models.generate_content(
            model=GEMINI_MODEL,
            contents=[
                types.Part.from_bytes(data=screenshot_path.read_bytes(), mime_type="image/png"),
                prompt,
            ],
        )
        return response.text.strip()
    except Exception as exc:
        return f"Screen analysis failed: {exc}"
    finally:
        screenshot_path.unlink(missing_ok=True)


def code_helper(
    parameters: dict,
    response=None,
    player=None,
    session_memory=None,
    speak=None,
) -> str:
    """Explain code, analyze a screen, or run one exactly approved local file."""
    del response, session_memory, speak
    raw = dict(parameters or {})
    action = str(raw.get("action", "")).lower().strip().replace("-", "_")

    if action in DISABLED_GENERATIVE_ACTIONS:
        return (
            f"Code helper action '{action}' is disabled because it could generate, write, "
            "or execute content that was not part of the approval. Use dev_agent for "
            "project generation with immutable artifact approval."
        )
    if action not in SUPPORTED_ACTIONS:
        return "Unknown code helper action. Use explain, screen_debug, or run."

    try:
        if action == "run":
            request = validate_materialized_source_request(raw)
            request["action"] = action
        else:
            request = materialize_code_helper_request(raw)
    except (OSError, ValueError) as exc:
        return f"Code helper request rejected: {exc}"

    if action == "explain":
        return _explain_action(
            request.get("file_path", ""), str(request.get("code", "")).strip(), player
        )
    if action == "screen_debug":
        return _screen_debug_action(
            str(request.get("description", "")).strip(), request.get("file_path", ""), player
        )

    if player:
        player.write_log(f"[Code] Running approved file {Path(request['file_path']).name}...")
    return _run_file(
        Path(request["file_path"]),
        request["args"],
        request["timeout"],
        approved_request=request,
    )

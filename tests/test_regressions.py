import ast
import asyncio
import copy
import ctypes
import errno
import hashlib
import importlib
import importlib.util
import json
import secrets
import os
import shutil
import socket
import stat
import subprocess
import sys
import tempfile
import threading
import time
import unittest
import zipfile
from datetime import date
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock, patch

from actions import file_controller
from actions import file_processor as file_processor_module
from actions import code_helper as code_helper_module
from actions import computer_control, dev_agent
from actions import computer_settings
from actions import send_message as send_message_module
from actions import desktop
from actions import flight_finder
from actions.file_processor import (
    _process_archive,
    _process_audio,
    _process_code,
    _process_data,
    _process_image,
    _process_pdf,
    _process_text_doc,
    _process_xml,
)
from core import permission_broker
from core.approved_execution import (
    execute_materialized_source,
    materialize_source_request,
)


ROOT = Path(__file__).resolve().parents[1]


def _main_tool_declarations():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    assignment = next(
        node
        for node in tree.body
        if isinstance(node, ast.Assign)
        and any(
            isinstance(target, ast.Name) and target.id == "TOOL_DECLARATIONS"
            for target in node.targets
        )
    )
    return ast.literal_eval(assignment.value)


class ToolWiringTests(unittest.TestCase):
    def test_every_declared_tool_has_a_dispatch_branch(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        declarations = None
        dispatched = set()

        for node in ast.walk(tree):
            if isinstance(node, ast.Assign):
                if any(
                    isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                    for t in node.targets
                ):
                    declarations = ast.literal_eval(node.value)
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name)
                and node.left.id == "name"
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.Eq)
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], ast.Constant)
                and isinstance(node.comparators[0].value, str)
            ):
                dispatched.add(node.comparators[0].value)
            if (
                isinstance(node, ast.Compare)
                and isinstance(node.left, ast.Name)
                and node.left.id == "name"
                and len(node.ops) == 1
                and isinstance(node.ops[0], ast.In)
                and len(node.comparators) == 1
                and isinstance(node.comparators[0], (ast.Tuple, ast.List, ast.Set))
            ):
                values = node.comparators[0].elts
                if all(
                    isinstance(item, ast.Constant) and isinstance(item.value, str)
                    for item in values
                ):
                    dispatched.update(item.value for item in values)

        self.assertIsNotNone(declarations)
        declared = {item["name"] for item in declarations}
        self.assertSetEqual(declared, dispatched)

    def test_tool_names_are_unique(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        names = [item["name"] for item in ast.literal_eval(assignment.value)]
        self.assertEqual(len(names), len(set(names)))

    def test_prompt_special_mission_tools_are_model_exposed(self):
        prompt = (ROOT / "core" / "prompt.txt").read_text(encoding="utf-8")
        declared = {item["name"] for item in _main_tool_declarations()}
        referenced = {
            name
            for name in (
                "mission_create",
                "mission_status",
                "mission_run",
                "mission_cancel",
                "mission_reconcile",
            )
            if f"{name}:" in prompt
        }
        self.assertSetEqual(
            referenced,
            {
                "mission_create",
                "mission_status",
                "mission_run",
                "mission_cancel",
                "mission_reconcile",
            },
        )
        self.assertLessEqual(referenced, declared)
        self.assertNotIn("agent_task", prompt)

    def test_every_declared_tool_has_a_central_risk_policy(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        declared = {item["name"] for item in ast.literal_eval(assignment.value)}
        self.assertEqual(len(declared), 39)
        self.assertSetEqual(
            declared,
            set(permission_broker.MODEL_TOOL_POLICIES) | {"capability_expansion"},
        )

    def test_mission_reconcile_requires_exact_owner_confirmation_even_autonomous(self):
        arguments = {
            "mission_id": "mis_" + "a" * 32,
            "decision": "still_unknown",
        }
        observed = []
        permission_broker.set_trust_profile("autonomous")
        permission_broker.configure_owner_autonomy(True, [str(ROOT)])
        permission_broker.set_permission_callback(None)
        permission_broker._audit_healthy = True
        try:
            with patch.object(permission_broker, "append_tool_audit"):
                approved, _reason = permission_broker.authorize_model_tool(
                    "mission_reconcile", arguments
                )
                self.assertFalse(approved)
                permission_broker.set_permission_callback(
                    lambda request: observed.append(request) or request["digest"]
                )
                approved, digest = permission_broker.authorize_model_tool(
                    "mission_reconcile", arguments
                )
            self.assertTrue(approved)
            self.assertEqual(observed[0]["details"]["arguments"], arguments)
            self.assertEqual(digest, observed[0]["digest"])
        finally:
            permission_broker.set_permission_callback(None)
            permission_broker.configure_owner_autonomy(False, [])
            permission_broker.set_trust_profile("cautious")

    def test_action_policies_are_complete_and_schemas_require_explicit_actions(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        declarations = {
            item["name"]: item["parameters"]
            for item in ast.literal_eval(assignment.value)
        }
        action_tools = {
            name
            for name, policy in permission_broker.MODEL_TOOL_POLICIES.items()
            if policy == "action_policy"
        }
        self.assertSetEqual(action_tools, set(permission_broker.MODEL_TOOL_ACTIONS))
        for tool in action_tools:
            with self.subTest(tool=tool):
                self.assertTrue(permission_broker.MODEL_TOOL_ACTIONS[tool])
                self.assertIn("action", declarations[tool]["required"])
        for tool, actions in permission_broker._PROMPT_FREE_ACTIONS.items():
            self.assertLessEqual(actions, permission_broker.MODEL_TOOL_ACTIONS[tool])

    def test_computer_settings_policy_matches_dispatcher_actions(self):
        special_actions = {
            "volume_set",
            "type_text",
            "write_on_screen",
            "type",
            "write",
            "press_key",
            "reload_n",
            "refresh_n",
            "reload_page_n",
            # Login registration is dispatched ahead of ACTION_MAP because it
            # needs no desktop automation and must still work headless.
            "enable_autostart",
            "disable_autostart",
            "autostart_status",
        }
        expected = set(computer_settings.ACTION_MAP) | special_actions
        self.assertSetEqual(
            expected,
            set(permission_broker.MODEL_TOOL_ACTIONS["computer_settings"]),
        )

    def test_declared_parameters_cover_confirmation_and_form_actions(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        declarations = {
            item["name"]: set(item["parameters"]["properties"])
            for item in ast.literal_eval(assignment.value)
        }
        self.assertNotIn("confirmed", declarations["computer_settings"])
        self.assertIn("fields", declarations["browser_control"])
        self.assertTrue(
            {"x1", "y1", "x2", "y2"}.issubset(declarations["computer_control"])
        )
        self.assertNotIn("confirmed", declarations["dev_agent"])
        self.assertNotIn("task", declarations["desktop_control"])
        self.assertFalse(
            {"language", "output_path", "instruction"} & declarations["code_helper"]
        )

    def test_generation_bypass_actions_are_not_model_exposed(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        declarations = {
            item["name"]: item for item in ast.literal_eval(assignment.value)
        }
        desktop_action = declarations["desktop_control"]["parameters"]["properties"][
            "action"
        ]["description"]
        code_action = declarations["code_helper"]["parameters"]["properties"]["action"][
            "description"
        ]
        self.assertNotIn("task", desktop_action)
        for action in code_helper_module.DISABLED_GENERATIVE_ACTIONS:
            self.assertNotIn(action, code_action)
        self.assertSetEqual(
            set(permission_broker.MODEL_TOOL_ACTIONS["code_helper"]),
            set(code_helper_module.SUPPORTED_ACTIONS),
        )

    def test_web_search_schema_expresses_conditional_runtime_requirements(self):
        tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
        assignment = next(
            node
            for node in tree.body
            if isinstance(node, ast.Assign)
            and any(
                isinstance(t, ast.Name) and t.id == "TOOL_DECLARATIONS"
                for t in node.targets
            )
        )
        web = next(
            item
            for item in ast.literal_eval(assignment.value)
            if item["name"] == "web_search"
        )["parameters"]
        self.assertNotIn("query", web["required"])
        self.assertIn(
            "omit only for compare", web["properties"]["query"]["description"]
        )

    @unittest.skipUnless(
        importlib.util.find_spec("PySide6") and importlib.util.find_spec("sounddevice"),
        "full runtime dependencies not installed",
    )
    def test_full_runtime_entrypoint_imports(self):
        module = importlib.import_module("main")
        self.assertTrue(hasattr(module, "OnyxLive"))


class FileSafetyTests(unittest.TestCase):
    def test_model_derived_file_outputs_never_write_before_exact_output_approval(self):
        generated = "UNSEEN_MODEL_OUTPUT\nPath('../owned').write_text('unsafe')"
        model = Mock()
        model.generate_content.return_value = SimpleNamespace(text=generated)

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            image = root / "photo.png"
            pdf = root / "document.pdf"
            text = root / "notes.txt"
            code = root / "app.py"
            audio = root / "clip.wav"
            for source in (image, pdf, audio):
                source.write_bytes(b"source bytes")
            text.write_text("original prose", encoding="utf-8")
            code.write_text("print('original')\n", encoding="utf-8")

            pdf_doc = SimpleNamespace(
                pages=[SimpleNamespace(extract_text=lambda: "original PDF text")]
            )
            pdf_open = MagicMock()
            pdf_open.return_value.__enter__.return_value = pdf_doc

            with (
                patch.object(
                    file_processor_module, "_gemini_client", return_value=model
                ),
                patch("PIL.Image.open", return_value=Mock()),
                patch("pdfplumber.open", pdf_open),
            ):
                cases = (
                    (
                        _process_image(image, "ocr", {"save": True}),
                        root / "photo_ocr_result.txt",
                    ),
                    (
                        _process_pdf(pdf, "summarize", {"save": True}),
                        root / "document_summarize.txt",
                    ),
                    (
                        _process_text_doc(text, "text", "fix", {"save": True}),
                        root / "notes_fix.txt",
                    ),
                    (
                        _process_code(code, "fix", {"save": True}),
                        root / "app_fix.py",
                    ),
                    (
                        _process_audio(audio, "transcribe", {"save": True}),
                        root / "clip_transcript.txt",
                    ),
                )

            for result, proposed in cases:
                with self.subTest(proposed=proposed.name):
                    self.assertIn(generated, result)
                    self.assertIn("PREVIEW ONLY - NOT SAVED", result)
                    self.assertIn("requested save was refused", result)
                    self.assertIn(str(proposed), result)
                    self.assertFalse(proposed.exists())
            self.assertFalse((root.parent / "owned").exists())

    def test_model_derived_output_is_preview_only_when_save_is_omitted(self):
        model = Mock()
        model.generate_content.return_value = SimpleNamespace(text="optimized preview")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(file_processor_module, "_gemini_client", return_value=model),
        ):
            source = Path(tmp) / "app.py"
            source.write_text("print('original')\n", encoding="utf-8")
            result = _process_code(source, "optimize", {})
            proposed = Path(tmp) / "app_optimize.py"
            self.assertIn("preview-only by default", result)
            self.assertIn(str(proposed), result)
            self.assertFalse(proposed.exists())

    def test_rename_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = root / "safe.txt"
            source.write_text("safe", encoding="utf-8")
            with patch.object(file_controller, "_SAFE_ROOTS", [root]):
                result = file_controller.rename_file(
                    str(source), new_name="../escaped.txt"
                )
            self.assertTrue(
                "must not contain a path" in result or "Access denied" in result,
                result,
            )
            self.assertTrue(source.exists())
            self.assertFalse((root.parent / "escaped.txt").exists())

    def test_xml_is_validated_and_formatted_as_xml(self):
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "sample.xml"
            source.write_text("<root><item>value</item></root>", encoding="utf-8")
            self.assertIn("Valid XML", _process_xml(source, "validate", {}))
            result = _process_xml(source, "format", {})
            self.assertIn("Formatted XML saved", result)
            formatted = Path(tmp) / "sample_formatted.xml"
            self.assertTrue(formatted.exists())
            self.assertIn("<?xml", formatted.read_text(encoding="utf-8"))

    def test_archive_extraction_rejects_parent_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            archive = root / "unsafe.zip"
            with zipfile.ZipFile(archive, "w") as zf:
                zf.writestr("../escaped.txt", "unsafe")
            destination = root / "output"
            result = _process_archive(
                archive,
                "extract",
                {"destination": str(destination)},
            )
            self.assertIn("Unsafe archive member path", result)
            self.assertFalse((root / "escaped.txt").exists())

    @unittest.skipUnless(importlib.util.find_spec("pandas"), "pandas not installed")
    def test_excel_sort_writes_a_real_excel_workbook(self):
        import pandas as pd

        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "data.xlsx"
            pd.DataFrame({"value": [2, 1]}).to_excel(source, index=False)
            result = _process_data(source, "excel", "sort", {"column": "value"})
            self.assertIn("Sorted", result)
            output = Path(tmp) / "data_sorted.xlsx"
            values = pd.read_excel(output)["value"].tolist()
            self.assertEqual(values, [1, 2])

    def test_flight_url_contains_requested_route_not_stale_hardcoded_data(self):
        url = flight_finder._build_google_flights_url(
            "MIA", "LHR", "2026-08-10", "2026-08-17", 2, "business"
        )
        self.assertIn("MIA", url)
        self.assertIn("LHR", url)
        self.assertIn("2026-08-10", url)
        self.assertIn("2026-08-17", url)
        self.assertNotIn("2025-03-15", url)
        self.assertNotIn("SVNU", url)


class CodeExecutionTests(unittest.TestCase):
    def tearDown(self):
        permission_broker.set_permission_callback(None)

    def test_model_confirmation_never_authorizes_consequential_tools(self):
        cases = [
            ("computer_control", {"action": "click", "confirmed": True}),
            ("file_controller", {"action": "delete", "confirmed": True}),
            ("browser_control", {"action": "fill_form", "confirmed": True}),
            ("game_updater", {"action": "install", "confirmed": True}),
            ("send_message", {"receiver": "Ada", "confirmed": True}),
            ("desktop_control", {"action": "clean", "confirmed": True}),
        ]
        for tool, args in cases:
            with self.subTest(tool=tool):
                approved, reason = permission_broker.authorize_model_tool(tool, args)
                self.assertFalse(approved)
                self.assertIn("no trusted host", reason)

    def test_trusted_host_must_return_exact_permission_digest(self):
        permission_broker.set_permission_callback(lambda request: request["digest"])
        approved, digest = permission_broker.authorize_model_tool(
            "computer_control", {"action": "hotkey", "keys": "ctrl+s"}
        )
        self.assertTrue(approved)
        self.assertRegex(digest, r"^[0-9a-f]{64}$")

    def test_only_non_sensitive_non_mutating_actions_skip_prompt(self):
        for tool, args in (
            ("computer_control", {"action": "random_data"}),
            ("computer_control", {"action": "wait"}),
            ("youtube_video", {"action": "get_info"}),
            ("youtube_video", {"action": "trending"}),
            ("close_camera", {}),
        ):
            with self.subTest(tool=tool):
                self.assertEqual(
                    permission_broker.authorize_model_tool(tool, args), (True, "")
                )

    def test_private_reads_and_all_browser_actions_require_trusted_approval(self):
        private_cases = {
            "browser_control": permission_broker.MODEL_TOOL_ACTIONS["browser_control"],
            "file_controller": permission_broker.MODEL_TOOL_ACTIONS["file_controller"],
            "file_processor": permission_broker.MODEL_TOOL_ACTIONS["file_processor"],
            "desktop_control": permission_broker.MODEL_TOOL_ACTIONS["desktop_control"],
            "game_updater": permission_broker.MODEL_TOOL_ACTIONS["game_updater"],
            "computer_settings": permission_broker.MODEL_TOOL_ACTIONS[
                "computer_settings"
            ],
        }
        for tool, actions in private_cases.items():
            for action in actions:
                args = {"action": action}
                if tool == "file_processor":
                    args["file_path"] = str(ROOT / "readme.md")
                approved, reason = permission_broker.authorize_model_tool(tool, args)
                with self.subTest(tool=tool, action=action):
                    self.assertFalse(approved)
                    if tool == "file_processor" and action == "run":
                        self.assertIn("not materialized", reason)
                    else:
                        self.assertIn("no trusted host", reason)

        for tool, args in (
            ("system_status", {}),
            ("computer_control", {"action": "copy"}),
            ("computer_control", {"action": "user_data"}),
            ("computer_control", {"action": "screen_find"}),
            ("code_helper", {"action": "explain"}),
        ):
            with self.subTest(tool=tool, args=args):
                approved, reason = permission_broker.authorize_model_tool(tool, args)
                self.assertFalse(approved)
                self.assertIn("no trusted host", reason)

    def test_safety_stop_is_prompt_free_but_broad_shutdowns_are_gated(self):
        self.assertEqual(
            permission_broker.authorize_model_tool("close_camera", {}),
            (True, ""),
        )
        for tool, args in (
            ("browser_control", {"action": "close"}),
            ("browser_control", {"action": "close_all"}),
            ("computer_settings", {"action": "close_app"}),
            ("computer_settings", {"action": "shutdown"}),
            ("shutdown_onyx", {}),
        ):
            with self.subTest(tool=tool, args=args):
                approved, reason = permission_broker.authorize_model_tool(tool, args)
                self.assertFalse(approved)
                self.assertIn("no trusted host", reason)

    def test_outbound_search_and_weather_require_exact_trusted_approval(self):
        requests = []

        def callback(request):
            requests.append(request)
            return request["digest"]

        permission_broker.set_permission_callback(callback)
        for tool, args in (
            ("web_search", {"mode": "search", "query": "private medical phrase"}),
            ("web_search", {"mode": "compare", "items": ["private A", "private B"]}),
            ("weather_report", {"city": "Exact Home City", "time": "now"}),
        ):
            with self.subTest(tool=tool):
                approved, digest = permission_broker.authorize_model_tool(tool, args)
                self.assertTrue(approved)
                self.assertRegex(digest, r"^[0-9a-f]{64}$")
                self.assertEqual(requests[-1]["details"]["arguments"], args)

    def test_web_search_rejects_invalid_conditional_arguments_before_prompt(self):
        callback = Mock(side_effect=AssertionError("invalid search prompted"))
        permission_broker.set_permission_callback(callback)
        for args in (
            {"mode": "search"},
            {"mode": "news", "query": ""},
            {"mode": "compare", "items": ["only one"]},
            {"mode": "unknown", "query": "topic"},
        ):
            with self.subTest(args=args):
                approved, reason = permission_broker.authorize_model_tool(
                    "web_search", args
                )
                self.assertFalse(approved)
                self.assertIn("Permission denied", reason)
        callback.assert_not_called()

    def test_web_search_runtime_accepts_item_only_compare_and_rejects_blank_query(self):
        from actions import web_search

        with patch.object(web_search, "_compare", return_value="compared") as compare:
            result = web_search.web_search(
                {
                    "mode": "compare",
                    "items": [" Alpha ", "Beta"],
                    "aspect": "features",
                }
            )
        self.assertEqual(result, "compared")
        compare.assert_called_once_with(["Alpha", "Beta"], "features")

        with patch.object(
            web_search, "_search", side_effect=AssertionError("network used")
        ):
            result = web_search.web_search({"mode": "search", "query": ""})
        self.assertIn("requires a query", result)

    def test_random_password_generation_uses_a_cryptographic_rng(self):
        self.assertIsInstance(computer_control._RNG, secrets.SystemRandom)
        password = computer_control._random_data("password")
        self.assertEqual(len(password), 12)
        self.assertRegex(password, r"[A-Z]")
        self.assertRegex(password, r"[0-9]")
        self.assertRegex(password, r"[!@#$%]")

    def test_headless_pyautogui_import_fails_closed_without_blocking_startup(self):
        for module_under_test in (
            computer_control,
            computer_settings,
            send_message_module,
        ):
            with self.subTest(module=module_under_test.__name__):
                platform_module = getattr(
                    module_under_test,
                    "host_platform",
                    getattr(module_under_test, "platform", None),
                )
                with (
                    patch.object(platform_module, "system", return_value="Windows"),
                    patch.object(
                        module_under_test.importlib,
                        "import_module",
                        side_effect=KeyError("DISPLAY"),
                    ),
                ):
                    module, error = module_under_test._load_pyautogui()

                self.assertIsNone(module)
                self.assertEqual(error, "KeyError")

        with (
            patch.object(computer_control, "_PYAUTOGUI", False),
            patch.object(computer_control, "_PYAUTOGUI_ERROR", "KeyError"),
        ):
            with self.assertRaisesRegex(
                RuntimeError,
                "unavailable in the current desktop session.*KeyError",
            ):
                computer_control._require_pyautogui()

    def test_pyautogui_is_lazy_and_linux_headless_guard_never_imports_it(self):
        for module_under_test in (
            computer_control,
            computer_settings,
            send_message_module,
        ):
            with self.subTest(module=module_under_test.__name__):
                platform_module = getattr(
                    module_under_test,
                    "host_platform",
                    getattr(module_under_test, "platform", None),
                )
                with (
                    patch.object(platform_module, "system", return_value="Linux"),
                    patch.dict(os.environ, {}, clear=True),
                    patch.object(
                        module_under_test.importlib,
                        "import_module",
                        side_effect=AssertionError("headless import attempted"),
                    ),
                ):
                    loaded, error = module_under_test._load_pyautogui()
                self.assertIsNone(loaded)
                self.assertEqual(error, "headless_session")

    def test_blank_unknown_and_unmaterialized_actions_fail_without_prompting(self):
        callback = Mock(side_effect=AssertionError("invalid call prompted the user"))
        permission_broker.set_permission_callback(callback)
        cases = (
            [(tool, {"action": ""}) for tool in permission_broker.MODEL_TOOL_ACTIONS]
            + [
                (tool, {"action": "definitely_not_a_real_action"})
                for tool in permission_broker.MODEL_TOOL_ACTIONS
            ]
            + [
                ("file_processor", {"action": "info", "file_path": ""}),
                (
                    "code_helper",
                    {
                        "action": "run",
                        "file_path": "relative.py",
                        "args": [],
                        "timeout": 30,
                    },
                ),
            ]
        )
        for tool, args in cases:
            with self.subTest(tool=tool, args=args):
                approved, reason = permission_broker.authorize_model_tool(tool, args)
                self.assertFalse(approved)
                self.assertIn("Permission denied", reason)
        callback.assert_not_called()

    def test_computer_settings_never_uses_second_model_action_inference(self):
        with patch.object(computer_settings, "_PYAUTOGUI", True):
            result = computer_settings.computer_settings(
                {
                    "description": "shut down this computer",
                }
            )
        self.assertEqual(result, "No explicit action provided.")

    def test_youtube_summary_only_skips_prompt_when_it_will_not_write(self):
        self.assertEqual(
            permission_broker.authorize_model_tool(
                "youtube_video", {"action": "summarize", "save": False}
            ),
            (True, ""),
        )
        approved, reason = permission_broker.authorize_model_tool(
            "youtube_video", {"action": "summarize", "save": True}
        )
        self.assertFalse(approved)
        self.assertIn("no trusted host", reason)

    def test_memory_search_is_declared_and_requires_trusted_approval(self):
        declarations = _main_tool_declarations()
        memory_tool = next(
            item for item in declarations if item["name"] == "memory_search"
        )
        self.assertEqual(memory_tool["parameters"]["required"], ["query"])
        approved, reason = permission_broker.authorize_model_tool(
            "memory_search", {"query": "prior project decision"}
        )
        self.assertFalse(approved)
        self.assertIn("no trusted host", reason)
        denied, reason = permission_broker.authorize_model_tool(
            "memory_search", {"query": ""}
        )
        self.assertFalse(denied)
        self.assertIn("requires a query", reason)

    @unittest.skipUnless(
        importlib.util.find_spec("PySide6") and importlib.util.find_spec("sounddevice"),
        "full runtime dependencies not installed",
    )
    def test_memory_search_live_dispatch_returns_bounded_cited_context(self):
        import main

        class UI:
            muted = True

            @staticmethod
            def set_state(_state):
                return None

        onyx_live = object.__new__(main.OnyxLive)
        onyx_live.ui = UI()
        call = SimpleNamespace(
            name="memory_search", args={"query": "Onyx project"}, id="mem-1"
        )
        context = "[ONYX MEMORY — UNTRUSTED REFERENCE DATA]\n[source: project:1]"
        with (
            patch.object(
                main, "authorize_model_tool", return_value=(True, "digest")
            ) as authorize,
            patch.object(main, "search_memory_context", return_value=context) as search,
        ):
            response = asyncio.run(onyx_live._execute_tool(call))
        authorize.assert_called_once_with("memory_search", {"query": "Onyx project"})
        search.assert_called_once_with("Onyx project", limit=8, max_chars=1800)
        self.assertEqual(response.response["result"], context)

    @unittest.skipUnless(
        importlib.util.find_spec("PySide6") and importlib.util.find_spec("sounddevice"),
        "full runtime dependencies not installed",
    )
    def test_file_processor_approval_receives_exact_materialized_path(self):
        import main

        with tempfile.TemporaryDirectory() as tmp:
            relative = Path(tmp) / "folder" / ".." / "private.txt"
            expected = str(relative.expanduser().resolve(strict=False))

            class UI:
                current_file = str(relative)
                muted = True

                @staticmethod
                def set_state(_state):
                    return None

            onyx_live = object.__new__(main.OnyxLive)
            onyx_live.ui = UI()
            call = SimpleNamespace(
                name="file_processor", args={"action": "info"}, id="1"
            )
            with patch.object(
                main,
                "authorize_model_tool",
                return_value=(False, "denied"),
            ) as authorize:
                asyncio.run(onyx_live._execute_tool(call))

        approved_args = authorize.call_args.args[1]
        self.assertEqual(approved_args["file_path"], expected)

    @unittest.skipUnless(
        importlib.util.find_spec("PySide6") and importlib.util.find_spec("sounddevice"),
        "full runtime dependencies not installed",
    )
    def test_code_run_approval_and_dispatch_share_exact_materialized_artifact(self):
        import main

        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "folder").mkdir()
            script = Path(tmp) / "folder" / ".." / "approved.py"
            script.write_text("print('approved')\n", encoding="utf-8")

            class UI:
                muted = True

                @staticmethod
                def set_state(_state):
                    return None

            onyx_live = object.__new__(main.OnyxLive)
            onyx_live.ui = UI()
            onyx_live.speak = Mock()
            call = SimpleNamespace(
                name="code_helper",
                args={
                    "action": "run",
                    "file_path": str(script),
                    "args": '--name "Ada Lovelace"',
                    "timeout": "41",
                },
                id="1",
            )
            approved_payloads = []

            def approve(_name, arguments):
                approved_payloads.append(copy.deepcopy(arguments))
                return True, "digest"

            with (
                patch.object(main, "authorize_model_tool", side_effect=approve),
                patch.object(main, "code_helper", return_value="ok") as execute,
            ):
                asyncio.run(onyx_live._execute_tool(call))

        dispatched = execute.call_args.kwargs["parameters"]
        self.assertEqual(approved_payloads[0], dispatched)
        self.assertEqual(dispatched["file_path"], str(script.resolve()))
        self.assertEqual(dispatched["args"], ["--name", "Ada Lovelace"])
        self.assertEqual(dispatched["timeout"], 41)

    @unittest.skipUnless(
        importlib.util.find_spec("PySide6") and importlib.util.find_spec("sounddevice"),
        "full runtime dependencies not installed",
    )
    def test_async_tool_approval_never_blocks_heartbeat_and_preserves_deny(self):
        import main

        class UI:
            muted = True

            @staticmethod
            def set_state(_state):
                return None

        onyx_live = object.__new__(main.OnyxLive)
        onyx_live.ui = UI()
        onyx_live.speak = Mock()
        onyx_live.speak_error = Mock()
        call = SimpleNamespace(name="open_app", args={"app_name": "calculator"}, id="1")
        entered = threading.Event()
        release = threading.Event()

        def blocking_approval(_name, _arguments):
            entered.set()
            if not release.wait(timeout=2):
                return False, "event loop was blocked"
            return True, "digest"

        async def approve_scenario():
            task = asyncio.create_task(onyx_live._execute_tool(call))
            deadline = asyncio.get_running_loop().time() + 1
            while not entered.is_set() and asyncio.get_running_loop().time() < deadline:
                await asyncio.sleep(0.001)
            heartbeats = 0
            for _ in range(3):
                await asyncio.sleep(0.005)
                heartbeats += 1
            release.set()
            return heartbeats, await task

        with (
            patch.object(main, "authorize_model_tool", side_effect=blocking_approval),
            patch.object(main, "open_app", return_value="opened") as execute,
        ):
            heartbeats, response = asyncio.run(approve_scenario())
        self.assertEqual(heartbeats, 3)
        execute.assert_called_once()
        self.assertEqual(response.response["result"], "opened")

        with (
            patch.object(main, "authorize_model_tool", return_value=(False, "denied")),
            patch.object(main, "open_app") as denied_execute,
        ):
            denied = asyncio.run(onyx_live._execute_tool(call))
        denied_execute.assert_not_called()
        self.assertEqual(denied.response["result"], "denied")

    def test_dev_approval_covers_exact_content_and_project_path(self):
        request = dev_agent._approval_request(
            "demo",
            "python",
            "safe",
            30,
            {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            },
            Path("C:/tmp/safe"),
            {"main.py": "print('one')"},
        )
        changed = dict(request)
        changed["files"] = [dict(request["files"][0], content="print('two')")]
        self.assertNotEqual(request["digest"], dev_agent._request_digest(changed))

    def test_dev_executor_revalidates_full_schema_before_side_effects(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "demo"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "demo",
                "python",
                "demo",
                30,
                plan,
                project,
                {"main.py": "print('safe')\n"},
            )
            request["files"].append(dict(request["files"][0]))
            request["digest"] = dev_agent._request_digest(request)
            result = dev_agent._execute_approved_artifacts(request, request["digest"])
        self.assertIn("unique", result)
        self.assertFalse(project.exists())

    def test_dev_executor_writes_exact_approved_bytes_and_uses_approved_timeout(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "demo"
            content = "import sys\nprint('safe', sys.argv[1])\n"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py exact-arg",
            }
            request = dev_agent._approval_request(
                "demo",
                "python",
                "demo",
                47,
                plan,
                project,
                {"main.py": content},
            )
            original_run = dev_agent._run_verified_entry
            observed = {}

            def run_exact_bytes(*args):
                observed["args"] = args
                return original_run(*args)

            with patch.object(
                dev_agent, "_run_verified_entry", side_effect=run_exact_bytes
            ):
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
            self.assertIn("created", result)
            self.assertIn("safe exact-arg", result)
            self.assertEqual(
                (project / "main.py").read_bytes(), content.encode("utf-8")
            )
            self.assertEqual(observed["args"][1], content.encode("utf-8"))
            self.assertEqual(observed["args"][2], ["exact-arg"])
            self.assertEqual(observed["args"][4], 47)
            self.assertEqual(observed["args"][3].name, "project")
            self.assertFalse((project / ".venv").exists())

    def test_dev_executor_never_runs_a_requested_path_replacement(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "race"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py --approved",
            }
            approved = "import sys\nprint('approved', sys.argv[1])\n"
            request = dev_agent._approval_request(
                "race",
                "python",
                "race",
                20,
                plan,
                project,
                {"main.py": approved},
            )
            original_run = dev_agent._run_verified_entry

            def replace_requested_path(*args):
                project.mkdir()
                (project / "main.py").write_text(
                    "print('replacement')\n", encoding="utf-8"
                )
                return original_run(*args)

            with patch.object(
                dev_agent, "_run_verified_entry", side_effect=replace_requested_path
            ):
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
            self.assertIn("target appeared", result)
            self.assertNotIn("replacement\n", result)
            self.assertEqual(
                project.joinpath("main.py").read_text(encoding="utf-8"),
                "print('replacement')\n",
            )

    def test_dev_executor_holds_entry_bytes_if_snapshot_path_is_replaced_before_run(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "snapshot_race"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "race",
                "python",
                "snapshot_race",
                20,
                plan,
                project,
                {"main.py": "print('approved-bytes')\n"},
            )
            real_run = subprocess.run
            observed = {}

            def mutate_then_run(command, *args, **kwargs):
                snapshot = Path(kwargs["cwd"])
                (snapshot / "main.py").write_text(
                    "print('replacement-bytes')\n", encoding="utf-8"
                )
                completed = real_run(command, *args, **kwargs)
                observed["stdout"] = completed.stdout.decode("utf-8", errors="replace")
                return completed

            with patch.object(dev_agent.subprocess, "run", side_effect=mutate_then_run):
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
        self.assertIn("approved artifact changed", result)
        self.assertEqual(observed["stdout"].strip(), "approved-bytes")
        self.assertNotIn("replacement-bytes", observed["stdout"])
        self.assertFalse(project.exists())

    def test_dev_executor_imports_only_held_helper_bytes_during_snapshot_race(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            root = Path(tmp)
            project = root / "module_race"
            ready = root / "entry-ready"
            mutated = root / "helper-mutated"
            approved_marker = root / "approved-helper-ran"
            replacement_marker = root / "replacement-helper-ran"
            entry = (
                "from pathlib import Path\n"
                "import time\n"
                f"Path({str(ready)!r}).write_text('ready', encoding='utf-8')\n"
                f"flag = Path({str(mutated)!r})\n"
                "deadline = time.monotonic() + 5\n"
                "while not flag.exists() and time.monotonic() < deadline:\n"
                "    time.sleep(0.01)\n"
                "import helper\n"
                "print(helper.VALUE)\n"
            )
            approved_helper = (
                "from pathlib import Path\n"
                f"Path({str(approved_marker)!r}).write_text('approved', encoding='utf-8')\n"
                "VALUE = 'approved-helper-bytes'\n"
            )
            replacement_helper = (
                "from pathlib import Path\n"
                f"Path({str(replacement_marker)!r}).write_text('replacement', encoding='utf-8')\n"
                "VALUE = 'replacement-helper-bytes'\n"
            )
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "race",
                "python",
                "module_race",
                20,
                plan,
                project,
                {"main.py": entry, "helper.py": approved_helper},
            )
            real_run = subprocess.run
            observed = {}

            def mutate_during_import(command, *args, **kwargs):
                snapshot = Path(kwargs["cwd"])

                def replace_helper():
                    deadline = time.monotonic() + 5
                    while not ready.exists() and time.monotonic() < deadline:
                        time.sleep(0.01)
                    (snapshot / "helper.py").write_text(
                        replacement_helper, encoding="utf-8"
                    )
                    mutated.write_text("mutated", encoding="utf-8")

                worker = threading.Thread(target=replace_helper)
                worker.start()
                completed = real_run(command, *args, **kwargs)
                worker.join(timeout=5)
                observed["stdout"] = completed.stdout.decode("utf-8", errors="replace")
                return completed

            with patch.object(
                dev_agent.subprocess, "run", side_effect=mutate_during_import
            ):
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
            approved_ran = approved_marker.exists()
            replacement_ran = replacement_marker.exists()
        self.assertIn("approved artifact changed: helper.py", result)
        self.assertIn("approved-helper-bytes", observed["stdout"])
        self.assertTrue(approved_ran)
        self.assertFalse(replacement_ran)
        self.assertFalse(project.exists())

    def test_dev_executor_supports_packages_and_rejects_ambiguous_modules(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "package_demo"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            files = {
                "main.py": "from package.helper import VALUE\nprint(VALUE)\n",
                "package/__init__.py": "NAME = 'package'\n",
                "package/helper.py": "VALUE = 'package-approved'\n",
            }
            request = dev_agent._approval_request(
                "package",
                "python",
                "package_demo",
                20,
                plan,
                project,
                files,
            )
            result = dev_agent._execute_approved_artifacts(request, request["digest"])
            self.assertIn("created", result)
            self.assertIn("package-approved", result)

            ambiguous = dev_agent._approval_request(
                "ambiguous",
                "python",
                "ambiguous",
                20,
                plan,
                Path(tmp) / "ambiguous",
                {
                    "main.py": "print('entry')\n",
                    "thing.py": "VALUE = 1\n",
                    "thing/__init__.py": "VALUE = 2\n",
                },
            )
            rejected = dev_agent._execute_approved_artifacts(
                ambiguous, ambiguous["digest"]
            )
        self.assertIn("ambiguous approved Python module mapping", rejected)

    def test_dev_executor_never_executes_or_stages_dependency_bearing_request(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "dependency_race"
            plan = {
                "dependencies": ["requests"],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "race",
                "python",
                "dependency_race",
                20,
                plan,
                project,
                {"main.py": "import helper\n", "helper.py": "VALUE = 'approved'\n"},
            )

            with patch.object(dev_agent.subprocess, "run") as run:
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
        self.assertIn("preview-only", result)
        self.assertIn("requests", result)
        run.assert_not_called()
        self.assertFalse(project.exists())

    def test_dev_executor_rejects_reparse_root_and_atomic_target_collision(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "junction"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "junction",
                "python",
                "junction",
                20,
                plan,
                project,
                {"main.py": "print('safe')\n"},
            )
            with patch.object(dev_agent, "_is_reparse_point", return_value=True):
                rejected = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
            self.assertIn("link or junction", rejected)

            with patch.object(
                dev_agent,
                "_atomic_publish_noreplace",
                side_effect=FileExistsError("collision"),
            ):
                collided = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
        self.assertIn("target appeared", collided)
        self.assertFalse(project.exists())

    def test_darwin_atomic_publish_uses_rename_excl(self):
        renamex_np = Mock(return_value=0)
        libc = SimpleNamespace(renamex_np=renamex_np)
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot"
            target = Path(tmp) / "published"
            snapshot.mkdir()
            with (
                patch.object(dev_agent.sys, "platform", "darwin"),
                patch.object(dev_agent.ctypes, "CDLL", return_value=libc) as cdll,
            ):
                dev_agent._atomic_publish_noreplace(snapshot, target)

        cdll.assert_called_once_with(None, use_errno=True)
        renamex_np.assert_called_once_with(
            os.fsencode(snapshot), os.fsencode(target), 0x00000004
        )

    def test_darwin_atomic_publish_reports_target_collision(self):
        def collide(*_args):
            ctypes.set_errno(errno.EEXIST)
            return -1

        libc = SimpleNamespace(renamex_np=Mock(side_effect=collide))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot"
            target = Path(tmp) / "published"
            snapshot.mkdir()
            with (
                patch.object(dev_agent.sys, "platform", "darwin"),
                patch.object(dev_agent.ctypes, "CDLL", return_value=libc),
                self.assertRaises(FileExistsError) as raised,
            ):
                dev_agent._atomic_publish_noreplace(snapshot, target)

        self.assertEqual(raised.exception.errno, errno.EEXIST)
        self.assertEqual(raised.exception.filename, target)

    def test_darwin_atomic_publish_propagates_native_errno(self):
        def deny(*_args):
            ctypes.set_errno(errno.EACCES)
            return -1

        libc = SimpleNamespace(renamex_np=Mock(side_effect=deny))
        with tempfile.TemporaryDirectory() as tmp:
            snapshot = Path(tmp) / "snapshot"
            target = Path(tmp) / "published"
            snapshot.mkdir()
            with (
                patch.object(dev_agent.sys, "platform", "darwin"),
                patch.object(dev_agent.ctypes, "CDLL", return_value=libc),
                self.assertRaises(PermissionError) as raised,
            ):
                dev_agent._atomic_publish_noreplace(snapshot, target)

        self.assertEqual(raised.exception.errno, errno.EACCES)
        self.assertEqual(raised.exception.filename, target)

    def test_dev_executor_requires_new_directory_and_exact_entry_point(self):
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            existing = Path(tmp) / "existing"
            existing.mkdir()
            (existing / "unapproved.py").write_text(
                "raise RuntimeError()", encoding="utf-8"
            )
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "demo",
                "python",
                "existing",
                30,
                plan,
                existing,
                {"main.py": "print('safe')\n"},
            )
            result = dev_agent._execute_approved_artifacts(request, request["digest"])
            self.assertIn("already exists", result)
            self.assertTrue((existing / "unapproved.py").exists())

            fresh = Path(tmp) / "fresh"
            bad_plan = {
                "project_name": "fresh",
                "entry_point": "main.py",
                "run_command": "python helper.py",
                "dependencies": [],
                "files": [
                    {"path": "main.py", "description": "entry", "imports": []},
                    {"path": "helper.py", "description": "other", "imports": []},
                ],
            }
            with self.assertRaisesRegex(ValueError, "exact planned entry_point"):
                dev_agent._validate_plan(bad_plan, fresh)

    def test_permission_dialog_does_not_truncate_approved_payload(self):
        source = (ROOT / "ui.py").read_text(encoding="utf-8")
        self.assertNotIn("display truncated; digest covers all data", source)
        self.assertIn("payload.setPlainText", source)

    def test_nonzero_process_exit_is_reported_as_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "fails.py"
            script.write_text("raise SystemExit(7)\n", encoding="utf-8")
            result = code_helper_module._run_file(script, [], timeout=5)
        self.assertIn("failed with exit code 7", result)

    def test_string_arguments_are_materialized_before_execution(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "sample.py"
            script.write_text("print('ok')\n", encoding="utf-8")
            request = code_helper_module.materialize_code_helper_request(
                {
                    "action": "run",
                    "file_path": str(script),
                    "args": '--name "Ada Lovelace"',
                }
            )
        self.assertEqual(request["file_path"], str(script.resolve()))
        self.assertEqual(request["args"], ["--name", "Ada Lovelace"])
        self.assertEqual(request["timeout"], 30)

    def test_code_helper_disabled_modes_never_generate_write_or_execute(self):
        with (
            patch.object(
                code_helper_module,
                "_get_gemini",
                side_effect=AssertionError("model used"),
            ),
            patch.object(
                code_helper_module, "_run_file", side_effect=AssertionError("executed")
            ),
            patch.object(
                Path, "write_text", side_effect=AssertionError("file written")
            ),
        ):
            for action in code_helper_module.DISABLED_GENERATIVE_ACTIONS:
                with self.subTest(action=action):
                    result = code_helper_module.code_helper(
                        {
                            "action": action,
                            "description": "generate and execute malicious content",
                            "file_path": "C:/sensitive.py",
                            "output_path": "C:/escaped.py",
                        }
                    )
                    self.assertIn("disabled", result)

    def test_screen_debug_returns_model_text_without_writing_or_executing_it(self):
        with tempfile.TemporaryDirectory() as tmp:
            screenshot = Path(tmp) / "screen.png"
            screenshot.write_bytes(b"not-a-real-png")
            response = SimpleNamespace(
                text="```python\nPath('owned').write_text('x')\n```"
            )
            client = SimpleNamespace(
                models=SimpleNamespace(generate_content=Mock(return_value=response))
            )
            fake_genai = SimpleNamespace(Client=Mock(return_value=client))
            fake_types = SimpleNamespace(
                Part=SimpleNamespace(from_bytes=Mock(return_value="image"))
            )
            fake_genai.types = fake_types
            fake_google = SimpleNamespace(genai=fake_genai)
            with (
                patch.dict(
                    sys.modules,
                    {
                        "google": fake_google,
                        "google.genai": fake_genai,
                        "google.genai.types": fake_types,
                    },
                ),
                patch.object(
                    code_helper_module, "_take_screenshot", return_value=screenshot
                ),
                patch.object(
                    code_helper_module, "_get_api_key", return_value="test-key"
                ),
                patch.object(
                    code_helper_module,
                    "_run_file",
                    side_effect=AssertionError("executed"),
                ),
                patch.object(
                    Path, "write_text", side_effect=AssertionError("file written")
                ),
            ):
                result = code_helper_module.code_helper({"action": "screen_debug"})
        self.assertIn("Path('owned')", result)
        self.assertFalse((Path(tmp) / "owned").exists())

    def test_dev_agent_rejects_project_path_traversal(self):
        model = Mock()
        model.generate_content.return_value = Mock(text="print('unsafe')")
        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "_get_model", return_value=model),
        ):
            with self.assertRaisesRegex(ValueError, "Unsafe project file path"):
                dev_agent._write_file(
                    file_info={
                        "path": "../escaped.py",
                        "description": "",
                        "imports": [],
                    },
                    project_description="test",
                    all_files=[],
                    language="python",
                    project_dir=Path(tmp) / "project",
                    already_written={},
                )

    def test_dev_agent_contains_no_package_manager_or_venv_execution_path(self):
        source = (ROOT / "actions" / "dev_agent.py").read_text(encoding="utf-8")
        self.assertNotIn("_install_dependencies", source)
        self.assertNotIn("EnvBuilder", source)
        self.assertNotIn('"-m", "pip"', source)
        self.assertNotIn("_ensure_project_venv", source)

    def test_dev_agent_is_preview_only_without_trusted_host_callback(self):
        plan = {
            "project_name": "safe_project",
            "files": [{"path": "main.py", "description": "entry", "imports": []}],
            "dependencies": ["requests>=2"],
            "entry_point": "main.py",
            "run_command": "python main.py",
        }
        with (
            patch.object(dev_agent, "_plan_project", return_value=plan),
            patch.object(dev_agent, "_write_file", return_value="print('ok')"),
            patch.object(dev_agent, "_approval_callback", None),
            patch.object(dev_agent, "_execute_approved_artifacts") as execute,
        ):
            result = dev_agent.dev_agent(
                {"description": "test project", "confirmed": True}
            )
        self.assertIn("preview-only", result)
        self.assertIn("Preview ID:", result)
        execute.assert_not_called()

    def test_dependency_preview_cannot_reach_approval_or_subprocess(self):
        plan = {
            "project_name": "dependency_preview",
            "files": [{"path": "main.py", "description": "entry", "imports": []}],
            "dependencies": ["requests==2.32.5"],
            "entry_point": "main.py",
            "run_command": "python main.py",
        }
        with (
            patch.object(dev_agent, "_plan_project", return_value=plan),
            patch.object(dev_agent, "_write_file", return_value="import requests\n"),
            patch.object(dev_agent, "_approval_callback") as approval,
            patch.object(dev_agent, "_execute_approved_artifacts") as execute,
            patch.object(dev_agent.subprocess, "run") as run,
        ):
            result = dev_agent.dev_agent({"description": "dependency project"})
        self.assertIn("preview-only", result)
        self.assertIn("requests==2.32.5", result)
        self.assertIn("manual review", result)
        approval.assert_not_called()
        execute.assert_not_called()
        run.assert_not_called()

    def test_dev_agent_accepts_only_exact_python_and_blocks_inferred_dependencies(self):
        for language in ("Python", "javascript", "", None):
            with (
                self.subTest(language=language),
                patch.object(dev_agent, "_plan_project") as plan,
            ):
                result = dev_agent.dev_agent(
                    {"description": "demo", "language": language}
                )
                self.assertIn("language must be exactly 'python'", result)
                plan.assert_not_called()

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dev_agent, "PROJECTS_DIR", Path(tmp)),
        ):
            project = Path(tmp) / "inferred_dependency"
            plan = {
                "dependencies": [],
                "entry_point": "main.py",
                "run_command": "python main.py",
            }
            request = dev_agent._approval_request(
                "demo",
                "python",
                "inferred_dependency",
                20,
                plan,
                project,
                {"main.py": "import requests\nprint('unsafe')\n"},
            )
            with patch.object(dev_agent.subprocess, "run") as run:
                result = dev_agent._execute_approved_artifacts(
                    request, request["digest"]
                )
        self.assertIn("third-party import", result)
        run.assert_not_called()
        self.assertFalse(project.exists())

    def test_dev_agent_rejects_wrong_host_digest_and_unsafe_runners(self):
        plan = {
            "project_name": "safe_project",
            "files": [{"path": "main.py", "description": "entry", "imports": []}],
            "dependencies": [],
            "entry_point": "main.py",
            "run_command": "python main.py",
        }
        with (
            patch.object(dev_agent, "_plan_project", return_value=plan),
            patch.object(dev_agent, "_write_file", return_value="print('ok')"),
            patch.object(
                dev_agent, "_approval_callback", lambda request: "wrong-digest"
            ),
            patch.object(dev_agent, "_execute_approved_artifacts") as execute,
        ):
            result = dev_agent.dev_agent({"description": "test project"})
        self.assertIn("not approved", result)
        execute.assert_not_called()
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertIsNone(dev_agent._parse_safe_python_command("curl x", root))
            self.assertIsNone(dev_agent._parse_safe_python_command("npx vite", root))
            self.assertIsNone(dev_agent._parse_safe_python_command("python -c x", root))

    def test_dev_agent_accepts_normal_multi_specifiers_but_rejects_pip_options(self):
        self.assertEqual(
            dev_agent._validated_dependency("requests>=2.31,<3"),
            ("requests>=2.31,<3", "requests"),
        )
        self.assertIsNone(dev_agent._validated_dependency("--index-url"))

    def test_dev_agent_has_no_legacy_mutating_repair_executor(self):
        source = (ROOT / "actions" / "dev_agent.py").read_text(encoding="utf-8")
        for legacy_name in (
            "_build_project",
            "_fix_files",
            "_open_vscode",
            "_try_auto_install",
            "MAX_FIX_ATTEMPTS",
        ):
            self.assertNotIn(legacy_name, source)
            self.assertFalse(hasattr(dev_agent, legacy_name))
        self.assertTrue(callable(dev_agent._execute_approved_artifacts))

    def test_xrandr_brightness_adjustment_never_uses_a_shell(self):
        verbose = Mock(
            returncode=0, stdout="HDMI-1 connected primary\n\tBrightness: 0.8\n"
        )
        changed = Mock(returncode=0, stdout="")
        with patch.object(
            computer_settings.subprocess, "run", side_effect=[verbose, changed]
        ) as run:
            self.assertTrue(computer_settings._adjust_xrandr_brightness(0.1))
        self.assertEqual(
            run.call_args_list[1].args[0][:3], ["xrandr", "--output", "HDMI-1"]
        )
        self.assertNotIn("shell", run.call_args_list[1].kwargs)

    def test_window_title_is_escaped_before_powershell(self):
        with (
            patch.object(computer_control, "_get_os", return_value="windows"),
            patch.object(computer_control.subprocess, "run") as run,
            patch.object(computer_control.time, "sleep"),
        ):
            computer_control._focus_window("x'); Write-Host hacked; ('")
        script = run.call_args.args[0][-1]
        self.assertIn("x''); Write-Host hacked; (''", script)

    def test_desktop_task_never_generates_or_executes_code(self):
        self.assertFalse(hasattr(desktop, "_ask_gemini_for_desktop_action"))
        self.assertFalse(hasattr(desktop, "_execute_generated_code"))
        result = desktop.desktop_control(
            {
                "action": "task",
                "task": "run arbitrary generated Python",
            }
        )
        self.assertIn("disabled", result)

    def test_wallpaper_applescript_path_is_escaped(self):
        escaped = desktop._applescript_string('a"b\\c\n')
        self.assertEqual(escaped, 'a\\"b\\\\c')

    def test_wallpaper_url_is_always_rejected_without_network_access(self):
        with patch(
            "urllib.request.urlopen", side_effect=AssertionError("network used")
        ):
            result = desktop.set_wallpaper_from_url("https://example.com/image.jpg")
        self.assertIn("Remote wallpaper URLs are disabled", result)

    def test_wallpaper_rejects_unc_before_filesystem_probe(self):
        with patch.object(
            desktop.Path, "exists", side_effect=AssertionError("filesystem probed")
        ):
            result = desktop.set_wallpaper(r"\\server\share\wallpaper.jpg")
        self.assertIn("Network, UNC, device", result)


@unittest.skipUnless(importlib.util.find_spec("requests"), "requests not installed")
class LocalLlmClientTests(unittest.TestCase):
    def test_text_calls_use_openai_compatible_endpoint_when_configured(self):
        import core.llm_client as llm

        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "choices": [{"message": {"content": "hello"}}],
        }
        with (
            patch.object(
                llm, "get_llm_settings", return_value=("http://localhost:1234", "local")
            ),
            patch.object(llm, "get_llm_provider", return_value="openai"),
            patch.object(llm.requests, "post", return_value=response) as post,
        ):
            result = llm.call_llm_text("hi")

        self.assertEqual(result, "hello")
        self.assertEqual(
            post.call_args.args[0], "http://localhost:1234/v1/chat/completions"
        )
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["max_tokens"], 600)
        self.assertNotIn("keep_alive", payload)


@unittest.skipUnless(
    importlib.util.find_spec("youtube_transcript_api"),
    "youtube-transcript-api not installed",
)
class YouTubeCompatibilityTests(unittest.TestCase):
    def test_current_transcript_api_objects_are_supported(self):
        import actions.youtube_video as youtube

        class Entry:
            text = "hello"

        transcript = Mock()
        transcript.fetch.return_value = [Entry()]
        transcript_list = Mock()
        transcript_list.find_manually_created_transcript.return_value = transcript
        api = Mock()
        api.list.return_value = transcript_list

        with patch.object(youtube, "YouTubeTranscriptApi", return_value=api):
            result = youtube._get_transcript("abcdefghijk")
        self.assertEqual(result, "hello")

    def test_summarize_uses_supplied_url_without_opening_a_dialog(self):
        import actions.youtube_video as youtube

        url = "https://www.youtube.com/watch?v=abcdefghijk"
        with (
            patch.object(
                youtube, "_ask_for_url", side_effect=AssertionError("dialog opened")
            ),
            patch.object(youtube, "_get_transcript", return_value="transcript"),
            patch.object(youtube, "_summarize_with_gemini", return_value="summary"),
        ):
            result = youtube._handle_summarize({"url": url}, player=None, speak=None)
        self.assertEqual(result, "summary")


class WeatherTests(unittest.TestCase):
    def test_weather_returns_actual_conditions(self):
        response = Mock()
        response.raise_for_status.return_value = None
        response.json.return_value = {
            "current_condition": [
                {
                    "weatherDesc": [{"value": "Sunny"}],
                    "temp_C": "24",
                    "FeelsLikeC": "25",
                    "humidity": "40",
                    "windspeedKmph": "9",
                }
            ],
            "weather": [],
        }
        requests = Mock()
        requests.get.return_value = response

        sys.modules.pop("actions.weather_report", None)
        with patch.dict(sys.modules, {"requests": requests}):
            weather = importlib.import_module("actions.weather_report")
            result = weather.weather_action({"city": "Miami", "time": "now"})

        self.assertIn("Sunny", result)
        self.assertIn("24°C", result)
        requests.get.assert_called_once()

    def test_weather_rejects_unsupported_time_clearly(self):
        from actions import weather_report

        with self.assertRaisesRegex(ValueError, "Unsupported weather time"):
            weather_report._select_forecast({"weather": []}, "sometime eventually")

    def test_today_uses_hourly_representative_and_averages(self):
        from actions import weather_report

        today = date.today().isoformat()
        data = {
            "weather": [
                {
                    "date": today,
                    "mintempC": "18",
                    "maxtempC": "29",
                    "avgtempC": "24",
                    "hourly": [
                        {
                            "time": "900",
                            "tempC": "21",
                            "humidity": "80",
                            "windspeedKmph": "5",
                            "weatherDesc": [{"value": "Cloudy"}],
                        },
                        {
                            "time": "1200",
                            "tempC": "26",
                            "humidity": "60",
                            "windspeedKmph": "15",
                            "weatherDesc": [{"value": "Sunny"}],
                        },
                        {
                            "time": "1800",
                            "tempC": "25",
                            "humidity": "40",
                            "windspeedKmph": "10",
                            "weatherDesc": [{"value": "Clear"}],
                        },
                    ],
                }
            ]
        }
        selected, label = weather_report._select_forecast(data, "today")
        self.assertEqual(label, today)
        self.assertEqual(selected["weatherDesc"][0]["value"], "Sunny")
        self.assertEqual(selected["humidity"], "60")
        self.assertEqual(selected["windspeedKmph"], "10")
        self.assertEqual((selected["mintempC"], selected["maxtempC"]), ("18", "29"))


@unittest.skipUnless(
    importlib.util.find_spec("cryptography"), "cryptography not installed"
)
class DashboardSecurityTests(unittest.TestCase):
    def test_phone_connection_is_visible_in_local_log_and_ui(self):
        import main as runtime

        onyx = runtime.OnyxLive.__new__(runtime.OnyxLive)
        onyx.ui = Mock()
        with patch("builtins.print") as output:
            onyx._on_phone_connected()
        output.assert_called_once_with("[Dashboard] Remote device authenticated.")
        onyx.ui.write_log.assert_called_once_with(
            "SYS: Phone connected via Remote Dashboard."
        )
        onyx.ui.notify_phone_connected.assert_called_once_with()

    def test_dashboard_selects_physical_lan_over_link_local_and_vpn(self):
        import dashboard.server as dashboard

        fake_stats = {
            "Tailscale": SimpleNamespace(isup=True),
            "NordLynx": SimpleNamespace(isup=True),
            "Ethernet": SimpleNamespace(isup=True),
        }
        fake_addrs = {
            "Tailscale": [
                SimpleNamespace(family=socket.AF_INET, address="169.254.83.107")
            ],
            "NordLynx": [SimpleNamespace(family=socket.AF_INET, address="10.5.0.2")],
            "Ethernet": [
                SimpleNamespace(family=socket.AF_INET, address="192.168.1.236")
            ],
        }
        fake_psutil = SimpleNamespace(
            net_if_stats=lambda: fake_stats,
            net_if_addrs=lambda: fake_addrs,
        )
        with (
            patch.dict(sys.modules, {"psutil": fake_psutil}),
            patch.object(dashboard.socket, "getaddrinfo", return_value=[]),
        ):
            self.assertEqual(dashboard._local_ip(), "192.168.1.236")

    def test_dashboard_client_never_puts_access_bearers_in_urls(self):
        html = (ROOT / "dashboard" / "static" / "app.html").read_text(encoding="utf-8")
        server = (ROOT / "dashboard" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn("?token=", html)
        self.assertNotIn("?token=", server)
        self.assertNotIn("token: str =", server)
        self.assertIn("/api/ws-ticket", html)
        self.assertIn("_authFetch(`/uploads/", html)
        self.assertIn("URL.createObjectURL(await response.blob())", html)

    def test_dashboard_client_centrally_handles_http_and_websocket_expiry(self):
        html = (ROOT / "dashboard" / "static" / "app.html").read_text(encoding="utf-8")
        self.assertIn("if (response.status === 401) _expireSession();", html)
        self.assertGreaterEqual(html.count("event.code === 4001"), 2)
        self.assertIn("sessionStorage.removeItem(ONYX_SESSION_TOKEN_KEY)", html)
        self.assertIn("location.replace('/login')", html)
        self.assertIn("if (xhr.status === 401)", html)

    def test_network_setup_is_manual_and_never_executes_commands(self):
        import dashboard.server as dashboard

        with patch.object(subprocess, "run", side_effect=AssertionError("command run")):
            dashboard._ensure_network_access(8000)

    def test_each_install_gets_a_distinct_tls_private_key(self):
        from dashboard.server import _ensure_local_certificate

        with (
            tempfile.TemporaryDirectory() as first,
            tempfile.TemporaryDirectory() as second,
        ):
            key1, cert1 = _ensure_local_certificate(Path(first), ["127.0.0.1"])
            key2, cert2 = _ensure_local_certificate(Path(second), ["127.0.0.1"])
            self.assertTrue(cert1.exists())
            self.assertTrue(cert2.exists())
            self.assertNotEqual(key1.read_bytes(), key2.read_bytes())

    def test_tls_certificate_regenerates_when_requested_san_is_missing(self):
        from dashboard.server import _ensure_local_certificate

        with tempfile.TemporaryDirectory() as tmp:
            key, _ = _ensure_local_certificate(Path(tmp), ["127.0.0.1"])
            original = key.read_bytes()
            key, _ = _ensure_local_certificate(Path(tmp), ["127.0.0.1", "192.0.2.20"])
            self.assertNotEqual(original, key.read_bytes())

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi not installed")
    def test_dashboard_requires_authentication(self):
        from fastapi.testclient import TestClient
        import dashboard.server as dashboard

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dashboard, "BASE_DIR", Path(tmp)),
        ):
            server = dashboard.DashboardServer()
            client = TestClient(server.app)
            self.assertTrue(server.get_url().startswith("https://"))
            self.assertTrue(server.get_manual_url().startswith("https://"))
            self.assertTrue(server.get_manual_url().endswith(":8001"))
            self.assertEqual(client.get("/api/files").status_code, 401)

            pin = server.new_key()
            login = client.post("/login", json={"pin": pin})
            self.assertEqual(login.status_code, 200)
            token = login.json()["token"]
            files = client.get(
                "/api/files", headers={"Authorization": f"Bearer {token}"}
            )
            self.assertEqual(files.status_code, 200)

            server._uploads_dir = Path(tmp) / "uploads"
            server._uploads_dir.mkdir()
            (server._uploads_dir / "report.txt").write_text("private", encoding="utf-8")
            self.assertEqual(
                client.get(f"/uploads/report.txt?token={token}").status_code,
                401,
            )
            download = client.get(
                "/uploads/report.txt",
                headers={"Authorization": f"Bearer {token}"},
            )
            self.assertEqual(download.status_code, 200)
            self.assertEqual(download.content, b"private")
            self.assertEqual(download.headers["cache-control"], "no-store")
            self.assertEqual(download.headers["referrer-policy"], "no-referrer")

            server._tokens[token] = 0
            self.assertEqual(
                client.get(
                    "/api/files", headers={"Authorization": f"Bearer {token}"}
                ).status_code,
                401,
            )

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi not installed")
    def test_websocket_tickets_are_authenticated_single_use_scoped_and_short_lived(
        self,
    ):
        from fastapi.testclient import TestClient
        import dashboard.server as dashboard

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dashboard, "BASE_DIR", Path(tmp)),
        ):
            server = dashboard.DashboardServer()
            client = TestClient(server.app)
            self.assertEqual(
                client.post("/api/ws-ticket", json={"scope": "command"}).status_code,
                401,
            )
            pin = server.new_key()
            token = client.post("/login", json={"pin": pin}).json()["token"]
            headers = {"Authorization": f"Bearer {token}"}

            issued = client.post(
                "/api/ws-ticket", headers=headers, json={"scope": "command"}
            )
            self.assertEqual(issued.status_code, 200)
            self.assertEqual(issued.headers["cache-control"], "no-store")
            self.assertEqual(issued.headers["referrer-policy"], "no-referrer")
            ticket = issued.json()["ticket"]
            self.assertEqual(server._consume_ws_ticket(ticket, "command"), token)
            self.assertIsNone(server._consume_ws_ticket(ticket, "command"))

            scoped = server._issue_ws_ticket(token, "audio")
            self.assertIsNone(server._consume_ws_ticket(scoped, "command"))
            self.assertIsNone(server._consume_ws_ticket(scoped, "audio"))

            expired = server._issue_ws_ticket(token, "command")
            server._ws_tickets[expired]["expires_at"] = 0
            self.assertIsNone(server._consume_ws_ticket(expired, "command"))

            self.assertEqual(
                client.post(
                    "/api/ws-ticket", headers=headers, json={"scope": "admin"}
                ).status_code,
                400,
            )

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi not installed")
    def test_dashboard_locks_out_repeated_login_failures_and_expires_devices(self):
        from fastapi.testclient import TestClient
        import dashboard.server as dashboard

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dashboard, "BASE_DIR", Path(tmp)),
        ):
            server = dashboard.DashboardServer()
            client = TestClient(server.app)
            for _ in range(dashboard.LOGIN_MAX_FAILURES):
                self.assertEqual(
                    client.post("/login", json={"pin": "BADPIN"}).status_code, 401
                )
            self.assertEqual(
                client.post("/login", json={"pin": "BADPIN"}).status_code, 429
            )

            server._device_sessions["expired"] = {
                "session_key": "ABCDEF",
                "expires_at": 0,
            }
            self.assertEqual(
                client.post(
                    "/api/device-login", json={"device_token": "expired"}
                ).status_code,
                401,
            )

    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi not installed")
    def test_websocket_rejects_post_expiry_command_and_expired_broadcast(self):
        from fastapi.testclient import TestClient
        import dashboard.server as dashboard

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dashboard, "BASE_DIR", Path(tmp)),
        ):
            server = dashboard.DashboardServer()
            with TestClient(server.app) as client:
                pin = server.new_key()
                token = client.post("/login", json={"pin": pin}).json()["token"]
                server._history.clear()
                ticket = client.post(
                    "/api/ws-ticket",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"scope": "command"},
                ).json()["ticket"]
                with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
                    server._tokens[token] = 0
                    ws.send_json({"type": "command", "text": "must not run"})
                    closed = ws.receive()
                    while closed["type"] == "websocket.send":
                        closed = ws.receive()
                    self.assertEqual(closed["type"], "websocket.close")
                    self.assertEqual(closed["code"], 4001)
                    self.assertTrue(server._command_queue.empty())

                pin = server.new_key()
                token = client.post("/login", json={"pin": pin}).json()["token"]
                server._history.clear()
                ticket = client.post(
                    "/api/ws-ticket",
                    headers={"Authorization": f"Bearer {token}"},
                    json={"scope": "command"},
                ).json()["ticket"]
                with client.websocket_connect(f"/ws?ticket={ticket}") as ws:
                    server._tokens[token] = 0
                    client.portal.call(
                        server.broadcast, {"type": "sys", "text": "secret"}
                    )
                    closed = ws.receive()
                    while closed["type"] == "websocket.send":
                        self.assertNotIn("secret", str(closed))
                        closed = ws.receive()
                    self.assertEqual(closed["type"], "websocket.close")
                    self.assertEqual(closed["code"], 4001)
                    self.assertFalse(server._clients)


class ApprovedSourceIdentityTests(unittest.TestCase):
    def test_changed_source_is_refused_and_never_dispatched(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "approved.py"
            approved = b"print('approved bytes')\n"
            script.write_bytes(approved)
            request = materialize_source_request(
                {
                    "file_path": str(script),
                    "args": ["--exact"],
                    "timeout": 20,
                }
            )
            self.assertEqual(
                request["source_sha256"], hashlib.sha256(approved).hexdigest()
            )
            self.assertEqual(request["source_size"], len(approved))
            script.write_bytes(b"print('replacement must never run')\n")
            with patch("core.approved_execution.subprocess.run") as run:
                result = execute_materialized_source(request)
            self.assertIn("source changed after approval", result)
            run.assert_not_called()

    def test_exact_approved_bytes_execute_from_stdin_with_source_cwd(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "approved.py"
            (Path(tmp) / "relative.txt").write_text("relative-ok", encoding="utf-8")
            script.write_text(
                "import pathlib, sys\n"
                "print(pathlib.Path('relative.txt').read_text(), sys.argv[1])\n",
                encoding="utf-8",
            )
            request = materialize_source_request(
                {
                    "file_path": str(script),
                    "args": ["arg-ok"],
                    "timeout": 20,
                }
            )
            result = execute_materialized_source(request)
            self.assertIn("relative-ok arg-ok", result)

    def test_both_tool_run_paths_refuse_a_post_approval_replacement(self):
        with tempfile.TemporaryDirectory() as tmp:
            script = Path(tmp) / "approved.py"
            script.write_text("print('approved')\n", encoding="utf-8")
            code_request = code_helper_module.materialize_code_helper_request(
                {
                    "action": "run",
                    "file_path": str(script),
                    "timeout": 20,
                }
            )
            file_request = file_processor_module.materialize_file_processor_request(
                {
                    "action": "run",
                    "file_path": str(script),
                    "timeout": 20,
                }
            )
            script.write_text("print('replacement')\n", encoding="utf-8")
            with patch("core.approved_execution.subprocess.run") as run:
                self.assertIn(
                    "source changed", code_helper_module.code_helper(code_request)
                )
                self.assertIn(
                    "source changed", file_processor_module.file_processor(file_request)
                )
            run.assert_not_called()


class TrustProfileTests(unittest.TestCase):
    def tearDown(self):
        permission_broker.set_trust_profile("cautious")
        permission_broker.configure_owner_autonomy(False, [])
        permission_broker.set_permission_callback(None)

    def test_autonomous_allows_routine_but_not_external_or_irreversible(self):
        callback = Mock(return_value=None)
        permission_broker.set_permission_callback(callback)
        permission_broker.set_trust_profile("autonomous")
        permission_broker.configure_owner_autonomy(
            True, [str(Path.home()), str(Path(__file__).parents[2])]
        )
        for tool, args in (
            ("open_app", {"app_name": "Calculator"}),
            ("web_search", {"query": "local news"}),
            ("memory_search", {"query": "project"}),
            (
                "file_controller",
                {
                    "action": "read",
                    "path": str(Path.home() / "Documents"),
                    "name": "x.txt",
                },
            ),
        ):
            self.assertTrue(permission_broker.authorize_model_tool(tool, args)[0])
        callback.assert_not_called()
        for tool, args in (
            ("send_message", {"receiver": "Ada"}),
            (
                "file_controller",
                {"action": "delete", "path": str(Path.home()), "name": "x"},
            ),
            ("computer_settings", {"action": "shutdown"}),
            ("code_helper", {"action": "run"}),
        ):
            self.assertFalse(permission_broker.authorize_model_tool(tool, args)[0])
        self.assertGreaterEqual(callback.call_count, 3)

    def test_launch_flags_default_off_and_require_exact_values(self):
        import main as runtime

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "settings.json"
            path.write_text(
                '{"startup_briefing_enabled":1,"proactive_enabled":"true","trust_profile":"unknown"}',
                encoding="utf-8",
            )
            self.assertEqual(
                runtime._load_launch_flags(path), (False, False, "cautious", False, [])
            )
            path.write_text(
                '{"startup_briefing_enabled":true,"proactive_enabled":true,"trust_profile":"autonomous","owner_autonomy_enabled":true,"autonomous_workspace_roots":["C:/tmp",7]}',
                encoding="utf-8",
            )
            self.assertEqual(
                runtime._load_launch_flags(path),
                (True, True, "autonomous", True, ["C:/tmp"]),
            )

    def test_protected_paths_fail_closed(self):
        self.assertFalse(
            file_controller._is_safe_path(Path.home() / "AppData" / "Local" / "secret")
        )
        self.assertFalse(
            file_controller._is_safe_path(
                Path(__file__).parents[1] / "config" / "api_keys.json"
            )
        )
        self.assertFalse(file_controller._is_safe_path(Path(r"\\.\PhysicalDrive0")))
        self.assertFalse(
            file_controller._is_safe_path(
                Path.home() / "Documents" / "report.txt:secret"
            )
        )
        self.assertFalse(
            file_controller._is_safe_path(Path.home() / "Documents" / "CON.txt")
        )

    def test_autonomous_file_materialization_rejects_escapes_and_both_destinations(
        self,
    ):
        with (
            tempfile.TemporaryDirectory() as tmp,
            tempfile.TemporaryDirectory() as outside,
        ):
            root = Path(tmp)
            (root / "source.txt").write_text("x", encoding="utf-8")
            permission_broker.set_trust_profile("autonomous")
            permission_broker.configure_owner_autonomy(True, [tmp])
            self.assertTrue(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {"action": "write", "path": tmp, "name": "ok.txt"},
                )[0]
            )
            self.assertFalse(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {"action": "write", "path": tmp, "name": "../escape.txt"},
                )[0]
            )
            # Owner scope decision (2026-08-21): ordinary folders are no longer
            # fenced off from one another; the standing restriction is that
            # operating-system and installed-program files stay explicit.
            self.assertTrue(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {
                        "action": "copy",
                        "path": tmp,
                        "name": "source.txt",
                        "destination": outside,
                    },
                )[0]
            )
            system_root = (
                os.environ.get("SystemRoot", r"C:\Windows")
                if os.name == "nt"
                else "/usr"
            )
            self.assertFalse(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {
                        "action": "copy",
                        "path": tmp,
                        "name": "source.txt",
                        "destination": system_root,
                    },
                )[0]
            )
            self.assertFalse(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {"action": "write", "path": system_root, "name": "escape.txt"},
                )[0]
            )
            link = root / "link"
            try:
                link.symlink_to(Path(outside), target_is_directory=True)
            except OSError:
                return
            self.assertFalse(
                permission_broker.authorize_model_tool(
                    "file_controller",
                    {"action": "write", "path": str(link), "name": "escape.txt"},
                )[0]
            )

    def test_autonomous_audit_is_hash_chained_and_redacted(self):
        from core import tool_audit

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tool_audit, "AUDIT_PATH", Path(tmp) / "audit.sqlite3"),
        ):
            permission_broker.set_trust_profile("autonomous")
            permission_broker.configure_owner_autonomy(True, [tmp])
            secret = "typed-private-value"
            self.assertTrue(
                permission_broker.authorize_model_tool(
                    "browser_control", {"action": "type", "text": secret}
                )[0]
            )
            self.assertEqual(tool_audit.verify_audit()[0], 1)
            raw = tool_audit.AUDIT_PATH.read_bytes()
            self.assertNotIn(secret.encode(), raw)
            import sqlite3

            db = sqlite3.connect(tool_audit.AUDIT_PATH)
            schema, event_hash = db.execute(
                "SELECT arg_schema,event_hash FROM events"
            ).fetchone()
            parsed = json.loads(schema)
            self.assertEqual(parsed["known_fields"], ["action"])
            self.assertEqual(parsed["type_counts"]["unknown"], 1)
            self.assertEqual(len(event_hash), 64)
            with self.assertRaises(sqlite3.DatabaseError):
                db.execute("UPDATE events SET outcome='x'")
            db.close()


@unittest.skipUnless(os.name == "nt", "Windows native handle semantics")
class WindowsBoundFileMutationTests(unittest.TestCase):
    def setUp(self):
        self.module = importlib.import_module("actions.file_controller")
        self.base = ROOT / "uploads" / f"bound-test-{secrets.token_hex(6)}"
        self.base.mkdir(parents=True)

    def tearDown(self):
        self.module._SAFE_OPERATION_TEST_HOOK = None
        shutil.rmtree(self.base, ignore_errors=True)

    def test_handle_rename_refuses_collision(self):
        source = self.base / "source.txt"
        target = self.base / "target.txt"
        source.write_text("source", encoding="utf-8")
        target.write_text("target", encoding="utf-8")
        with self.module.SafeOperationGuard(self.base) as guard:
            with self.assertRaises(FileExistsError):
                guard.rename(source, target)
        self.assertEqual(target.read_text(encoding="utf-8"), "target")

    def test_bound_leaf_cannot_be_swapped_during_rename(self):
        source = self.base / "source.txt"
        target = self.base / "target.txt"
        attacker = self.base / "attacker.txt"
        source.write_text("approved", encoding="utf-8")
        swap_errors = []

        def attempt_swap(_source, _target):
            try:
                os.replace(source, attacker)
            except OSError as exc:
                swap_errors.append(exc)

        self.module._SAFE_OPERATION_TEST_HOOK = attempt_swap
        try:
            with self.module.SafeOperationGuard(self.base) as guard:
                guard.rename(source, target)
        except OSError:
            pass  # A racing path mutation may force a safe operation failure.
        self.assertTrue(swap_errors)
        self.assertFalse(attacker.exists())
        surviving = target if target.exists() else source
        self.assertEqual(surviving.read_text(encoding="utf-8"), "approved")

    def test_organize_uses_bound_rename(self):
        document = self.base / "report.pdf"
        document.write_bytes(b"pdf")
        with patch.object(self.module, "_get_desktop", return_value=self.base):
            result = self.module.organize_desktop()
        self.assertIn("1 files moved", result)
        moved = self.base / "Documents" / "report.pdf"
        self.assertTrue(
            moved.exists(),
            f"result={result!r} tree={[str(p.relative_to(self.base)) for p in self.base.rglob('*')]}",
        )
        self.assertEqual(moved.read_bytes(), b"pdf")

    def test_cross_volume_move_fails_truthfully(self):
        source = self.base / "source.txt"
        destination = self.base / "destination.txt"
        source.write_text("approved", encoding="utf-8")
        with patch.object(
            self.module.SafeOperationGuard,
            "rename",
            side_effect=OSError(17, "not same device"),
        ):
            result = self.module.move_file(str(source), destination=str(destination))
        self.assertIn("not same device", result)
        self.assertEqual(source.read_text(encoding="utf-8"), "approved")
        self.assertFalse(destination.exists())

    def test_bound_append_cannot_be_redirected_by_leaf_swap(self):
        target = self.base / "append.txt"
        attacker = self.base / "attacker.txt"
        target.write_bytes(b"approved")
        swap_errors = []

        def attempt_swap(_source, _target):
            try:
                os.replace(target, attacker)
            except OSError as exc:
                swap_errors.append(exc)

        self.module._SAFE_OPERATION_TEST_HOOK = attempt_swap
        try:
            with self.module.SafeOperationGuard(self.base) as guard:
                guard.write_bytes(target, b"+bound", append=True)
        except OSError:
            pass
        self.assertTrue(swap_errors)
        self.assertFalse(attacker.exists())
        self.assertIn(target.read_bytes(), (b"approved", b"approved+bound"))


class ToolAuditIntegrityTests(unittest.TestCase):
    def tearDown(self):
        permission_broker._audit_healthy = True

    def test_concurrent_append_and_chain_verification(self):
        from core import tool_audit

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tool_audit, "AUDIT_PATH", Path(tmp) / "audit.sqlite3"),
        ):
            errors = []

            def write(index):
                try:
                    tool_audit.append_tool_audit(
                        profile="autonomous",
                        tool="browser_control",
                        action="type",
                        decision="allow",
                        reason="test",
                        arguments={"text": f"secret-{index}"},
                    )
                except Exception as exc:
                    errors.append(exc)

            threads = [threading.Thread(target=write, args=(i,)) for i in range(8)]
            for thread in threads:
                thread.start()
            for thread in threads:
                thread.join()
            self.assertFalse(errors)
            self.assertEqual(tool_audit.verify_audit()[0], 8)

    def test_multi_event_corruption_is_detected(self):
        import sqlite3
        from core import tool_audit

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(tool_audit, "AUDIT_PATH", Path(tmp) / "audit.sqlite3"),
        ):
            for index in range(3):
                tool_audit.append_tool_audit(
                    profile="cautious",
                    tool="x",
                    action=str(index),
                    decision="deny",
                    reason="test",
                )
            db = sqlite3.connect(tool_audit.AUDIT_PATH)
            try:
                db.execute("DROP TRIGGER events_no_update")
                db.execute("UPDATE events SET outcome='corrupt' WHERE id=2")
                db.commit()
            finally:
                db.close()
            with self.assertRaises(RuntimeError):
                tool_audit.verify_audit()

    def test_audit_failure_denies_autonomous_execution(self):
        permission_broker.set_trust_profile("autonomous")
        permission_broker.configure_owner_autonomy(True, [str(ROOT / "uploads")])
        with patch.object(
            permission_broker, "append_tool_audit", side_effect=OSError("disk full")
        ):
            allowed, _reason = permission_broker.authorize_model_tool(
                "browser_control", {"action": "type", "text": "private"}
            )
        self.assertFalse(allowed)


class PosixDescriptorTraversalTests(unittest.TestCase):
    def test_descendants_are_component_opened_relative_to_bound_root(self):
        module = importlib.import_module("actions.file_controller")
        root = (ROOT / "uploads").resolve()
        parent = root / "level1" / "level2"
        parent.mkdir(parents=True, exist_ok=True)
        calls = []
        next_fd = iter((10, 11, 12))

        def fake_open(path, flags, *args, **kwargs):
            calls.append((path, kwargs.get("dir_fd"), flags))
            return next(next_fd)

        fake_stat = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_dev=1, st_ino=1)
        with (
            patch.object(module.os, "name", "posix"),
            patch.object(module.os, "O_NOFOLLOW", 0x100, create=True),
            patch.object(module, "_SAFE_ROOTS", [root]),
            patch.object(module, "_is_safe_path", return_value=True),
            patch.object(module.os, "open", side_effect=fake_open),
            patch.object(module.os, "fstat", return_value=fake_stat),
            patch.object(module.os, "close"),
        ):
            with module.SafeOperationGuard(parent):
                pass
        self.assertEqual(Path(calls[0][0]), root)
        self.assertIsNone(calls[0][1])
        self.assertEqual(
            [(str(path), fd) for path, fd, _ in calls[1:]],
            [("level1", 10), ("level2", 11)],
        )
        self.assertTrue(all(flags & 0x100 for _, _, flags in calls))

    def test_intermediate_component_open_failure_fails_closed(self):
        module = importlib.import_module("actions.file_controller")
        root = (ROOT / "uploads").resolve()
        parent = root / "blocked" / "child"
        parent.mkdir(parents=True, exist_ok=True)

        def fake_open(path, flags, *args, **kwargs):
            if kwargs.get("dir_fd") is not None:
                raise OSError("symlink swap")
            return 10

        fake_stat = SimpleNamespace(st_mode=stat.S_IFDIR | 0o700, st_dev=1, st_ino=1)
        with (
            patch.object(module.os, "name", "posix"),
            patch.object(module, "_SAFE_ROOTS", [root]),
            patch.object(module, "_is_safe_path", return_value=True),
            patch.object(module.os, "open", side_effect=fake_open),
            patch.object(module.os, "fstat", return_value=fake_stat),
            patch.object(module.os, "close"),
        ):
            with self.assertRaises(OSError):
                module.SafeOperationGuard(parent).__enter__()


class DashboardHeaderTests(unittest.TestCase):
    @unittest.skipUnless(importlib.util.find_spec("fastapi"), "fastapi not installed")
    def test_global_security_headers_and_sensitive_no_store(self):
        from fastapi.testclient import TestClient
        import dashboard.server as dashboard

        with (
            tempfile.TemporaryDirectory() as tmp,
            patch.object(dashboard, "BASE_DIR", Path(tmp)),
        ):
            server = dashboard.DashboardServer()
            client = TestClient(server.app, base_url="https://testserver")
            for path in ("/login", "/api/files"):
                response = client.get(path)
                self.assertIn(
                    # The mobile dashboard embeds the allowlisted humanoid
                    # visual from this same origin. External origins remain
                    # blocked while that required internal frame stays valid.
                    "frame-ancestors 'self'",
                    response.headers["content-security-policy"],
                )
                self.assertIn(
                    "connect-src 'self' ws: wss:",
                    response.headers["content-security-policy"],
                )
                self.assertEqual(response.headers["x-content-type-options"], "nosniff")
                self.assertIn(
                    "microphone=(self)", response.headers["permissions-policy"]
                )
                self.assertEqual(response.headers["referrer-policy"], "no-referrer")
                self.assertEqual(response.headers["cache-control"], "no-store")
                self.assertIn(
                    "max-age=31536000", response.headers["strict-transport-security"]
                )


class DesktopSweepBoundaryTests(unittest.TestCase):
    def test_organize_skips_link_or_reparse_entries(self):
        desktop = importlib.import_module("actions.desktop")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "report.pdf"
            candidate.write_text("owned", encoding="utf-8")
            guard = Mock()
            guard.__enter__ = Mock(return_value=guard)
            guard.__exit__ = Mock(return_value=False)
            with (
                patch.object(desktop, "_desktop_boundary", return_value=(root, guard)),
                patch.object(
                    desktop,
                    "_is_link_or_reparse",
                    side_effect=lambda path: path == candidate,
                ),
            ):
                result = desktop.organize_desktop()
            self.assertIn("0 files moved", result)
            self.assertEqual(candidate.read_text(encoding="utf-8"), "owned")

    def test_organize_moves_only_through_bound_guard(self):
        desktop = importlib.import_module("actions.desktop")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            candidate = root / "report.pdf"
            candidate.write_text("owned", encoding="utf-8")
            guard = Mock()
            guard.__enter__ = Mock(return_value=guard)
            guard.__exit__ = Mock(return_value=False)
            with (
                patch.object(desktop, "_desktop_boundary", return_value=(root, guard)),
                patch.object(desktop, "_bound_rename") as bound_rename,
            ):
                desktop.organize_desktop()
            bound_rename.assert_called_once_with(
                root, candidate, root / "Documents" / "report.pdf"
            )

    @unittest.skipUnless(os.name == "nt", "Windows junction semantics only")
    def test_windows_organize_refuses_real_junction_destination(self):
        desktop_module = importlib.import_module("actions.desktop")
        uploads = ROOT / "uploads"
        uploads.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=uploads) as tmp:
            base = Path(tmp)
            root = base / "Desktop"
            external = base / "external"
            root.mkdir()
            external.mkdir()
            candidate = root / "report.pdf"
            candidate.write_text("owned", encoding="utf-8")
            junction = root / "Documents"
            created = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(external)],
                capture_output=True,
                text=True,
                check=False,
            )
            if created.returncode:
                self.skipTest(
                    "native junction creation unavailable; fail-closed reparse "
                    "detection remains covered by test_organize_skips_link_or_reparse_entries"
                )
            try:
                self.assertTrue(desktop_module._is_link_or_reparse(junction))
                with patch.object(desktop_module, "_get_desktop", return_value=root):
                    result = desktop_module.organize_desktop()
                self.assertIn("0 files moved", result)
                self.assertIn("1 file(s) skipped", result)
                self.assertEqual(candidate.read_text(encoding="utf-8"), "owned")
                self.assertEqual(list(external.iterdir()), [])
            finally:
                junction.rmdir()

    @unittest.skipUnless(os.name == "nt", "Windows handle race semantics only")
    def test_windows_organize_blocks_source_swap_during_bound_rename(self):
        desktop_module = importlib.import_module("actions.desktop")
        uploads = ROOT / "uploads"
        uploads.mkdir(exist_ok=True)
        with tempfile.TemporaryDirectory(dir=uploads) as tmp:
            root = Path(tmp)
            candidate = root / "report.pdf"
            attacker = root / "attacker.pdf"
            candidate.write_text("owned", encoding="utf-8")
            swap_errors = []

            def attempt_swap(_source, _target):
                try:
                    os.replace(candidate, attacker)
                except OSError as error:
                    swap_errors.append(error)

            file_controller._SAFE_OPERATION_TEST_HOOK = attempt_swap
            try:
                with patch.object(desktop_module, "_get_desktop", return_value=root):
                    result = desktop_module.organize_desktop()
            finally:
                file_controller._SAFE_OPERATION_TEST_HOOK = None

            self.assertTrue(swap_errors, "the adversarial replacement must be refused")
            self.assertFalse(attacker.exists())
            moved = root / "Documents" / "report.pdf"
            self.assertEqual(moved.read_text(encoding="utf-8"), "owned")
            self.assertIn("1 files moved", result)


class CapabilityExpansionCompositionRegressionTests(unittest.TestCase):
    def test_model_contract_excludes_raw_clipboard_content(self):
        import main

        declaration = next(
            item
            for item in main.TOOL_DECLARATIONS
            if item["name"] == "capability_expansion"
        )
        properties = declaration["parameters"]["properties"]
        self.assertNotIn("text", properties)
        self.assertNotIn("content", properties)
        self.assertEqual(
            declaration["parameters"]["required"],
            ["capability", "operation"],
        )


if __name__ == "__main__":
    unittest.main()

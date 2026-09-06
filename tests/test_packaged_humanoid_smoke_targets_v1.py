"""Evaluate the real packaged HUD smoke predicate without importing main or Qt.

This is scoped source-contract coverage, not a packaged/offscreen rendering run.
Only selected expressions from _run_package_smoke_test are evaluated, against
synthetic objects with no host, provider, camera, audio or filesystem methods.
"""

from __future__ import annotations

import ast
import re
from dataclasses import dataclass, field
from pathlib import Path
from types import SimpleNamespace

import pytest


ROOT = Path(__file__).resolve().parents[1]
LOOKUPS = (
    "host",
    "quick",
    "hud_root",
    "humanoid",
    "webgl",
    "fallback",
    "predecessor_orb",
)
METHODS = {"rootObject", "findChild", "objectName", "isVisible", "property", "alpha"}
EXPRESSION_NODES = (
    ast.Expression,
    ast.BoolOp,
    ast.Or,
    ast.And,
    ast.UnaryOp,
    ast.Not,
    ast.Compare,
    ast.Is,
    ast.IsNot,
    ast.NotEq,
    ast.Eq,
    ast.Constant,
    ast.Name,
    ast.Load,
    ast.Attribute,
    ast.Call,
    ast.IfExp,
)


def _one(items):
    items = list(items)
    assert len(items) == 1, "expected exactly one scoped source binding"
    return items[0]


def _assignment(statements, name):
    return _one(
        node
        for node in statements
        if isinstance(node, ast.Assign)
        and len(node.targets) == 1
        and isinstance(node.targets[0], ast.Name)
        and node.targets[0].id == name
    )


def _qml_name(path, qml_type, identifier, *, indent=""):
    # Match an actual declaration and its own id/objectName, not a reference,
    # comment, another component or a global occurrence of the target string.
    pattern = (
        rf"(?m)^{indent}{qml_type} \{{\s*"
        rf"id: {identifier}\s*objectName: \"([^\"]+)\""
    )
    return _one(re.findall(pattern, path.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def contract():
    tree = ast.parse((ROOT / "main.py").read_text(encoding="utf-8"))
    smoke = _one(
        node
        for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_run_package_smoke_test"
    )
    transaction = _one(node for node in smoke.body if isinstance(node, ast.Try))
    assignments = tuple(_assignment(transaction.body, name) for name in LOOKUPS)
    guard = _one(
        node
        for node in transaction.body
        if isinstance(node, ast.If)
        and any(
            isinstance(part, ast.Name) and part.id == "predecessor_orb"
            for part in ast.walk(node.test)
        )
    )
    assert len(guard.body) == 1 and not guard.orelse
    refusal = guard.body[0]
    assert isinstance(refusal, ast.Raise) and refusal.cause is None
    assert isinstance(refusal.exc, ast.Call)
    assert (
        isinstance(refusal.exc.func, ast.Name) and refusal.exc.func.id == "SystemExit"
    )
    assert not refusal.exc.keywords
    assert [ast.literal_eval(arg) for arg in refusal.exc.args] == [
        "Packaged humanoid HUD did not load offscreen"
    ]

    host_tree = ast.parse(
        (ROOT / "core/onyx_hud_orb_v17.py").read_text(encoding="utf-8")
    )
    root_binding = _one(
        node
        for node in host_tree.body
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "ROOT_OBJECT"
    )
    install = _one(
        node
        for node in host_tree.body
        if isinstance(node, ast.FunctionDef) and node.name == "_install"
    )
    host_class = _one(
        node
        for node in install.body
        if isinstance(node, ast.ClassDef) and node.name == "_CinematicHudV17Host"
    )
    renderer = _one(
        node
        for node in host_class.body
        if isinstance(node, ast.FunctionDef) and node.name == "renderer_mode"
    )
    assert len(renderer.body) == 1 and isinstance(renderer.body[0], ast.Return)
    assert [ast.unparse(node) for node in renderer.decorator_list] == ["property"]
    names = {
        "hud_root": _qml_name(
            ROOT / "qml/OnyxLiveShellV16.qml", "OnyxLiveShellV12", "root"
        ),
        "humanoid": _qml_name(
            ROOT / "qml/components/OnyxHumanoidEntityV13.qml", "Item", "entity"
        ),
        "webgl": _qml_name(
            ROOT / "qml/components/OnyxHumanoidEntityV13.qml",
            "WebEngineView",
            "threeView",
            indent="    ",
        ),
        "fallback": _qml_name(
            ROOT / "qml/components/OnyxHumanoidEntityV13.qml",
            "Image",
            "continuityA",
            indent="    ",
        ),
        "predecessor_orb": _qml_name(
            ROOT / "qml/components/OnyxOrbEntityV9.qml", "Item", "entity"
        ),
    }
    assert names["hud_root"] == ast.literal_eval(root_binding.value)
    return assignments, guard, names, ast.literal_eval(renderer.body[0].value)


def _safe_eval(expression, environment):
    for node in ast.walk(expression):
        assert isinstance(node, EXPRESSION_NODES), (
            f"unexpected expression: {type(node).__name__}"
        )
        if isinstance(node, ast.Name):
            assert node.id in environment
        if isinstance(node, ast.Attribute):
            assert node.attr in METHODS
        if isinstance(node, ast.Call):
            assert not node.keywords
            assert (
                isinstance(node.func, ast.Name) and node.func.id in {"getattr", "bool"}
            ) or (isinstance(node.func, ast.Attribute) and node.func.attr in METHODS)
    return eval(
        compile(
            ast.Expression(expression), "<scoped-packaged-smoke-expression>", "eval"
        ),
        {"__builtins__": {}},
        environment,
    )


@dataclass
class _Item:
    name: str
    visible: bool = True
    properties: dict = field(default_factory=dict)
    children: dict = field(default_factory=dict)

    def objectName(self):
        return self.name

    def isVisible(self):
        return self.visible

    def property(self, name):
        return self.properties[name]

    def findChild(self, item_type, name):
        assert item_type is _Item
        return self.children.get(name)


@dataclass
class _Color:
    value: int = 0

    def alpha(self):
        return self.value


@dataclass
class _Quick:
    root: _Item | None

    def rootObject(self):
        return self.root


def _scene(contract, *, ready=True, slot=0):
    _assignments, _guard, names, mode = contract
    items = {name: _Item(value) for name, value in names.items()}
    items["humanoid"].properties = {"webglReady": ready, "continuitySlot": slot}
    items["webgl"].properties = {"backgroundColor": _Color()}
    items["fallback"].visible = not ready and slot == 0
    items["predecessor_orb"].visible = False
    root = items["hud_root"]
    root.children = {
        item.name: item for key, item in items.items() if key != "hud_root"
    }
    window = SimpleNamespace(
        _hud_v5_live=True,
        _v5_host=SimpleNamespace(_quick=_Quick(root), renderer_mode=mode),
    )
    return window, items


def _rejects(contract, window):
    assignments, guard, _names, _mode = contract
    environment = {
        "window": window,
        "getattr": getattr,
        "bool": bool,
        "QQuickItem": _Item,
    }
    for assignment in assignments:
        environment[assignment.targets[0].id] = _safe_eval(
            assignment.value, environment
        )
    result = _safe_eval(guard.test, environment)
    assert type(result) is bool
    return result


def test_smoke_findchild_targets_match_real_qml_and_host(contract):
    assignments, guard, names, mode = contract
    for name in ("humanoid", "webgl", "fallback", "predecessor_orb"):
        assignment = _one(node for node in assignments if node.targets[0].id == name)
        lookup = _one(
            node
            for node in ast.walk(assignment.value)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Attribute)
            and node.func.attr == "findChild"
        )
        assert ast.unparse(lookup.func.value) == "hud_root"
        assert len(lookup.args) == 2 and not lookup.keywords
        assert ast.unparse(lookup.args[0]) == "QQuickItem"
        assert ast.literal_eval(lookup.args[1]) == names[name]
    comparisons = [
        node for node in ast.walk(guard.test) if isinstance(node, ast.Compare)
    ]
    for expression, value in (
        ("hud_root.objectName()", names["hud_root"]),
        ("getattr(host, 'renderer_mode', '')", mode),
    ):
        comparison = _one(
            node for node in comparisons if ast.unparse(node.left) == expression
        )
        assert len(comparison.ops) == 1 and isinstance(comparison.ops[0], ast.NotEq)
        assert [ast.literal_eval(node) for node in comparison.comparators] == [value]


@pytest.mark.parametrize("ready,slot", [(True, 0), (True, 1), (False, 0), (False, 1)])
def test_smoke_condition_accepts_valid_transparent_and_continuity_states(
    contract, ready, slot
):
    window, _items = _scene(contract, ready=ready, slot=slot)
    assert _rejects(contract, window) is False


@pytest.mark.parametrize(
    "missing", ["humanoid", "webgl", "fallback", "predecessor_orb"]
)
def test_smoke_condition_rejects_missing_required_child(contract, missing):
    window, items = _scene(contract)
    del items["hud_root"].children[items[missing].name]
    assert _rejects(contract, window) is True


@pytest.mark.parametrize("alpha", [1, 128, 255])
def test_smoke_condition_rejects_nontransparent_webgl(contract, alpha):
    window, items = _scene(contract)
    items["webgl"].properties["backgroundColor"] = _Color(alpha)
    assert _rejects(contract, window) is True


def test_smoke_condition_rejects_visible_legacy_orb(contract):
    window, items = _scene(contract)
    items["predecessor_orb"].visible = True
    assert _rejects(contract, window) is True


@pytest.mark.parametrize("ready,slot", [(True, 0), (True, 1), (False, 0), (False, 1)])
def test_smoke_condition_rejects_wrong_continuity_visibility(contract, ready, slot):
    window, items = _scene(contract, ready=ready, slot=slot)
    items["fallback"].visible = not items["fallback"].visible
    assert _rejects(contract, window) is True


@pytest.mark.parametrize(
    "changed", ["host", "quick", "root", "root_name", "mode", "live", "visibility"]
)
def test_smoke_condition_rejects_invalid_host_or_humanoid(contract, changed):
    window, items = _scene(contract)
    if changed == "host":
        window._v5_host = None
    elif changed == "quick":
        window._v5_host._quick = None
    elif changed == "root":
        window._v5_host._quick.root = None
    elif changed == "root_name":
        items["hud_root"].name = "historical-shell"
    elif changed == "mode":
        window._v5_host.renderer_mode = "historical-renderer"
    elif changed == "live":
        window._hud_v5_live = False
    else:
        items["humanoid"].visible = False
    assert _rejects(contract, window) is True

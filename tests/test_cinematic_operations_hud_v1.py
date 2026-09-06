from __future__ import annotations

import os
import re
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QSG_RHI_BACKEND", "software")

import pytest
from PySide6.QtCore import QObject, QPointF, Qt, QUrl
from PySide6.QtGui import QAccessible, QFontDatabase
from PySide6.QtQml import QQmlComponent, QQmlEngine
from PySide6.QtQuick import QQuickItem, QQuickView
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

from core.cinematic_operations_projection_v1 import CinematicOperationsProjectionV1


PROJECT = Path(__file__).resolve().parents[1]
QML_ROOT = PROJECT / "qml"
HUD = QML_ROOT / "operations" / "CinematicOperationsHudV1.qml"
HUD_FILES = (
    HUD,
    QML_ROOT / "operations/pages/GoalsHudPageV1.qml",
    QML_ROOT / "operations/pages/WorkflowHudPageV1.qml",
    QML_ROOT / "operations/pages/DevicesHudPageV1.qml",
    QML_ROOT / "operations/pages/SiteWorkspaceHudPageV1.qml",
    QML_ROOT / "operations/pages/AgentsHudPageV1.qml",
    QML_ROOT / "operations/pages/AnalyticsHudPageV1.qml",
    QML_ROOT / "components/HudSectionTitleV1.qml",
    QML_ROOT / "components/HudMetricTileV1.qml",
    QML_ROOT / "components/HudDataRowV1.qml",
    QML_ROOT / "components/HudTypographyV1.qml",
)


def populated_snapshot() -> dict[str, object]:
    return {
        "status_label": "OPERATIONS READY",
        "goals": [
            {
                "goal_id": "goal.alpha",
                "title": "Release Onyx",
                "detail": "Review evidence",
                "status": "active",
                "priority": "high",
                "due_label": "TODAY",
                "progress": 0.6,
            }
        ],
        "workflow_nodes": [
            {
                "node_id": "node.start",
                "workflow_id": "workflow.alpha",
                "label": "Start",
                "kind": "trigger",
                "status": "complete",
            },
            {
                "node_id": "node.plan",
                "workflow_id": "workflow.alpha",
                "label": "Plan",
                "kind": "plan",
                "status": "active",
            },
        ],
        "workflow_edges": [
            {
                "edge_id": "edge.alpha",
                "workflow_id": "workflow.alpha",
                "source": "node.start",
                "target": "node.plan",
                "route": "next",
            }
        ],
        "devices": [
            {
                "device_id": "device.alpha",
                "name": "Workstation",
                "platform": "Windows",
                "status": "online",
                "trust": "bound",
                "last_seen": "NOW",
            }
        ],
        "sites": [
            {
                "site_id": "site.alpha",
                "name": "Cyryx Labs",
                "branch": "main",
                "status": "active",
                "preview_state": "ready",
                "updated_label": "NOW",
            }
        ],
        "site_files": [
            {
                "file_id": "file.index",
                "site_id": "site.alpha",
                "name": "index.html",
                "kind": "file",
                "state": "modified",
                "depth": 1,
            }
        ],
        "agents": [
            {
                "agent_id": "agent.alpha",
                "name": "Release operator",
                "role": "Quality",
                "status": "running",
                "task": "Reviewing evidence",
                "load_label": "1 ACTIVE",
            }
        ],
        "inbox": [
            {
                "inbox_id": "inbox.alpha",
                "title": "Review package",
                "source": "LEDGER",
                "status": "pending",
                "age_label": "NOW",
            }
        ],
        "events": [
            {
                "event_id": "event.alpha",
                "title": "Evidence received",
                "detail": "Review pending",
                "category": "system",
                "status": "review",
                "time_label": "09:42",
            }
        ],
    }


def maximum_snapshot() -> dict[str, object]:
    node_kinds = ("trigger", "condition", "transform", "plan", "output")
    categories = ("agent", "device", "goal", "site", "system", "workflow")
    return {
        "status_label": "MAXIMUM PROJECTION",
        "goals": [
            {
                "goal_id": f"goal.{index}",
                "title": f"Bounded operational goal {index:02d}",
                "detail": "Projected priority, progress and attention metadata.",
                "status": "attention" if index % 4 == 0 else "active",
                "priority": "high" if index % 3 == 0 else "normal",
                "due_label": "TODAY" if index % 2 == 0 else "THIS WEEK",
                "progress": index / 24,
            }
            for index in range(24)
        ],
        "workflow_nodes": [
            {
                "node_id": f"node.{index}",
                "workflow_id": "workflow.maximum",
                "label": f"Governed node {index:02d}",
                "kind": node_kinds[index % len(node_kinds)],
                "status": "active" if index == 1 else "complete",
            }
            for index in range(32)
        ],
        "workflow_edges": [
            {
                "edge_id": f"edge.{index}",
                "workflow_id": "workflow.maximum",
                "source": f"node.{index % 31}",
                "target": f"node.{(index % 31) + 1}",
                "route": "next",
            }
            for index in range(64)
        ],
        "devices": [
            {
                "device_id": f"device.{index}",
                "name": f"Bound device {index:02d}",
                "platform": "Windows" if index % 2 == 0 else "Linux",
                "status": "online" if index % 3 else "offline",
                "trust": "bound",
                "last_seen": "NOW" if index % 3 else "12 MIN AGO",
            }
            for index in range(24)
        ],
        "sites": [
            {
                "site_id": f"site.{index}",
                "name": f"Governed site workspace {index:02d}",
                "branch": f"feature/operations-{index:02d}",
                "status": "active" if index % 2 == 0 else "draft",
                "preview_state": "ready" if index % 2 == 0 else "pending",
                "updated_label": f"{index + 1} MIN AGO",
            }
            for index in range(16)
        ],
        "site_files": [
            {
                "file_id": f"file.{index}",
                "site_id": f"site.{index % 16}",
                "name": f"surface-{index:02d}.qml",
                "kind": "file",
                "state": "modified" if index % 3 == 0 else "clean",
                "depth": index % 4,
            }
            for index in range(96)
        ],
        "agents": [
            {
                "agent_id": f"agent.{index}",
                "name": f"Command unit {index:02d}",
                "role": "Quality and operations",
                "status": "running" if index % 3 == 0 else "ready",
                "task": "Reviewing bounded mission evidence",
                "load_label": f"{index % 4} ACTIVE",
            }
            for index in range(32)
        ],
        "inbox": [
            {
                "inbox_id": f"inbox.{index}",
                "title": f"Governed work proposal {index:02d}",
                "source": "MISSION LEDGER",
                "status": "pending",
                "age_label": f"{index + 1} MIN",
            }
            for index in range(32)
        ],
        "events": [
            {
                "event_id": f"event.{index}",
                "title": f"Operational event {index:03d}",
                "detail": "Event-derived metadata without background polling.",
                "category": categories[index % len(categories)],
                "status": "complete" if index % 2 == 0 else "review",
                "time_label": f"{index // 60:02d}:{index % 60:02d}",
            }
            for index in range(100)
        ],
    }


@pytest.fixture(scope="module")
def app() -> QApplication:
    return QApplication.instance() or QApplication([])


PAGES = {
    "goals": "goalsHudPageV1",
    "workflow": "workflowHudPageV1",
    "devices": "devicesHudPageV1",
    "sites": "siteWorkspaceHudPageV1",
    "agents": "agentsHudPageV1",
    "analytics": "analyticsHudPageV1",
}


def visual_items(parent: QQuickItem) -> list[QQuickItem]:
    result: list[QQuickItem] = []
    for child in parent.childItems():
        result.append(child)
        result.extend(visual_items(child))
    return result


def visual_item(parent: QQuickItem, object_name: str) -> QQuickItem:
    return next(
        item for item in visual_items(parent) if item.objectName() == object_name
    )


def open_hud(
    app: QApplication,
    *,
    width: int,
    height: int,
    snapshot: dict[str, object] | None = None,
) -> tuple[QQuickView, QQuickItem, CinematicOperationsProjectionV1, list[str]]:
    projection = CinematicOperationsProjectionV1(enabled=True, reduced_motion=True)
    if snapshot is not None:
        projection.set_snapshot(snapshot)
    view = QQuickView()
    warnings: list[str] = []
    view.engine().warnings.connect(
        lambda messages: warnings.extend(message.toString() for message in messages)
    )
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.resize(width, height)
    view.setInitialProperties({"projection": projection})
    view.setSource(QUrl.fromLocalFile(str(HUD)))
    errors = "\n".join(error.toString() for error in view.errors())
    assert view.status() == QQuickView.Status.Ready, errors
    view.show()
    app.processEvents()
    root = view.rootObject()
    assert isinstance(root, QQuickItem)
    return view, root, projection, warnings


def assert_frame(view: QQuickView, width: int, height: int) -> None:
    image = view.grabWindow()
    if image.isNull():
        pytest.skip("the active Qt offscreen backend does not support frame capture")
    assert (image.width(), image.height()) == (width, height)
    sample = {
        image.pixelColor(x, y).rgba()
        for x in range(0, width, max(1, width // 20))
        for y in range(0, height, max(1, height // 20))
    }
    assert len(sample) >= 4


def assert_item_inside(item: QQuickItem, parent: QQuickItem) -> None:
    position = item.mapToItem(parent, QPointF(0, 0))
    tolerance = 1.0
    assert position.x() >= -tolerance
    assert position.y() >= -tolerance
    assert position.x() + item.width() <= parent.width() + tolerance
    assert position.y() + item.height() <= parent.height() + tolerance


def assert_page_has_no_horizontal_clipping(page: QQuickItem) -> None:
    for item in [page, *visual_items(page)]:
        if not item.isVisible() or item.width() <= 0 or item.height() <= 0:
            continue
        ancestor = item.parentItem()
        clipper: QQuickItem | None = None
        while ancestor is not None and ancestor is not page:
            if ancestor.clip():
                clipper = ancestor
                break
            ancestor = ancestor.parentItem()
        if clipper is None:
            assert_item_inside(item, page)
            continue
        position = item.mapToItem(clipper, QPointF(0, 0))
        assert position.x() >= -1.0
        assert position.x() + item.width() <= clipper.width() + 1.0


def test_hud_is_additive_default_off_and_not_live_selected(
    app: QApplication,
) -> None:
    projection = CinematicOperationsProjectionV1()
    engine = QQmlEngine()
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(HUD)))
    errors = "\n".join(error.toString() for error in component.errors())
    assert component.status() == QQmlComponent.Status.Ready, errors
    root = component.createWithInitialProperties({"projection": projection})
    errors = "\n".join(error.toString() for error in component.errors())
    assert root is not None, errors
    assert root.objectName() == "cinematicOperationsHudV1"
    assert root.property("visible") is False

    for path in (
        PROJECT / "main.py",
        PROJECT / "ui.py",
        PROJECT / "qml/OnyxLiveShellV11.qml",
    ):
        source = path.read_text(encoding="utf-8")
        assert "CinematicOperationsHudV1" not in source
        assert "CinematicOperationsProjectionV1" not in source

    root.deleteLater()
    del component
    del engine


def test_qml_contract_is_local_static_bounded_and_cyryx_branded() -> None:
    assert all(path.is_file() for path in HUD_FILES)
    combined = "\n".join(path.read_text(encoding="utf-8") for path in HUD_FILES)
    lowered = combined.lower()

    for forbidden in (
        "timer {",
        "canvas {",
        "particlesystem",
        "shaderEffect".lower(),
        "xmlhttprequest",
        "websocket",
        "workerScript".lower(),
        "qt.openurlexternally",
        "http://",
        "https://",
    ):
        assert forbidden not in lowered
    assert "Loader {" in combined
    assert "safeNodeCatalog" in combined
    assert "requestProposal" in combined
    assert "Accessible.role" in combined
    assert "activeFocusOnTab" in combined
    assert "reducedMotion" in combined
    assert "OnyxOrb" not in combined

    approved = {
        "#050607",
        "#0a0d0f",
        "#11161a",
        "#1b2227",
        "#8c949e",
        "#c7c9cc",
        "#0f6b68",
        "#19c7c0",
    }
    opaque_colors = {
        value.lower() for value in re.findall(r"#[0-9a-fA-F]{6}", combined)
    }
    assert opaque_colors <= approved

    python_source = (PROJECT / "core/cinematic_operations_projection_v1.py").read_text(
        encoding="utf-8"
    )
    for forbidden_import in (
        "import pathlib",
        "import requests",
        "import socket",
        "import subprocess",
        "import urllib",
    ):
        assert forbidden_import not in python_source


def test_each_lazy_page_loads_through_public_qml_contract(app: QApplication) -> None:
    projection = CinematicOperationsProjectionV1(enabled=True, reduced_motion=True)
    projection.set_snapshot(populated_snapshot())
    engine = QQmlEngine()
    warnings: list[str] = []
    engine.warnings.connect(
        lambda messages: warnings.extend(message.toString() for message in messages)
    )
    component = QQmlComponent(engine, QUrl.fromLocalFile(str(HUD)))
    errors = "\n".join(error.toString() for error in component.errors())
    assert component.status() == QQmlComponent.Status.Ready, errors
    root = component.createWithInitialProperties({"projection": projection})
    errors = "\n".join(error.toString() for error in component.errors())
    assert root is not None, errors

    loader = root.findChild(QObject, "operationsPageLoaderV1")
    assert loader is not None
    for page, object_name in PAGES.items():
        assert projection.requestNavigation(page)
        app.processEvents()
        loaded_page = loader.property("item")
        assert loaded_page is not None
        assert loaded_page.objectName() == object_name
    assert warnings == []

    root.deleteLater()
    del component
    del engine
    app.processEvents()


@pytest.mark.parametrize(
    ("width", "height", "compact"),
    ((1100, 720, False), (800, 600, True)),
)
def test_viewport_responsiveness_maximum_data_and_all_page_frames(
    app: QApplication,
    width: int,
    height: int,
    compact: bool,
) -> None:
    view, root, projection, warnings = open_hud(
        app, width=width, height=height, snapshot=maximum_snapshot()
    )
    assert (root.width(), root.height()) == (width, height)
    assert root.property("compact") is compact

    rail = visual_item(root, "operationsDesktopRailV1")
    compact_navigation = visual_item(root, "operationsCompactNavigationV1")
    assert rail.isVisible() is (not compact)
    assert compact_navigation.isVisible() is compact
    active_navigation = compact_navigation if compact else rail
    assert_item_inside(active_navigation, root)

    loader = visual_item(root, "operationsPageLoaderV1")
    assert_item_inside(loader, root)
    for page, object_name in PAGES.items():
        assert projection.requestNavigation(page)
        app.processEvents()
        loaded_page = loader.property("item")
        assert isinstance(loaded_page, QQuickItem)
        assert loaded_page.objectName() == object_name
        assert loaded_page.width() == pytest.approx(loader.width())
        assert loaded_page.height() == pytest.approx(loader.height())
        assert_page_has_no_horizontal_clipping(loaded_page)
        assert_frame(view, width, height)

    assert warnings == []
    view.close()
    app.processEvents()


def test_typography_policy_resolves_available_system_families(
    app: QApplication,
) -> None:
    font_assets = [
        path
        for suffix in ("*.ttf", "*.otf", "*.woff", "*.woff2", "*.ttc")
        for path in QML_ROOT.rglob(suffix)
    ]
    source = (QML_ROOT / "components/HudTypographyV1.qml").read_text(encoding="utf-8")
    assert font_assets == []
    assert "FontLoader" not in source
    assert "Qt.fontFamilies()" in source

    engine = QQmlEngine()
    component = QQmlComponent(
        engine,
        QUrl.fromLocalFile(str(QML_ROOT / "components/HudTypographyV1.qml")),
    )
    errors = "\n".join(error.toString() for error in component.errors())
    assert component.status() == QQmlComponent.Status.Ready, errors
    policy = component.create()
    assert policy is not None

    available = {family.casefold() for family in QFontDatabase.families()}
    if not available:
        pytest.skip("the active Qt offscreen backend exposes no font database")
    for candidates_property, resolved_property, generic in (
        ("displayFamilies", "displayFamily", "sans-serif"),
        ("bodyFamilies", "bodyFamily", "sans-serif"),
        ("monoFamilies", "monoFamily", "monospace"),
    ):
        candidates = list(policy.property(candidates_property))
        resolved = str(policy.property(resolved_property))
        installed = next(
            (
                candidate
                for candidate in candidates
                if candidate.casefold() in available
            ),
            generic,
        )
        assert resolved.casefold() == installed.casefold()

    policy.deleteLater()
    del component
    del engine
    app.processEvents()


@pytest.mark.parametrize(
    ("width", "height", "prefix"),
    (
        (1100, 720, "operationsNav_"),
        (800, 600, "operationsCompactNav_"),
    ),
)
def test_keyboard_focus_order_and_accessible_actions_in_both_viewports(
    app: QApplication,
    width: int,
    height: int,
    prefix: str,
) -> None:
    view, root, _projection, warnings = open_hud(
        app, width=width, height=height, snapshot=maximum_snapshot()
    )
    first = visual_item(root, f"{prefix}goals")
    second = visual_item(root, f"{prefix}workflow")
    first.forceActiveFocus(Qt.FocusReason.TabFocusReason)
    app.processEvents()
    assert view.activeFocusItem() is first
    assert first.nextItemInFocusChain(True) is second
    assert second.nextItemInFocusChain(False) is first

    chain: list[QQuickItem] = [first]
    current = first
    for _ in range(256):
        current = current.nextItemInFocusChain(True)
        if current is first:
            break
        if current.isVisible() and current.isEnabled():
            chain.append(current)
    else:
        pytest.fail("focus chain did not return to its origin")

    expected_navigation = [f"{prefix}{page}" for page in PAGES]
    chain_names = [item.objectName() for item in chain]
    assert chain_names[:6] == expected_navigation
    assert "hudDataRowV1" in chain_names
    for item in chain:
        interface = QAccessible.queryAccessibleInterface(item)
        assert interface is not None
        assert interface.role() == QAccessible.Role.Button
        assert interface.text(QAccessible.Text.Name).strip()

    QTest.keyClick(view, Qt.Key.Key_Tab)
    app.processEvents()
    assert view.activeFocusItem() is second
    QTest.keyClick(view, Qt.Key.Key_Backtab)
    app.processEvents()
    assert view.activeFocusItem() is first
    assert warnings == []
    view.close()
    app.processEvents()

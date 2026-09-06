from __future__ import annotations

import json
import importlib
import math
import os
import platform
import random
import subprocess
import sys
import threading
import time
from pathlib import Path

import psutil

if platform.system() == "Windows":
    _WIN_HIDE: dict = {"creationflags": subprocess.CREATE_NO_WINDOW}
else:
    _WIN_HIDE: dict = {}

from PySide6.QtCore import (
    QEvent,
    QObject,
    QPointF,
    QRectF,
    Qt,
    QUrl,
    QTimer,
)
from PySide6.QtGui import (
    QAction,
    QBrush,
    QColor,
    QCursor,
    QDragEnterEvent,
    QDropEvent,
    QFont,
    QKeySequence,
    QPainter,
    QIcon,
    QPainterPath,
    QPen,
    QPixmap,
    QPolygonF,
    QRadialGradient,
    QShortcut,
)
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDialogButtonBox,
    QComboBox,
    QFileDialog,
    QFrame,
    QGridLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QMessageBox,
    QPushButton,
    QSizePolicy,
    QSplitter,
    QStackedLayout,
    QStackedWidget,
    QTextEdit,
    QSystemTrayIcon,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineQuick import QtWebEngineQuick
from core.qt_compat import pyqtProperty, pyqtSignal, pyqtSlot

from core.orb_motion_v1 import OrbMotionPolicyV1
from core.camera_gesture_attention_v1 import CameraGestureAttentionTrackerV1
from core.paths import config_dir, is_frozen, memory_dir, resource_root
from core.live_voice_preference_v1 import LiveVoicePreferenceV1, VOICES
from core.orb_state import OrbStateBridge

# The Three.js surface is embedded by Qt WebEngine. Initialization must happen
# after imports but before any QApplication is constructed.
QtWebEngineQuick.initialize()

WINDOWS_APP_USER_MODEL_ID = "labs.cyryx.onyx"


def _close_to_background_enabled() -> bool:
    """Return the packaged resident-window policy without changing dev cleanup."""

    override = os.environ.get("ONYX_EXIT_ON_WINDOW_CLOSE", "").strip().lower()
    return is_frozen() and override not in {"1", "true", "yes", "on"}


class _ResidentControls(QObject):
    """Trusted local restore/exit surface for a resident packaged assistant."""

    exitRequested = pyqtSignal(str)

    def __init__(self, window: "MainWindow", icon: QIcon) -> None:
        super().__init__(window)
        self._window = window
        self._notice_shown = False
        self.menu = QMenu("Onyx", window)
        self.show_action = QAction("Show Onyx", self.menu)
        self.exit_action = QAction("Exit Onyx", self.menu)
        self.exit_action.setMenuRole(QAction.MenuRole.QuitRole)
        self.show_action.triggered.connect(self.restore)
        self.exit_action.triggered.connect(
            lambda: self.exitRequested.emit("local-exit-menu")
        )
        self.menu.addAction(self.show_action)
        self.menu.addSeparator()
        self.menu.addAction(self.exit_action)

        self.tray: QSystemTrayIcon | None = None
        if _close_to_background_enabled() and QSystemTrayIcon.isSystemTrayAvailable():
            tray_icon = (
                icon if not icon.isNull() else QIcon.fromTheme("applications-system")
            )
            self.tray = QSystemTrayIcon(tray_icon, window)
            self.tray.setToolTip("Onyx — Cyryx Labs")
            self.tray.setContextMenu(self.menu)
            self.tray.activated.connect(self._on_tray_activated)
            self.tray.show()

    @property
    def tray_available(self) -> bool:
        return self.tray is not None and self.tray.isVisible()

    @pyqtSlot()
    def restore(self) -> None:
        self._window.showNormal()
        self._window.show()
        self._window.raise_()
        self._window.activateWindow()

    @pyqtSlot(QSystemTrayIcon.ActivationReason)
    def _on_tray_activated(self, reason) -> None:
        if reason in {
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        }:
            self.restore()

    @pyqtSlot()
    def notify_background_once(self) -> None:
        if self._notice_shown:
            return
        self._notice_shown = True
        if self.tray_available and self.tray is not None:
            self.tray.showMessage(
                "Onyx is still active",
                "Use the Onyx tray menu to restore or exit the assistant.",
                QSystemTrayIcon.MessageIcon.Information,
                5000,
            )

    def shutdown(self) -> None:
        if self.tray is not None:
            self.tray.hide()


def _dayops_visible_render(
    rendered: str,
    *,
    limit: int,
    payload: dict[str, object],
) -> str:
    """Bound DayOps JSON without concealing that the public result was cut."""

    if len(rendered) <= limit:
        return rendered
    planner = payload.get("planner")
    coverage = planner.get("coverage") if isinstance(planner, dict) else None
    details = "coverage remains available in the controller result"
    if isinstance(coverage, dict):
        details = (
            f"source_truncated={coverage.get('source_truncated', 'unknown')}; "
            f"output_truncated={coverage.get('output_truncated', 'unknown')}; "
            f"calendar={coverage.get('calendar_pagination', 'unknown')}; "
            f"mail={coverage.get('mail_pagination', 'unknown')}"
        )
    marker = f"\n[TRUNCATED: DayOps display exceeded {limit} characters; {details}]"
    if len(marker) >= limit:
        return marker[:limit]
    return rendered[: limit - len(marker)] + marker


def _advanced_operations_visible_render(
    status: dict[str, object],
    attention: dict[str, object],
    *,
    limit: int = 4000,
) -> str:
    """Render an allowlisted, bounded local operations projection for the HUD."""

    state = str(status.get("status", "unavailable"))[:48].upper()
    lines = [f"OPERATIONS  /  {state}"]
    capabilities = status.get("capabilities")
    if isinstance(capabilities, (tuple, list)):
        safe = [
            " ".join(str(item).split())[:64]
            for item in capabilities[:16]
            if isinstance(item, str)
        ]
        if safe:
            lines.append("CAPABILITIES  /  " + " · ".join(safe))
    for label, key in (
        ("AUTOMATION QUEUE", "automation_queued"),
        ("AWARENESS QUEUE", "awareness_queued"),
        ("AUTOMATION RULES", "automation_rules"),
        ("ENROLLED DEVICES", "enrolled_devices"),
        ("SITE PROJECTS", "site_projects"),
        ("WORKFLOWS", "workflow_graphs"),
        ("CONTEXT NODES", "context_nodes"),
        ("CONTEXT LINKS", "context_edges"),
        ("ACTIVE PREFERENCES", "active_preferences"),
    ):
        value = status.get(key)
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            lines.append(f"{label}  /  {value}")

    workflows = status.get("workflow_summaries", ())
    if isinstance(workflows, (tuple, list)):
        for item in workflows[:6]:
            if not isinstance(item, dict):
                continue
            name = " ".join(str(item.get("name", "")).split())[:80]
            state = " ".join(str(item.get("status", "")).split())[:24].upper()
            kinds = item.get("node_kinds", ())
            if not name or not isinstance(kinds, (tuple, list)):
                continue
            safe_kinds = [str(kind)[:20].upper() for kind in kinds[:8]]
            lines.append(f"FLOW  /  {state}  /  {name}")
            lines.append("  " + "  >  ".join(safe_kinds))

    rhythm = attention.get("rhythm")
    if isinstance(rhythm, dict) and rhythm.get("status") == "ready":
        cadence = " ".join(str(rhythm.get("cadence", "daily")).split())[:32]
        lines.append("")
        lines.append("TODAY  /  " + cadence.replace("_", " ").upper())
        focus = rhythm.get("focus")
        if isinstance(focus, (tuple, list)):
            for item in focus[:3]:
                if not isinstance(item, dict):
                    continue
                title = " ".join(str(item.get("title", "Untitled goal")).split())[:160]
                health = " ".join(str(item.get("health", "unknown")).split())[:32]
                lines.append(f"• FOCUS  /  {health.upper()}  /  {title}")
        actions = rhythm.get("actions")
        if isinstance(actions, (tuple, list)):
            for item in actions[:5]:
                if not isinstance(item, dict):
                    continue
                title = " ".join(str(item.get("title", "Untitled action")).split())[
                    :160
                ]
                level = " ".join(str(item.get("level", "goal")).split())[:32]
                lines.append(f"• NEXT  /  {level.upper()}  /  {title}")
        warnings = rhythm.get("warnings")
        if isinstance(warnings, (tuple, list)):
            for item in warnings[:8]:
                clean = " ".join(str(item).split())[:200]
                if clean:
                    lines.append(f"! {clean}")

    attention_items = attention.get("attention")
    if isinstance(attention_items, (tuple, list)) and attention_items:
        lines.append("")
        lines.append("ATTENTION")
        for item in attention_items[:12]:
            clean = " ".join(str(item).split())[:240]
            if clean:
                lines.append(f"• {clean}")

    goals = attention.get("goals")
    if isinstance(goals, (tuple, list)) and goals:
        lines.append("")
        lines.append("PRIORITY GOALS")
        for item in goals[:12]:
            if not isinstance(item, dict):
                continue
            title = " ".join(str(item.get("title", "Untitled goal")).split())[:160]
            level = " ".join(str(item.get("level", "goal")).split())[:32].upper()
            health = " ".join(str(item.get("health", "unknown")).split())[:32].upper()
            score = item.get("score")
            score_text = (
                f"{float(score):.2f}" if isinstance(score, (int, float)) else "--"
            )
            lines.append(f"• {level}  /  {health}  /  {score_text}  /  {title}")

    rendered = "\n".join(lines)
    marker = f"\n[TRUNCATED: operations projection exceeded {limit} characters]"
    if len(rendered) <= limit:
        return rendered
    if len(marker) >= limit:
        return marker[:limit]
    return rendered[: limit - len(marker)] + marker


def _configure_native_app_identity() -> bool:
    """Declare the Onyx process identity before Qt creates any windows."""
    if platform.system() != "Windows":
        return False
    try:
        import ctypes

        result = ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
            WINDOWS_APP_USER_MODEL_ID
        )
        return result == 0
    except (AttributeError, OSError):
        return False


def _set_windows_shortcut_app_id(path: str | Path) -> bool:
    """Bind a Windows shortcut to the same taskbar identity as the Qt process."""
    if platform.system() != "Windows":
        return False
    try:
        from win32com.propsys import propsys, pscon  # type: ignore
        from win32com.shell import shellcon  # type: ignore

        store = propsys.SHGetPropertyStoreFromParsingName(
            str(path),
            None,
            shellcon.GPS_READWRITE,
            propsys.IID_IPropertyStore,
        )
        store.SetValue(
            pscon.PKEY_AppUserModel_ID,
            propsys.PROPVARIANTType(WINDOWS_APP_USER_MODEL_ID),
        )
        store.Commit()
        return True
    except Exception:
        return False


def _base_dir() -> Path:
    return resource_root()


BASE_DIR = _base_dir()
CONFIG_DIR = config_dir()
API_FILE = CONFIG_DIR / "api_keys.json"


def _application_icon_path() -> Path | None:
    """Resolve the official Orb icon in source checkouts and frozen bundles."""
    candidates = (
        BASE_DIR / "assets" / "onyx.png",
        BASE_DIR / "packaging" / "assets" / "onyx-app-icon-master-v2.png",
        CONFIG_DIR / "onyx.ico",
    )
    return next((path for path in candidates if path.is_file()), None)


# Opt-in only until the cinematic shell passes its independent acceptance gate.
# The exact comparison is intentional: ambiguous/truthy values cannot activate it.
HUD_V5_LIVE = os.environ.get("ONYX_HUD_V5_LIVE", "0").strip() == "1"
_QML_SCENE_GRAPH_CLAIMED = False


def _owner_autonomy_warning(roots: list[str]) -> str:
    resolved = []
    for value in roots:
        try:
            resolved.append(str(Path(value).expanduser().resolve(strict=True)))
        except (OSError, RuntimeError):
            continue
    root_text = (
        "\n".join(f"  - {item}" for item in resolved) or "  - no valid writable roots"
    )
    return (
        "Owner autonomy grants broad browser and computer control that can create external effects, including composed messages or purchases.\n\nAutonomous writable roots:\n"
        + root_text
    )


_DEFAULT_W, _DEFAULT_H = 1280, 820
_MIN_W, _MIN_H = 1024, 680
_LEFT_W = 166
_RIGHT_W = 286

_OS = platform.system()  # "Windows" | "Darwin" | "Linux"


class C:
    # Cyryx Labs Design System v1.0 — official product palette.
    ONYX = "#050607"
    OBSIDIAN = "#0A0D0F"
    GRAPHITE = "#11161A"
    GUNMETAL = "#1B2227"
    STEEL = "#8C949E"
    SILVER = "#C7C9CC"
    CORE_TEAL = "#0F6B68"
    TEAL_GLOW = "#19C7C0"

    BG = ONYX
    PANEL = OBSIDIAN
    PANEL2 = GRAPHITE
    BORDER = GUNMETAL
    BORDER_B = CORE_TEAL
    BORDER_A = GUNMETAL
    PRI = TEAL_GLOW
    PRI_DIM = CORE_TEAL
    PRI_GHO = CORE_TEAL
    ACC = STEEL
    ACC2 = SILVER
    GREEN = TEAL_GLOW
    GREEN_D = CORE_TEAL
    # Restrained semantic red is retained only for errors, mute and interruption.
    RED = "#A74D57"
    MUTED_C = RED
    TEXT = SILVER
    TEXT_DIM = STEEL
    TEXT_MED = STEEL
    WHITE = SILVER
    DARK = ONYX
    BAR_BG = GRAPHITE


def qcol(h: str, a: int = 255) -> QColor:
    c = QColor(h)
    c.setAlpha(a)
    return c


# ── Windows GPU via NVML DLL (no subprocess, no console window) ──────────────
_nvml_lib: object = None  # cached ctypes DLL
_nvml_ok: object = None  # None=untested, True=works, False=unavailable


def _nvml_gpu_windows() -> float:
    """Return NVIDIA GPU utilisation % using nvml.dll directly — zero subprocess."""
    global _nvml_lib, _nvml_ok
    if _nvml_ok is False:
        return -1.0
    try:
        import ctypes

        class _Util(ctypes.Structure):
            _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

        if _nvml_lib is None:
            for dll_name in ("nvml", r"C:\Windows\System32\nvml.dll"):
                try:
                    lib = ctypes.WinDLL(dll_name)
                    lib.nvmlInit_v2()
                    _nvml_lib = lib
                    break
                except Exception:
                    continue

        if _nvml_lib is None:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            _nvml_ok = True
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)

        dev = ctypes.c_void_p()
        _nvml_lib.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
        util = _Util()
        _nvml_lib.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(util))
        _nvml_ok = True
        return float(util.gpu)
    except Exception:
        _nvml_ok = False
        return -1.0


class _SysMetrics:
    POLL_SECONDS = 2.0
    STOP_TIMEOUT = 2.0

    def __init__(self):
        self.cpu = 0.0
        self.mem = 0.0
        self.net = 0.0
        self.gpu = -1.0
        self.tmp = -1.0
        self._lock = threading.Lock()
        self._lifecycle_lock = threading.Lock()
        self._stop = threading.Event()
        self._thread = None
        self._com = None
        self._com_client = None
        self._com_ready = False
        self._last_net = None
        self._last_net_t = time.time()
        self._sample_index = 0
        self._gpu_cache = -1.0
        self._temp_cache = -1.0
    def start(self) -> bool:
        """Start sampling explicitly on the UI owner thread, never during import."""
        if threading.current_thread() is not threading.main_thread():
            raise RuntimeError("System metrics must be started by the main thread")
        with self._lifecycle_lock:
            if self._thread is not None and self._thread.is_alive():
                return False
            if _OS == "Windows" and self._com is None:
                try:
                    # pythoncom initializes its importing thread. Import on the
                    # owner thread, then balance explicit COM use in _loop.
                    import pythoncom
                    import win32com.client

                    self._com = pythoncom
                    self._com_client = win32com.client
                except ImportError:
                    # CPU/memory/network metrics remain available without WMI.
                    pass
            self._stop.clear()
            self._last_net = None
            self._last_net_t = time.time()
            self._sample_index = 0
            self._thread = threading.Thread(
                target=self._loop, name="onyx-system-metrics", daemon=True
            )
            self._thread.start()
            return True

    def stop(self, timeout: float = STOP_TIMEOUT) -> bool:
        """Wait boundedly; a blocked native query must not freeze Qt shutdown."""
        if isinstance(timeout, bool) or not math.isfinite(timeout) or timeout < 0:
            raise ValueError("Invalid metrics stop timeout")
        with self._lifecycle_lock:
            self._stop.set()
            thread = self._thread
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout)
        return thread is None or not thread.is_alive()

    def shutdown(self) -> None:
        if not self.stop():
            print("[Onyx Metrics] Shutdown timeout; native sample still running.", flush=True)

    def _loop(self):
        try:
            if self._com is not None:
                try:
                    self._com.CoInitializeEx(self._com.COINIT_MULTITHREADED)
                    self._com_ready = True
                except self._com.com_error:
                    # Do not issue WMI calls in an uninitialized apartment.
                    self._com_ready = False
            while not self._stop.is_set():
                try:
                    self._update()
                except Exception:
                    pass
                if self._stop.wait(self.POLL_SECONDS):
                    break
        finally:
            if self._com_ready:
                self._com_ready = False
                self._com.CoUninitialize()

    def _update(self):
        cpu = psutil.cpu_percent(interval=None)
        mem = psutil.virtual_memory().percent

        nc = psutil.net_io_counters()
        now = time.time()
        dt = now - self._last_net_t
        if dt > 0 and self._last_net is not None:
            sent = (nc.bytes_sent - self._last_net.bytes_sent) / dt
            recv = (nc.bytes_recv - self._last_net.bytes_recv) / dt
            net = (sent + recv) / (1024 * 1024)
        else:
            net = 0.0
        self._last_net = nc
        self._last_net_t = now

        self._sample_index += 1
        if self._sample_index == 1 or self._sample_index % 2 == 0:
            self._gpu_cache = self._get_gpu()
        if self._sample_index == 1 or self._sample_index % 15 == 0:
            self._temp_cache = self._get_temp()
        gpu = self._gpu_cache
        tmp = self._temp_cache

        with self._lock:
            self.cpu = cpu
            self.mem = mem
            self.net = net
            self.gpu = gpu
            self.tmp = tmp

    def _get_gpu(self) -> float:
        if _OS == "Windows":
            return _nvml_gpu_windows()

        # pynvml — subprocess-free, works on all platforms if installed
        try:
            import pynvml  # type: ignore

            pynvml.nvmlInit()
            h = pynvml.nvmlDeviceGetHandleByIndex(0)
            return float(pynvml.nvmlDeviceGetUtilizationRates(h).gpu)
        except Exception:
            pass

        # Linux / macOS: libnvidia-ml shared lib via ctypes
        try:
            import ctypes

            _lib = "libnvidia-ml.so.1" if _OS == "Linux" else "libnvidia-ml.dylib"

            class _Util(ctypes.Structure):
                _fields_ = [("gpu", ctypes.c_uint), ("memory", ctypes.c_uint)]

            nv = ctypes.CDLL(_lib)
            nv.nvmlInit_v2()
            dev = ctypes.c_void_p()
            nv.nvmlDeviceGetHandleByIndex_v2(0, ctypes.byref(dev))
            u = _Util()
            nv.nvmlDeviceGetUtilizationRates(dev, ctypes.byref(u))
            return float(u.gpu)
        except Exception:
            pass

        return -1.0  # N/A — zero subprocess on all platforms

    def _get_temp(self) -> float:
        # psutil — works on Linux; occasionally Windows with driver support
        try:
            temps = psutil.sensors_temperatures()
            for name in [
                "coretemp",
                "k10temp",
                "cpu_thermal",
                "acpitz",
                "cpu-thermal",
                "zenpower",
                "it8688",
            ]:
                if name in temps and temps[name]:
                    return temps[name][0].current
            for entries in temps.values():
                if entries:
                    return entries[0].current
        except Exception:
            pass

        # Keep WMI proxies local to this apartment. The `wmi` package creates
        # module-global COM objects at import, unsafe across worker lifetimes.
        if _OS == "Windows" and self._com_ready:
            services = rows = zone = None
            try:
                services = self._com_client.GetObject("winmgmts:root/wmi")
                rows = services.ExecQuery("SELECT CurrentTemperature FROM MSAcpi_ThermalZoneTemperature")
                for zone in rows:
                    return (zone.CurrentTemperature / 10.0) - 273.15
            except Exception:
                pass
            finally:
                # Release on the creating thread before _loop uninitializes COM.
                zone = rows = services = None

        return -1.0  # N/A — zero subprocess on all platforms

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "cpu": self.cpu,
                "mem": self.mem,
                "net": self.net,
                "gpu": self.gpu,
                "tmp": self.tmp,
            }


_metrics = _SysMetrics()


class HudCanvas(QWidget):
    def __init__(self, face_path: str, parent=None, *, reduced_motion: bool = False):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_OpaquePaintEvent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

        self.muted = False
        self.speaking = False
        self.state = "INITIALISING"
        self.reduced_motion = bool(reduced_motion)
        self.audio_level = 0.0
        self._adaptive_fps = 24
        self._slow_frames = 0
        self._healthy_frames = 0

        self._tick = 0
        self._scale = 1.0
        self._tgt_scale = 1.0
        self._halo = 55.0
        self._tgt_halo = 55.0
        self._last_t = time.time()
        self._scan = 0.0
        self._scan2 = 180.0
        self._rings = [0.0, 120.0, 240.0]
        self._pulses: list[float] = [0.0, 50.0, 100.0]
        self._blink = True
        self._blink_tick = 0
        self._particles: list[list[float]] = []
        # Deterministic volumetric particle cloud based on the Cyryx Orb
        # reference: a dense irregular shell plus suspended interior matter.
        _rng = random.Random(481)
        self._orb_nodes: list[tuple[float, float, float, float, float]] = []
        for _i in range(1600):
            _y = _rng.uniform(-1.0, 1.0)
            _theta = _rng.uniform(0.0, math.tau)
            _rr = math.sqrt(max(0.0, 1.0 - _y * _y))
            if _rng.random() < 0.86:
                _radial = _rng.uniform(0.84, 1.0)
            else:
                _radial = (_rng.random() ** (1.0 / 3.0)) * 0.88
            _radial *= 1.0 + 0.035 * math.sin(_theta * 5.0 + _y * 3.0)
            self._orb_nodes.append(
                (
                    math.cos(_theta) * _rr * _radial,
                    _y * _radial,
                    math.sin(_theta) * _rr * _radial,
                    _rng.uniform(0.24, 0.92),
                    _rng.uniform(0.0, math.tau),
                )
            )
        self._face_px: QPixmap | None = None
        self._static_frame: QPixmap | None = None
        self._static_frame_key: tuple[int, int, bool, str] | None = None
        self._load_face(face_path)

        self._tmr = QTimer(self)
        self._tmr.setTimerType(Qt.TimerType.CoarseTimer)
        self._tmr.timeout.connect(self._step)

    def _animation_required(self) -> bool:
        return (
            not self.reduced_motion
            and not self.muted
            and self.state not in {"MUTED", "OFFLINE"}
        )

    def _target_fps(self) -> int:
        requested = (
            24
            if self.speaking
            else (20 if self.state in {"THINKING", "PROCESSING"} else 12)
        )
        return min(requested, self._adaptive_fps)

    def _invalidate_static_frame(self) -> None:
        self._static_frame = None
        self._static_frame_key = None

    def sync_animation(self) -> None:
        """Run the Orb only while cognition is visibly active.

        Listening, muted, hidden and minimised states are cached still frames,
        so the Orb consumes no recurring paint CPU while waiting for the owner.
        """
        window = self.window()
        should_run = (
            self._animation_required()
            and self.isVisible()
            and not (window and window.isMinimized())
        )
        if should_run:
            interval = max(42, round(1000 / self._target_fps()))
            if not self._tmr.isActive() or self._tmr.interval() != interval:
                self._tmr.start(interval)
        else:
            self._tmr.stop()
        self.update()

    def set_operational_state(self, state: str) -> None:
        speaking = state == "SPEAKING"
        if state == self.state and speaking == self.speaking:
            return
        self.state = state
        self.speaking = speaking
        self._invalidate_static_frame()
        self.sync_animation()

    def set_muted(self, muted: bool) -> None:
        muted = bool(muted)
        if muted == self.muted:
            return
        self.muted = muted
        self._invalidate_static_frame()
        self.sync_animation()

    def set_reduced_motion(self, reduced: bool) -> None:
        reduced = bool(reduced)
        if reduced == self.reduced_motion:
            return
        self.reduced_motion = reduced
        self._invalidate_static_frame()
        self.sync_animation()

    def set_audio_level(self, level: float) -> None:
        try:
            value = float(level)
        except (TypeError, ValueError):
            value = 0.0
        if not math.isfinite(value):
            value = 0.0
        self.audio_level = max(0.0, min(1.0, value))

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_animation()

    def hideEvent(self, event):
        self._tmr.stop()
        super().hideEvent(event)

    def resizeEvent(self, event):
        self._invalidate_static_frame()
        super().resizeEvent(event)

    def _load_face(self, path: str):
        try:
            from PIL import Image, ImageDraw
            import io

            img = Image.open(path).convert("RGBA")
            sz = min(img.size)
            img = img.resize((sz, sz), Image.LANCZOS)
            mk = Image.new("L", (sz, sz), 0)
            ImageDraw.Draw(mk).ellipse((2, 2, sz - 2, sz - 2), fill=255)
            img.putalpha(mk)
            buf = io.BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._face_px = px
        except Exception:
            self._face_px = None

    def _step(self):
        window = self.window()
        if (
            not self._animation_required()
            or not self.isVisible()
            or (window and window.isMinimized())
        ):
            self._tmr.stop()
            return

        self._tick += 1
        now = time.time()
        if now - self._last_t > (0.12 if self.speaking else 0.5):
            if self.speaking:
                self._tgt_scale = 1.02 + self.audio_level * 0.065
                self._tgt_halo = 105 + self.audio_level * 82
            elif self.muted:
                self._tgt_scale = random.uniform(0.998, 1.002)
                self._tgt_halo = random.uniform(15, 28)
            else:
                self._tgt_scale = random.uniform(1.001, 1.008)
                self._tgt_halo = random.uniform(48, 68)
            self._last_t = now

        sp = 0.38 if self.speaking else 0.15
        self._scale += (self._tgt_scale - self._scale) * sp
        self._halo += (self._tgt_halo - self._halo) * sp

        speeds = [1.3, -0.9, 2.0] if self.speaking else [0.55, -0.35, 0.9]
        for i, spd in enumerate(speeds):
            self._rings[i] = (self._rings[i] + spd) % 360

        self._scan = (self._scan + (3.0 if self.speaking else 1.3)) % 360
        self._scan2 = (self._scan2 + (-2.0 if self.speaking else -0.75)) % 360

        fw = min(self.width(), self.height())
        lim = fw * 0.74
        spd = 4.2 if self.speaking else 2.0
        self._pulses = [r + spd for r in self._pulses if r + spd < lim]
        if len(self._pulses) < 3 and random.random() < (
            0.07 if self.speaking else 0.025
        ):
            self._pulses.append(0.0)

        if self.speaking and random.random() < 0.28:
            cx, cy = self.width() / 2, self.height() / 2
            ang = random.uniform(0, 2 * math.pi)
            r_s = fw * 0.28
            self._particles.append(
                [
                    cx + math.cos(ang) * r_s,
                    cy + math.sin(ang) * r_s,
                    math.cos(ang) * random.uniform(0.9, 2.4),
                    math.sin(ang) * random.uniform(0.9, 2.4) - 0.4,
                    1.0,
                ]
            )
        self._particles = [
            [p[0] + p[2], p[1] + p[3], p[2] * 0.97, p[3] * 0.97, p[4] - 0.028]
            for p in self._particles
            if p[4] > 0
        ]

        self._blink_tick += 1
        if self._blink_tick >= 38:
            self._blink = not self._blink
            self._blink_tick = 0
        self.update()

    def paintEvent(self, _):
        """Paint an active frame or blit the cached zero-idle-cost frame."""
        started = time.perf_counter()
        if not self._animation_required():
            key = (self.width(), self.height(), self.muted, self.state)
            if self._static_frame is None or self._static_frame_key != key:
                frame = QPixmap(max(1, self.width()), max(1, self.height()))
                frame.fill(QColor(C.ONYX))
                frame_painter = QPainter(frame)
                self._paint_orb(frame_painter)
                frame_painter.end()
                self._static_frame = frame
                self._static_frame_key = key
            p = QPainter(self)
            p.drawPixmap(0, 0, self._static_frame)
            p.end()
            self._report_frame_duration((time.perf_counter() - started) * 1000.0)
            return

        p = QPainter(self)
        self._paint_orb(p)
        p.end()
        self._report_frame_duration((time.perf_counter() - started) * 1000.0)

    def _report_frame_duration(self, duration_ms: float) -> None:
        fps = self._target_fps()
        budget = 1000.0 / fps
        if duration_ms > budget * 1.18:
            self._slow_frames += 1
            self._healthy_frames = 0
            if self._slow_frames >= 3 and self._adaptive_fps > 12:
                self._adaptive_fps = 12
                self._slow_frames = 0
                self.sync_animation()
        elif duration_ms < budget * 0.55:
            self._slow_frames = 0
            self._healthy_frames += 1
            if self._healthy_frames >= 180 and self._adaptive_fps < 24:
                self._adaptive_fps = 24
                self._healthy_frames = 0
                self.sync_animation()
        else:
            self._slow_frames = 0
            self._healthy_frames = 0

    def _paint_orb(self, p: QPainter) -> None:
        """Paint one Cyryx neural Orb frame into the supplied painter."""
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()
        cx, cy = W / 2, H * 0.395
        fw = min(W, H)

        backdrop = QRadialGradient(QPointF(cx, cy), max(W, H) * 0.68)
        backdrop.setColorAt(0.0, QColor(C.GRAPHITE))
        backdrop.setColorAt(0.50, QColor(C.OBSIDIAN))
        backdrop.setColorAt(1.0, QColor(C.ONYX))
        p.fillRect(self.rect(), QBrush(backdrop))

        orb_r = min(fw * 0.315 * self._scale, H * 0.285)
        active = C.MUTED_C if self.muted else C.PRI
        energy = 1.0 + (0.08 + self.audio_level * 0.18 if self.speaking else 0.0)

        # Soft volumetric bloom — no mechanical rings.
        aura = QRadialGradient(QPointF(cx, cy), orb_r * 1.24)
        aura.setColorAt(0.0, qcol(C.CORE_TEAL, 13 if not self.speaking else 24))
        aura.setColorAt(0.64, qcol(C.CORE_TEAL, 16))
        aura.setColorAt(0.84, qcol(active, 28 if not self.muted else 16))
        aura.setColorAt(1.0, qcol(active, 0))
        p.setPen(Qt.PenStyle.NoPen)
        p.setBrush(QBrush(aura))
        p.drawEllipse(QPointF(cx, cy), orb_r * 1.24, orb_r * 1.24)

        angle_y = self._tick * (0.0105 if self.speaking else 0.0042)
        angle_x = 0.24 + math.sin(self._tick * 0.0022) * 0.08
        sy, cyaw = math.sin(angle_y), math.cos(angle_y)
        sx, cxr = math.sin(angle_x), math.cos(angle_x)
        batches: dict[tuple[str, int, int], list[QPointF]] = {}
        node_step = (
            1
            if self.speaking
            else (2 if self.state in {"THINKING", "PROCESSING"} else 3)
        )
        for node_index in range(0, len(self._orb_nodes), node_step):
            nx, ny, nz, size, phase = self._orb_nodes[node_index]
            rx = nx * cyaw + nz * sy
            rz = -nx * sy + nz * cyaw
            ry = ny * cxr - rz * sx
            rz2 = ny * sx + rz * cxr
            perspective = 0.90 + (rz2 + 1.0) * 0.07
            turbulence = 1.0 + 0.018 * math.sin(self._tick * 0.014 + phase * 2.0)
            px = cx + rx * orb_r * perspective * turbulence
            py = cy + ry * orb_r * perspective * turbulence
            flicker = 0.62 + 0.38 * math.sin(self._tick * 0.048 + phase) ** 2
            visibility = max(0.10, (rz2 + 1.0) / 2.0)
            screen_radius = min(1.0, math.hypot(px - cx, py - cy) / orb_r)
            limb_light = max(0.0, (screen_radius - 0.58) / 0.42)
            alpha = int((38 + visibility * 150 + limb_light * 170) * flicker)
            if self.muted:
                color_hex = C.MUTED_C
                alpha = min(alpha, 150)
            elif limb_light > 0.62:
                color_hex = C.SILVER
                alpha = min(alpha + 24, 255)
            elif px < cx and py > cy and math.sin(phase * 2.7) > 0.72:
                color_hex = C.STEEL
                alpha = min(alpha + 8, 225)
            elif rz2 > 0.35:
                color_hex = C.PRI
                alpha = min(alpha + 16, 245)
            else:
                color_hex = C.PRI_DIM
                alpha = min(alpha, 205)
            radius = size * (0.62 + visibility * 0.66) * energy
            alpha_bucket = max(48, min(240, int(alpha / 48) * 48))
            size_bucket = 1 if radius < 0.72 else 2
            batches.setdefault((color_hex, alpha_bucket, size_bucket), []).append(
                QPointF(px, py)
            )

        p.setRenderHint(QPainter.RenderHint.Antialiasing, False)
        for (color_hex, alpha, size_bucket), points in batches.items():
            pen = QPen(qcol(color_hex, alpha))
            pen.setWidthF(1.1 if size_bucket == 1 else 1.9)
            pen.setCapStyle(Qt.PenCapStyle.RoundCap)
            p.setPen(pen)
            p.drawPoints(QPolygonF(points))
        p.setRenderHint(QPainter.RenderHint.Antialiasing, True)

        # Five diffuse cognitive cores, matching the actual reference frame.
        core_nodes = [
            (-0.16, -0.19, 0.060, C.TEAL_GLOW),
            (-0.11, -0.02, 0.066, C.TEAL_GLOW),
            (0.14, -0.04, 0.071, C.SILVER),
            (0.02, 0.14, 0.061, C.CORE_TEAL),
            (0.14, 0.24, 0.064, C.TEAL_GLOW),
        ]
        for index, (ox, oy, fraction, node_color) in enumerate(core_nodes):
            pulse = 1.0 + math.sin(self._tick * (0.045 + index * 0.006) + index) * 0.10
            ncx, ncy = cx + ox * orb_r, cy + oy * orb_r
            nr = orb_r * fraction * pulse * energy
            glow_r = nr * 2.35
            core_glow = QRadialGradient(QPointF(ncx, ncy), glow_r)
            core_glow.setColorAt(0.0, qcol(C.SILVER, 245))
            core_glow.setColorAt(0.16, qcol(node_color, 238))
            core_glow.setColorAt(0.46, qcol(node_color, 170 if self.speaking else 138))
            core_glow.setColorAt(0.76, qcol(node_color, 42))
            core_glow.setColorAt(1.0, qcol(node_color, 0))
            p.setBrush(QBrush(core_glow))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(ncx, ncy), glow_r, glow_r)

        if self.muted:
            status, status_color = "MICROPHONE MUTED", C.MUTED_C
        elif self.speaking:
            status, status_color = "RESPONDING", C.PRI
        elif self.state == "THINKING":
            status, status_color = "COGNITIVE PROCESS ACTIVE", C.ACC2
        elif self.state == "PROCESSING":
            status, status_color = "EXECUTING", C.ACC2
        elif self.state == "LISTENING":
            status, status_color = "LISTENING", C.GREEN
        else:
            status, status_color = self.state, C.PRI

        sy_text = cy + orb_r * 1.33
        p.setPen(QPen(qcol(status_color, 230), 1))
        p.setFont(QFont("Segoe UI", 10, QFont.Weight.DemiBold))
        p.drawText(QRectF(0, sy_text, W, 24), Qt.AlignmentFlag.AlignCenter, status)
        p.setPen(QPen(qcol(C.TEXT_DIM, 190), 1))
        p.setFont(QFont("Segoe UI", 7, QFont.Weight.Medium))
        p.drawText(
            QRectF(0, sy_text + 22, W, 18),
            Qt.AlignmentFlag.AlignCenter,
            "CYRYX NEURAL PRESENCE  /  CLOUD MODEL + LOCAL TOOL HOST",
        )

        # A restrained audio trace beneath the state label.
        trace_y = sy_text + 50
        bars, spacing = 42, 6
        x0 = cx - bars * spacing / 2
        for i in range(bars):
            if self.muted:
                height = 1.5
            elif self.speaking:
                height = 3 + abs(math.sin(self._tick * 0.18 + i * 0.72)) * (
                    7 + self.audio_level * 11
                )
            else:
                height = 2 + abs(math.sin(self._tick * 0.055 + i * 0.42)) * 3
            p.setPen(QPen(qcol(status_color, int(60 + height * 8)), 1.4))
            p.drawLine(
                QPointF(x0 + i * spacing, trace_y - height / 2),
                QPointF(x0 + i * spacing, trace_y + height / 2),
            )

    def _paint_previous_hud(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        p.fillRect(self.rect(), qcol(C.BG))

        W, H = self.width(), self.height()
        cx, cy = W / 2, H / 2
        fw = min(W, H)

        # grid dots
        p.setPen(QPen(qcol(C.PRI_GHO), 1))
        for x in range(0, W, 48):
            for y in range(0, H, 48):
                p.drawPoint(x, y)

        r_face = fw * 0.31

        # halo glow
        for i in range(10):
            r = r_face * (1.8 - i * 0.08)
            frc = 1.0 - i / 10
            a = max(0, min(255, int(self._halo * 0.085 * frc)))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - r, cy - r, r * 2, r * 2))

        # pulse rings
        for pr in self._pulses:
            a = max(0, int(230 * (1.0 - pr / (fw * 0.74))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a)
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            p.drawEllipse(QRectF(cx - pr, cy - pr, pr * 2, pr * 2))

        # spinning arc rings
        for idx, (r_frac, w_r, arc_l, gap) in enumerate(
            [(0.48, 3, 115, 78), (0.40, 2, 78, 55), (0.32, 1, 56, 40)]
        ):
            ring_r = fw * r_frac
            base = self._rings[idx]
            a_val = max(0, min(255, int(self._halo * (1.0 - idx * 0.18))))
            col = qcol(C.MUTED_C if self.muted else C.PRI, a_val)
            p.setPen(QPen(col, w_r))
            p.setBrush(Qt.BrushStyle.NoBrush)
            angle = base
            rect = QRectF(cx - ring_r, cy - ring_r, ring_r * 2, ring_r * 2)
            while angle < base + 360:
                p.drawArc(rect, int(angle * 16), int(arc_l * 16))
                angle += arc_l + gap

        # scanners
        sr = fw * 0.50
        sa = min(255, int(self._halo * 1.5))
        ex = 75 if self.speaking else 44
        p.setPen(QPen(qcol(C.MUTED_C if self.muted else C.PRI, sa), 2.5))
        p.setBrush(Qt.BrushStyle.NoBrush)
        srect = QRectF(cx - sr, cy - sr, sr * 2, sr * 2)
        p.drawArc(srect, int(self._scan * 16), int(ex * 16))
        p.setPen(QPen(qcol(C.ACC, sa // 2), 1.5))
        p.drawArc(srect, int(self._scan2 * 16), int(ex * 16))

        # tick marks
        t_out, t_in = fw * 0.497, fw * 0.474
        p.setPen(QPen(qcol(C.PRI, 140), 1))
        for deg in range(0, 360, 10):
            rad = math.radians(deg)
            inn = t_in if deg % 30 == 0 else t_in + 6
            p.drawLine(
                QPointF(cx + t_out * math.cos(rad), cy - t_out * math.sin(rad)),
                QPointF(cx + inn * math.cos(rad), cy - inn * math.sin(rad)),
            )

        # crosshair
        ch_r, gap_h = fw * 0.51, fw * 0.16
        p.setPen(QPen(qcol(C.PRI, int(self._halo * 0.5)), 1))
        p.drawLine(QPointF(cx - ch_r, cy), QPointF(cx - gap_h, cy))
        p.drawLine(QPointF(cx + gap_h, cy), QPointF(cx + ch_r, cy))
        p.drawLine(QPointF(cx, cy - ch_r), QPointF(cx, cy - gap_h))
        p.drawLine(QPointF(cx, cy + gap_h), QPointF(cx, cy + ch_r))

        # corner brackets
        bl = 24
        bc = qcol(C.PRI, 210)
        hl, hr = cx - fw // 2, cx + fw // 2
        ht, hb = cy - fw // 2, cy + fw // 2
        p.setPen(QPen(bc, 2))
        for bx, by, dx, dy in [
            (hl, ht, 1, 1),
            (hr, ht, -1, 1),
            (hl, hb, 1, -1),
            (hr, hb, -1, -1),
        ]:
            p.drawLine(QPointF(bx, by), QPointF(bx + dx * bl, by))
            p.drawLine(QPointF(bx, by), QPointF(bx, by + dy * bl))

        # face
        if self._face_px:
            fsz = int(fw * 0.62 * self._scale)
            scaled = self._face_px.scaled(
                fsz,
                fsz,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            p.drawPixmap(int(cx - fsz / 2), int(cy - fsz / 2), scaled)
        else:
            orb_r = int(fw * 0.27 * self._scale)
            oc = (200, 0, 50) if self.muted else (0, 60, 110)
            for i in range(8, 0, -1):
                r2 = int(orb_r * i / 8)
                frc = i / 8
                a = max(0, min(255, int(self._halo * 1.1 * frc)))
                p.setBrush(
                    QBrush(
                        QColor(int(oc[0] * frc), int(oc[1] * frc), int(oc[2] * frc), a)
                    )
                )
                p.setPen(Qt.PenStyle.NoPen)
                p.drawEllipse(QRectF(cx - r2, cy - r2, r2 * 2, r2 * 2))
            p.setPen(QPen(qcol(C.PRI, min(255, int(self._halo * 2))), 1))
            p.setFont(QFont("Cascadia Mono", 13, QFont.Weight.Bold))
            p.drawText(
                QRectF(cx - 80, cy - 14, 160, 28), Qt.AlignmentFlag.AlignCenter, "ONYX"
            )

        # particles
        for pt in self._particles:
            a = max(0, min(255, int(pt[4] * 255)))
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QBrush(qcol(C.PRI, a)))
            p.drawEllipse(QPointF(pt[0], pt[1]), 2.5, 2.5)

        # status text
        sy = cy + fw * 0.40
        if self.muted:
            txt, col = "⊘  MUTED", qcol(C.MUTED_C)
        elif self.speaking:
            txt, col = "●  SPEAKING", qcol(C.ACC)
        elif self.state == "THINKING":
            sym = "◈" if self._blink else "◇"
            txt, col = f"{sym}  THINKING", qcol(C.ACC2)
        elif self.state == "PROCESSING":
            sym = "▷" if self._blink else "▶"
            txt, col = f"{sym}  PROCESSING", qcol(C.ACC2)
        elif self.state == "LISTENING":
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  LISTENING", qcol(C.GREEN)
        else:
            sym = "●" if self._blink else "○"
            txt, col = f"{sym}  {self.state}", qcol(C.PRI)

        p.setPen(QPen(col, 1))
        p.setFont(QFont("Cascadia Mono", 11, QFont.Weight.Bold))
        p.drawText(QRectF(0, sy, W, 26), Qt.AlignmentFlag.AlignCenter, txt)

        # waveform
        wy = sy + 30
        N, bw = 36, 8
        wx0 = (W - N * bw) / 2
        for i in range(N):
            if self.muted:
                hgt, cl = 2, qcol(C.MUTED_C)
            elif self.speaking:
                hgt = random.randint(3, 20)
                cl = qcol(C.PRI) if hgt > 12 else qcol(C.PRI_DIM)
            else:
                hgt = int(3 + 2 * math.sin(self._tick * 0.09 + i * 0.6))
                cl = qcol(C.BORDER_B)
            p.fillRect(QRectF(wx0 + i * bw, wy + 20 - hgt, bw - 1, hgt), cl)


class OrbHost(QWidget):
    """One Quick3D Orb with a mutually-exclusive software HudCanvas fallback."""

    _SAFE_RENDERERS = frozenset({"software", "fallback", "safe", "2d"})

    def __init__(
        self,
        face_path: str,
        parent=None,
        *,
        qml_path: Path | None = None,
        force_fallback: bool | None = None,
    ) -> None:
        super().__init__(parent)
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)
        self.bridge = OrbStateBridge(self)
        self._mode = "fallback"
        self._quick = None
        self._fallback = HudCanvas(
            face_path, self, reduced_motion=self.bridge.reducedMotion
        )
        self._stack = QStackedLayout(self)
        self._stack.setContentsMargins(0, 0, 0, 0)
        self._stack.addWidget(self._fallback)
        self._show_fallback()

        requested = os.environ.get("ONYX_ORB_RENDERER", "auto").strip().lower()
        safe_mode = requested in self._SAFE_RENDERERS
        if force_fallback is not None:
            safe_mode = bool(force_fallback)
        if _QML_SCENE_GRAPH_CLAIMED:
            safe_mode = True
        if self.bridge.reducedMotion:
            safe_mode = True
        if not safe_mode:
            self._create_gpu_widget(
                qml_path or (resource_root() / "qml" / "OnyxOrb.qml")
            )

    @property
    def renderer_mode(self) -> str:
        return self._mode

    @property
    def fallback(self) -> HudCanvas:
        return self._fallback

    def _gpu_api_unavailable(self) -> bool:
        try:
            from PySide6.QtQuick import QQuickWindow, QSGRendererInterface

            api = QQuickWindow.graphicsApi()
            return api in {
                QSGRendererInterface.GraphicsApi.Software,
                QSGRendererInterface.GraphicsApi.Null,
                QSGRendererInterface.GraphicsApi.NullRhi,
            }
        except (ImportError, AttributeError, RuntimeError):
            return True

    def _create_gpu_widget(self, qml_path: Path) -> None:
        if self._gpu_api_unavailable():
            return
        try:
            # Public integration pattern from Qt's QQuickWidget documentation:
            # https://doc.qt.io/qt-6/qquickwidget.html
            from PySide6.QtQuickWidgets import QQuickWidget

            quick = QQuickWidget(self)
            quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
            quick.setClearColor(QColor(C.ONYX))
            context = quick.rootContext()
            if context is None:
                quick.deleteLater()
                return
            context.setContextProperty("orbBridge", self.bridge)
            self._quick = quick
            self._stack.addWidget(quick)
            quick.statusChanged.connect(self._on_qml_status)
            quick.sceneGraphError.connect(self._on_scene_graph_error)
            quick.setSource(QUrl.fromLocalFile(str(qml_path.resolve())))
            self._on_qml_status(quick.status())
        except (ImportError, OSError, RuntimeError):
            self._quick = None

    def _on_qml_status(self, status) -> None:
        if self._quick is None:
            return
        try:
            from PySide6.QtQuickWidgets import QQuickWidget
        except ImportError:
            self._show_fallback()
            return
        if status == QQuickWidget.Status.Ready:
            root = self._quick.rootObject()
            if root is not None and root.objectName() == "onyxOrbRoot":
                self._show_gpu()
                return
        if status == QQuickWidget.Status.Error:
            self._show_fallback()

    def _on_scene_graph_error(self, *_args) -> None:
        self._show_fallback()

    def _show_gpu(self) -> None:
        if self._quick is None:
            return
        self._mode = "gpu"
        self._fallback.hide()
        self._fallback.sync_animation()
        self._quick.show()
        self._stack.setCurrentWidget(self._quick)
        self.sync_animation()

    def _show_fallback(self) -> None:
        self._mode = "fallback"
        self.bridge.set_surface_active(False)
        if self._quick is not None:
            self._quick.hide()
        self._fallback.show()
        self._stack.setCurrentWidget(self._fallback)
        self._fallback.sync_animation()

    def set_operational_state(self, state: str) -> None:
        self.bridge.set_state(state)
        self._fallback.set_operational_state(state)
        self.sync_animation()

    def set_audio_level(self, level: float) -> None:
        self._fallback.set_audio_level(level)

    def set_muted(self, muted: bool) -> None:
        self.bridge.set_muted(muted)
        self._fallback.set_muted(muted)
        self.sync_animation()

    def set_reduced_motion(self, reduced: bool) -> None:
        self.bridge.set_reduced_motion(reduced)
        self._fallback.set_reduced_motion(reduced)
        if reduced:
            self._show_fallback()
        self.sync_animation()

    def sync_animation(self) -> None:
        window = self.window()
        surface_active = (
            self._mode == "gpu"
            and self.isVisible()
            and not (window and window.isMinimized())
        )
        self.bridge.set_surface_active(surface_active)
        if self._mode == "fallback":
            self._fallback.sync_animation()
        else:
            self._fallback._tmr.stop()

    def showEvent(self, event):
        super().showEvent(event)
        self.sync_animation()

    def hideEvent(self, event):
        self.bridge.set_surface_active(False)
        self._fallback._tmr.stop()
        super().hideEvent(event)


class EntityHudOverlay(QWidget):
    """Non-interactive holographic framing projected around the Onyx presence."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        w, h = self.width(), self.height()
        cx = w / 2
        cy = h * 0.395
        radius = min(w * 0.265, h * 0.31)

        # Segmented outer targeting arcs: sparse enough to frame, not cage, the Orb.
        arc_rect = QRectF(cx - radius, cy - radius, radius * 2, radius * 2)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.setPen(QPen(qcol(C.PRI, 72), 1.0))
        for start, span in [
            (12, 24),
            (55, 14),
            (104, 22),
            (151, 13),
            (193, 24),
            (238, 13),
            (286, 21),
            (329, 15),
        ]:
            p.drawArc(arc_rect, start * 16, span * 16)

        inner = radius * 0.90
        inner_rect = QRectF(cx - inner, cy - inner, inner * 2, inner * 2)
        p.setPen(QPen(qcol(C.ACC2, 42), 1.0, Qt.PenStyle.DotLine))
        p.drawArc(inner_rect, 205 * 16, 48 * 16)
        p.drawArc(inner_rect, 25 * 16, 48 * 16)

        # Four angular acquisition brackets and small energy nodes.
        p.setPen(QPen(qcol(C.PRI, 118), 1.2))
        arm = 21
        gap = radius * 0.82
        for sx, sy in [(-1, -1), (1, -1), (-1, 1), (1, 1)]:
            x = cx + sx * gap
            y = cy + sy * gap
            p.drawLine(QPointF(x, y), QPointF(x - sx * arm, y))
            p.drawLine(QPointF(x, y), QPointF(x, y - sy * arm))
            p.setBrush(QBrush(qcol(C.PRI, 175)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, y), 2.2, 2.2)
            p.setPen(QPen(qcol(C.PRI, 118), 1.2))

        # Peripheral signal paths visually connect the entity to functional modules.
        p.setPen(QPen(qcol(C.BORDER_B, 70), 1.0))
        left_x, right_x = 192.0, w - 312.0
        path_y = max(92.0, cy - radius * 0.78)
        p.drawLine(QPointF(left_x, path_y), QPointF(cx - radius * 1.05, path_y))
        p.drawLine(QPointF(cx + radius * 1.05, path_y), QPointF(right_x, path_y))
        for x in (left_x, right_x):
            p.setBrush(QBrush(qcol(C.ACC, 145)))
            p.setPen(Qt.PenStyle.NoPen)
            p.drawEllipse(QPointF(x, path_y), 2.0, 2.0)

        # Baseline telemetry ticks under the presence.
        baseline = min(h - 142.0, cy + radius * 1.10)
        p.setPen(QPen(qcol(C.PRI, 55), 1.0))
        for i in range(-9, 10):
            x = cx + i * 13
            tick = 7 if i % 3 == 0 else 3
            p.drawLine(QPointF(x, baseline - tick), QPointF(x, baseline))


class HolographicPanel(QWidget):
    """Static black-glass module with restrained Cyryx command geometry."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        r = QRectF(self.rect()).adjusted(1.0, 1.0, -1.0, -1.0)
        cut = 14.0
        path = QPainterPath()
        path.moveTo(r.left() + cut, r.top())
        path.lineTo(r.right() - cut * 2.1, r.top())
        path.lineTo(r.right(), r.top() + cut * 1.15)
        path.lineTo(r.right(), r.bottom() - cut)
        path.lineTo(r.right() - cut, r.bottom())
        path.lineTo(r.left() + cut * 0.7, r.bottom())
        path.lineTo(r.left(), r.bottom() - cut * 0.7)
        path.lineTo(r.left(), r.top() + cut)
        path.closeSubpath()

        p.setBrush(QBrush(qcol(C.OBSIDIAN, 232)))
        p.setPen(QPen(qcol(C.GUNMETAL, 240), 1.0))
        p.drawPath(path)

        p.setPen(QPen(qcol(C.CORE_TEAL, 215), 1.35))
        p.drawLine(
            QPointF(r.left() + cut, r.top()),
            QPointF(r.left() + min(150.0, r.width() * 0.22), r.top()),
        )
        p.drawLine(
            QPointF(r.right() - min(95.0, r.width() * 0.15), r.bottom()),
            QPointF(r.right() - cut, r.bottom()),
        )
        p.setBrush(QBrush(qcol(C.TEAL_GLOW, 220)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawEllipse(QPointF(r.left() + cut - 3, r.top()), 2.0, 2.0)


class MetricBar(QWidget):
    def __init__(self, label: str, color: str = C.PRI, parent=None):
        super().__init__(parent)
        self._label = label
        self._color = color
        self._value = 0.0  # 0–100
        self._text = "--"
        self.setFixedHeight(34)
        self.setMinimumWidth(80)

    def set_value(self, pct: float, text: str):
        self._value = max(0.0, min(100.0, pct))
        self._text = text
        self.update()

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        W, H = self.width(), self.height()

        p.setPen(QPen(qcol(C.GUNMETAL, 220), 1.0))
        p.drawLine(QPointF(0, 5), QPointF(0, H - 5))
        p.drawLine(QPointF(0, 5), QPointF(12, 5))

        bar_h = 2
        bar_y = H - 6
        bar_w = W - 10
        bar_x = 4
        fill_w = int(bar_w * self._value / 100)

        p.setBrush(QBrush(qcol(C.BAR_BG)))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRect(QRectF(bar_x, bar_y, bar_w, bar_h))

        if self._value > 85:
            bar_col = qcol(C.RED)
        elif self._value > 65:
            bar_col = qcol(C.ACC)
        else:
            bar_col = qcol(self._color)

        if fill_w > 0:
            p.setBrush(QBrush(bar_col))
            p.drawRect(QRectF(bar_x, bar_y, fill_w, bar_h))

        p.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(8, 3, 50, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            self._label,
        )

        p.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold))
        p.setPen(QPen(bar_col if self._text != "--" else qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(0, 2, W - 4, 16),
            Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter,
            self._text,
        )


class LogWidget(QTextEdit):
    _sig = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFont(QFont("Cascadia Mono", 9))
        self.setStyleSheet(f"""
            QTextEdit {{
                background: {C.PANEL};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 4px;
                padding: 6px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG};
                width: 8px;
                border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B};
                border-radius: 4px;
                min-height: 20px;
            }}
        """)
        self._queue: list[str] = []
        self._typing = False
        self._text = ""
        self._pos = 0
        self._tag = "sys"
        self._tmr = QTimer(self)
        self._tmr.timeout.connect(self._step)
        self._sig.connect(self._enqueue)

    def append_log(self, text: str):
        self._sig.emit(text)

    def _enqueue(self, text: str):
        self._queue.append(text)
        if not self._typing:
            self._next()

    def _next(self):
        if not self._queue:
            self._typing = False
            return
        self._typing = True
        self._text = self._queue.pop(0)
        self._pos = 0
        tl = self._text.lower()
        if tl.startswith("you:"):
            self._tag = "you"
        elif tl.startswith("onyx:"):
            self._tag = "ai"
        elif tl.startswith("file:"):
            self._tag = "file"
        elif "err" in tl:
            self._tag = "err"
        else:
            self._tag = "sys"
        self._tmr.start(6)

    def _step(self):
        if self._pos < len(self._text):
            ch = self._text[self._pos]
            cur = self.textCursor()
            fmt = cur.charFormat()
            col = {
                "you": qcol(C.WHITE),
                "ai": qcol(C.PRI),
                "err": qcol(C.RED),
                "file": qcol(C.GREEN),
                "sys": qcol(C.ACC2),
            }.get(self._tag, qcol(C.TEXT))
            fmt.setForeground(QBrush(col))
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText(ch, fmt)
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            self._pos += 1
        else:
            self._tmr.stop()
            cur = self.textCursor()
            cur.movePosition(cur.MoveOperation.End)
            cur.insertText("\n")
            self.setTextCursor(cur)
            self.ensureCursorVisible()
            QTimer.singleShot(20, self._next)


_FILE_ICONS = {
    "image": ("🖼", C.TEAL_GLOW),
    "video": ("🎬", C.SILVER),
    "audio": ("🎵", C.CORE_TEAL),
    "pdf": ("📄", C.STEEL),
    "word": ("📝", C.SILVER),
    "excel": ("📊", C.CORE_TEAL),
    "code": ("💻", C.TEAL_GLOW),
    "archive": ("📦", C.STEEL),
    "pptx": ("📊", C.SILVER),
    "text": ("📃", C.STEEL),
    "data": ("🔧", C.CORE_TEAL),
    "unknown": ("📎", C.STEEL),
}
_EXT_TO_CAT = {
    **dict.fromkeys(
        ["jpg", "jpeg", "png", "gif", "webp", "bmp", "tiff", "svg", "ico"], "image"
    ),
    **dict.fromkeys(["mp4", "avi", "mov", "mkv", "wmv", "flv", "webm", "m4v"], "video"),
    **dict.fromkeys(
        ["mp3", "wav", "ogg", "m4a", "aac", "flac", "wma", "opus"], "audio"
    ),
    **dict.fromkeys(["pdf"], "pdf"),
    **dict.fromkeys(["doc", "docx"], "word"),
    **dict.fromkeys(["xls", "xlsx", "ods"], "excel"),
    **dict.fromkeys(["ppt", "pptx"], "pptx"),
    **dict.fromkeys(
        [
            "py",
            "js",
            "ts",
            "jsx",
            "tsx",
            "html",
            "css",
            "java",
            "c",
            "cpp",
            "cs",
            "go",
            "rs",
            "rb",
            "php",
            "swift",
            "kt",
            "sh",
            "sql",
            "lua",
        ],
        "code",
    ),
    **dict.fromkeys(["zip", "tar", "gz", "bz2", "xz"], "archive"),
    **dict.fromkeys(["txt", "md", "rst", "log"], "text"),
    **dict.fromkeys(["csv", "tsv", "json", "xml"], "data"),
}


def _file_category(path: Path) -> str:
    return _EXT_TO_CAT.get(path.suffix.lower().lstrip("."), "unknown")


def _fmt_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    elif size < 1024**2:
        return f"{size / 1024:.1f} KB"
    elif size < 1024**3:
        return f"{size / 1024**2:.1f} MB"
    else:
        return f"{size / 1024**3:.1f} GB"


def _dispatch_selected_file(
    *,
    host_callback,
    legacy_model_callback,
    path: str,
    filename: str,
    suffix: str,
    size: str,
    runtime_dispatch=None,
) -> str:
    """Dispatch one selection to exactly one owner, preferring V18 host intake."""

    if host_callback is not None:
        if callable(runtime_dispatch) and runtime_dispatch(
            "file-intake", lambda: host_callback(path), None
        ):
            return "v18-host"
        return "quiesced"
    if legacy_model_callback is not None:
        message = (
            f"[FILE_UPLOADED] path={path} | name={filename} | "
            f"type={suffix} | size={size} | "
            f"Briefly tell the user you can see the file '{filename}' "
            f"({size}) has been uploaded and ask what they'd like to do with it."
        )
        if callable(runtime_dispatch) and runtime_dispatch(
            "legacy-file-message", lambda: legacy_model_callback(message), None
        ):
            return "legacy-model"
        return "quiesced"
    return "unhandled"


class FileDropZone(QWidget):
    file_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFixedHeight(100)
        self._current_file: str | None = None
        self._hovering = False
        self._drag_over = False
        self._dash_offset = 0.0
        self._anim_tmr = QTimer(self)
        self._anim_tmr.timeout.connect(self._animate)
        self._anim_tmr.setInterval(80)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        self._canvas = _DropCanvas(self)
        layout.addWidget(self._canvas)

    def _animate(self):
        if not (self._hovering or self._drag_over):
            self._anim_tmr.stop()
            return
        self._dash_offset = (self._dash_offset + 0.8) % 20
        self._canvas.update()

    def dragEnterEvent(self, e: QDragEnterEvent):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()
            self._drag_over = True
            if not self._anim_tmr.isActive():
                self._anim_tmr.start()
            self._canvas.update()

    def dragLeaveEvent(self, e):
        self._drag_over = False
        if not self._hovering:
            self._anim_tmr.stop()
        self._canvas.update()

    def dropEvent(self, e: QDropEvent):
        self._drag_over = False
        if not self._hovering:
            self._anim_tmr.stop()
        urls = e.mimeData().urls()
        if urls:
            path = urls[0].toLocalFile()
            if Path(path).is_file():
                self._set_file(path)
        self._canvas.update()

    def mousePressEvent(self, e):
        if e.button() == Qt.MouseButton.LeftButton:
            self._browse()

    def enterEvent(self, e):
        self._hovering = True
        if not self._anim_tmr.isActive():
            self._anim_tmr.start()
        self._canvas.update()

    def leaveEvent(self, e):
        self._hovering = False
        if not self._drag_over:
            self._anim_tmr.stop()
        self._canvas.update()

    def current_file(self) -> str | None:
        return self._current_file

    def clear_file(self):
        self._current_file = None
        self._canvas.update()

    def _browse(self):
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Select a file for Onyx",
            str(Path.home()),
            "All Files (*.*);;"
            "Images (*.jpg *.jpeg *.png *.gif *.webp *.bmp *.svg);;"
            "Documents (*.pdf *.docx *.txt *.md *.pptx);;"
            "Data (*.csv *.xlsx *.json *.xml);;"
            "Code (*.py *.js *.ts *.html *.css *.java *.cpp *.go);;"
            "Audio (*.mp3 *.wav *.ogg *.m4a *.aac *.flac);;"
            "Video (*.mp4 *.avi *.mov *.mkv *.wmv *.webm);;"
            "Archives (*.zip *.tar *.gz *.bz2 *.xz)",
        )
        if path:
            self._set_file(path)

    def _set_file(self, path: str):
        self._current_file = path
        self._canvas.update()
        self.file_selected.emit(path)


class _DropCanvas(QWidget):
    def __init__(self, zone: FileDropZone):
        super().__init__(zone)
        self._z = zone

    def paintEvent(self, _):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        z = self._z
        W, H = self.width(), self.height()
        pad = 6
        rect = QRectF(pad, pad, W - pad * 2, H - pad * 2)

        if z._drag_over:
            bg_col = qcol(C.CORE_TEAL, 58)
        elif z._hovering:
            bg_col = qcol(C.CORE_TEAL, 32)
        else:
            bg_col = qcol(C.PANEL)
        p.setBrush(QBrush(bg_col))
        p.setPen(Qt.PenStyle.NoPen)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:
            border_col = qcol(C.GREEN, 200)
        elif z._drag_over:
            border_col = qcol(C.PRI, 230)
        elif z._hovering:
            border_col = qcol(C.BORDER_B, 200)
        else:
            border_col = qcol(C.BORDER, 160)

        pen = QPen(border_col, 1.5, Qt.PenStyle.DashLine)
        pen.setDashOffset(z._dash_offset)
        p.setPen(pen)
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawRoundedRect(rect, 6, 6)

        if z._current_file:
            self._paint_file(p, W, H)
        elif z._drag_over:
            self._paint_drag_over(p, W, H)
        else:
            self._paint_idle(p, W, H, z._hovering)

    def _paint_idle(self, p, W, H, hover):
        cx, cy = W / 2, H / 2
        col = qcol(C.PRI_DIM if not hover else C.PRI)
        if H < 70:
            p.setPen(QPen(col, 1.5))
            p.setBrush(Qt.BrushStyle.NoBrush)
            icon_x = 24
            p.drawLine(QPointF(icon_x, cy + 6), QPointF(icon_x, cy - 7))
            p.drawLine(QPointF(icon_x - 5, cy - 2), QPointF(icon_x, cy - 7))
            p.drawLine(QPointF(icon_x + 5, cy - 2), QPointF(icon_x, cy - 7))
            p.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
            p.setPen(QPen(qcol(C.TEXT_MED if not hover else C.PRI), 1))
            p.drawText(
                QRectF(40, 0, W - 48, H),
                Qt.AlignmentFlag.AlignVCenter,
                "DROP / BROWSE CONTEXT",
            )
            return
        p.setPen(QPen(col, 2))
        p.setBrush(Qt.BrushStyle.NoBrush)
        p.drawLine(QPointF(cx, cy - 14), QPointF(cx, cy + 4))
        p.drawLine(QPointF(cx - 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx + 8, cy - 6), QPointF(cx, cy - 14))
        p.drawLine(QPointF(cx - 14, cy + 4), QPointF(cx + 14, cy + 4))
        p.setFont(QFont("Cascadia Mono", 8))
        p.setPen(QPen(qcol(C.PRI_DIM if not hover else C.TEXT), 1))
        p.drawText(
            QRectF(0, cy + 8, W, 16),
            Qt.AlignmentFlag.AlignCenter,
            "Drop file here  or  Click to Browse",
        )
        p.setFont(QFont("Cascadia Mono", 7))
        p.setPen(QPen(qcol(C.CORE_TEAL, 115), 1))
        p.drawText(
            QRectF(0, cy + 24, W, 14),
            Qt.AlignmentFlag.AlignCenter,
            "Images · Video · Audio · PDF · Docs · Code · Data",
        )

    def _paint_drag_over(self, p, W, H):
        cy = H / 2
        p.setFont(QFont("Cascadia Mono", 20))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(QRectF(0, cy - 24, W, 32), Qt.AlignmentFlag.AlignCenter, "⬇")
        p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.PRI), 1))
        p.drawText(
            QRectF(0, cy + 12, W, 16), Qt.AlignmentFlag.AlignCenter, "Release to load"
        )

    def _paint_file(self, p, W, H):
        path = Path(self._z._current_file)
        cat = _file_category(path)
        icon, icon_col = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size_str = _fmt_size(path.stat().st_size)
        ext_str = path.suffix.upper().lstrip(".") or "FILE"

        block_x, block_w = 10, 60
        p.setFont(
            QFont("Segoe UI Emoji", 22) if _OS == "Windows" else QFont("Arial", 22)
        )
        p.setPen(QPen(qcol(icon_col), 1))
        p.drawText(QRectF(block_x, 0, block_w, H), Qt.AlignmentFlag.AlignCenter, icon)

        tx = block_x + block_w + 6
        tw = W - tx - 38

        p.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.WHITE), 1))
        name = path.name if len(path.name) <= 34 else path.name[:31] + "..."
        p.drawText(
            QRectF(tx, H * 0.18, tw, 16),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            name,
        )

        p.setFont(QFont("Cascadia Mono", 7))
        p.setPen(QPen(qcol(C.TEXT_DIM), 1))
        p.drawText(
            QRectF(tx, H * 0.18 + 18, tw, 14),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            f"{ext_str}  ·  {size_str}",
        )

        p.setFont(QFont("Cascadia Mono", 6))
        p.setPen(QPen(qcol(C.CORE_TEAL, 145), 1))
        par = str(path.parent)
        if len(par) > 42:
            par = "…" + par[-41:]
        p.drawText(
            QRectF(tx, H * 0.18 + 34, tw, 12),
            Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter,
            par,
        )

        p.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold))
        p.setPen(QPen(qcol(C.RED, 180), 1))
        p.drawText(QRectF(W - 34, 0, 28, H), Qt.AlignmentFlag.AlignCenter, "✕")

    def mousePressEvent(self, e):
        z = self._z
        if z._current_file and e.pos().x() > self.width() - 34:
            z.clear_file()
        else:
            z.mousePressEvent(e)


class _CameraPreview(QWidget):
    """Floating overlay that briefly shows what the camera captured."""

    _W, _H = 244, 188

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            _CameraPreview {{
                background: rgba(0, 6, 10, 242);
                border: 1px solid {C.PRI};
                border-radius: 6px;
            }}
        """)
        self.setFixedWidth(self._W)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(6, 5, 6, 6)
        lay.setSpacing(4)

        hdr = QHBoxLayout()
        title = QLabel("◈  VISUAL INPUT")
        title.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(title)
        hdr.addStretch()
        close_btn = QPushButton("✕")
        close_btn.setFixedSize(16, 16)
        close_btn.setFont(QFont("Cascadia Mono", 8))
        close_btn.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent; border: none;"
        )
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.clicked.connect(self.hide)
        hdr.addWidget(close_btn)
        lay.addLayout(hdr)

        self._img_lbl = QLabel()
        self._img_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._img_lbl.setStyleSheet("background: transparent;")
        lay.addWidget(self._img_lbl)

        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.hide)

        self.hide()

    def show_frame(self, img_bytes: bytes) -> None:
        px = QPixmap()
        px.loadFromData(img_bytes)
        if not px.isNull():
            max_w = self._W - 12
            scaled = px.scaled(
                max_w,
                160,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
            self._img_lbl.setPixmap(scaled)
            self._img_lbl.setFixedSize(scaled.width(), scaled.height())
            self.adjustSize()
        self.show()
        self.raise_()
        self._timer.start(6_000)  # auto-dismiss after 6 s


class SetupOverlay(QWidget):
    done = pyqtSignal(str, str, str)
    dismissed = pyqtSignal()

    def __init__(
        self,
        parent=None,
        *,
        credential_configured: bool = False,
        dismissible: bool = False,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            SetupOverlay {{
                background: rgba(0, 6, 10, 245);
                border: 1px solid {C.BORDER_B};
                border-radius: 6px;
            }}
        """)

        detected = {"darwin": "mac", "windows": "windows"}.get(_OS.lower(), "linux")
        self._sel_os = detected

        layout = QVBoxLayout(self)
        layout.setContentsMargins(30, 22, 30, 22)
        layout.setSpacing(8)

        def _lbl(
            txt,
            font_size=9,
            bold=False,
            color=C.PRI,
            align=Qt.AlignmentFlag.AlignCenter,
        ):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(
                QFont(
                    "Cascadia Mono",
                    font_size,
                    QFont.Weight.Bold if bold else QFont.Weight.Normal,
                )
            )
            w.setStyleSheet(f"color: {color}; background: transparent;")
            return w

        layout.addWidget(_lbl("◈  INITIALISATION REQUIRED", 13, True))
        layout.addWidget(_lbl("Configure Onyx before first boot.", 9, color=C.PRI_DIM))
        layout.addSpacing(6)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep)
        layout.addSpacing(4)

        layout.addWidget(
            _lbl("YOUR NAME", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft)
        )
        self._name_input = QLineEdit()
        self._name_input.setPlaceholderText("How should Onyx address you?")
        self._name_input.setFont(QFont("Cascadia Mono", 10))
        self._name_input.setFixedHeight(34)
        self._name_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.OBSIDIAN}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 5px; padding: 4px 9px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        try:
            existing_name = json.loads(API_FILE.read_text(encoding="utf-8")).get(
                "owner_name", ""
            )
        except Exception:
            existing_name = ""
        self._name_input.setText(str(existing_name).strip())
        layout.addWidget(self._name_input)
        layout.addSpacing(8)

        layout.addWidget(
            _lbl(
                "GEMINI API KEY", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft
            )
        )
        self._key_input = QLineEdit()
        self._key_input.setEchoMode(QLineEdit.EchoMode.Password)
        self._key_input.setPlaceholderText("AIza…")
        self._key_input.setFont(QFont("Cascadia Mono", 10))
        self._key_input.setFixedHeight(32)
        self._key_input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.OBSIDIAN}; color: {C.TEXT};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 4px 8px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._credential_configured = credential_configured
        if credential_configured:
            self._key_input.setPlaceholderText("Secure credential already configured")
            self._key_input.setEnabled(False)
        layout.addWidget(self._key_input)
        self._setup_error = _lbl("", 8, color=C.RED, align=Qt.AlignmentFlag.AlignLeft)
        self._setup_error.setWordWrap(True)
        layout.addWidget(self._setup_error)
        layout.addSpacing(8)

        layout.addWidget(
            _lbl("ONYX VOICE", 8, color=C.TEXT_DIM, align=Qt.AlignmentFlag.AlignLeft)
        )
        self._voice_select = QComboBox()
        self._voice_select.setObjectName("onyxLiveVoiceSelectorV1")
        self._voice_select.addItems(VOICES)
        self._voice_select.setFont(QFont("Cascadia Mono", 10))
        self._voice_select.setFixedHeight(34)
        self._voice_select.setCursor(Qt.CursorShape.PointingHandCursor)
        self._voice_select.setStyleSheet(f"""
            QComboBox {{
                background: {C.OBSIDIAN}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 5px;
                padding: 4px 9px;
            }}
            QComboBox:focus {{ border: 1px solid {C.PRI}; }}
            QComboBox QAbstractItemView {{
                background: {C.OBSIDIAN}; color: {C.WHITE};
                border: 1px solid {C.BORDER_B};
                selection-background-color: {C.PRI_GHO};
            }}
        """)
        try:
            current_voice = LiveVoicePreferenceV1(
                memory_dir() / "live_voice_preference_v1.json"
            ).get()
        except Exception:
            current_voice = VOICES[0]
        self._voice_select.setCurrentText(current_voice)
        self._voice_select.setToolTip(
            "Select the Gemini Live voice used by Onyx. The live session refreshes automatically."
        )
        layout.addWidget(self._voice_select)
        layout.addSpacing(12)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER};")
        layout.addWidget(sep2)
        layout.addSpacing(4)

        layout.addWidget(
            _lbl(
                "OPERATING SYSTEM",
                8,
                color=C.TEXT_DIM,
                align=Qt.AlignmentFlag.AlignLeft,
            )
        )
        det_name = {"windows": "Windows", "mac": "macOS", "linux": "Linux"}[detected]
        layout.addWidget(
            _lbl(
                f"Auto-detected: {det_name}",
                8,
                color=C.ACC2,
                align=Qt.AlignmentFlag.AlignLeft,
            )
        )

        os_row = QHBoxLayout()
        os_row.setSpacing(6)
        self._os_btns: dict[str, QPushButton] = {}
        for key, label in [
            ("windows", "⊞  Windows"),
            ("mac", "  macOS"),
            ("linux", "🐧  Linux"),
        ]:
            btn = QPushButton(label)
            btn.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold))
            btn.setFixedHeight(32)
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _, k=key: self._sel(k))
            os_row.addWidget(btn)
            self._os_btns[key] = btn
        layout.addLayout(os_row)
        self._sel(detected)
        layout.addSpacing(12)

        init_btn = QPushButton("▸  INITIALISE SYSTEMS")
        init_btn.setFont(QFont("Cascadia Mono", 10, QFont.Weight.Bold))
        init_btn.setFixedHeight(36)
        init_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        init_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; border: 1px solid {C.PRI};
            }}
        """)
        init_btn.clicked.connect(self._submit)
        layout.addWidget(init_btn)

        dayops_btn = QPushButton("◇  MICROSOFT DAYOPS CONNECTION")
        dayops_btn.setObjectName("onyxDayOpsConnectionButtonV19")
        dayops_btn.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold))
        dayops_btn.setFixedHeight(32)
        dayops_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        dayops_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.SILVER};
                border: 1px solid {C.GUNMETAL}; border-radius: 3px;
            }}
            QPushButton:hover {{ color: {C.TEAL_GLOW}; border-color: {C.CORE_TEAL}; }}
        """)
        dayops_btn.clicked.connect(self._open_dayops)
        layout.addWidget(dayops_btn)

        # First-run setup remains mandatory.  Once Onyx is already configured,
        # Escape provides a non-mutating return path from the same overlay
        # without adding or moving any visual control in the accepted HUD.
        self._dismiss_shortcut: QShortcut | None = None
        if dismissible:
            self._dismiss_shortcut = QShortcut(QKeySequence("Escape"), self)
            self._dismiss_shortcut.setContext(
                Qt.ShortcutContext.WidgetWithChildrenShortcut
            )
            self._dismiss_shortcut.activated.connect(self.dismissed.emit)

    def _sel(self, key: str):
        self._sel_os = key
        pal = {
            "windows": (C.PRI, C.GRAPHITE),
            "mac": (C.SILVER, C.GRAPHITE),
            "linux": (C.CORE_TEAL, C.GRAPHITE),
        }
        for k, btn in self._os_btns.items():
            if k == key:
                fg, bg = pal[k]
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {fg}; color: {bg};
                        border: none; border-radius: 3px; font-weight: bold;
                    }}
                """)
            else:
                btn.setStyleSheet(f"""
                    QPushButton {{
                        background: {C.OBSIDIAN}; color: {C.TEXT_DIM};
                        border: 1px solid {C.BORDER}; border-radius: 3px;
                    }}
                    QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
                """)

    def _submit(self):
        owner_name = self._name_input.text().strip()
        if not owner_name:
            self._name_input.setFocus()
            self._setup_error.setText("Please tell Onyx how to address you.")
            return
        key = self._key_input.text().strip()
        if not key and not self._credential_configured:
            self._key_input.setStyleSheet(
                self._key_input.styleSheet()
                + f" QLineEdit {{ border: 1px solid {C.RED}; }}"
            )
            return
        self.done.emit(key, self._sel_os, owner_name[:80])

    @property
    def selected_voice(self) -> str:
        return self._voice_select.currentText()

    def _open_dayops(self) -> None:
        window = self.window()
        callback = getattr(window, "_request_v5_dayops", None)
        if not callable(callback) or callback() is False:
            self._setup_error.setText(
                "DayOps becomes available after Onyx finishes initialization."
            )

    def show_error(self, message: str) -> None:
        self._setup_error.setText(message)
        self._key_input.clear()
        (
            self._key_input if self._key_input.isEnabled() else self._name_input
        ).setFocus()


class RemoteKeyOverlay(QWidget):
    """Floating overlay — QR code for instant phone pairing + manual key fallback."""

    closed = pyqtSignal()

    _OW, _OH = 400, 465

    def __init__(
        self,
        url: str,
        key: str,
        auto_login_url: str = "",
        manual_url: str = "",
        expiry_secs: int = 600,
        parent=None,
    ):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_StyledBackground, True)
        self.setStyleSheet(f"""
            RemoteKeyOverlay {{
                background: rgba(0, 4, 12, 0.95);
                border: 1px solid {C.BORDER_B};
                border-radius: 14px;
            }}
        """)
        self._expiry = time.time() + expiry_secs
        self._on_new_key = None
        self._auto_login_url = auto_login_url
        self._manual_url = manual_url or url

        lay = QVBoxLayout(self)
        lay.setContentsMargins(24, 16, 24, 16)
        lay.setSpacing(5)

        def _lbl(
            txt, fs=9, bold=False, color=C.PRI, align=Qt.AlignmentFlag.AlignCenter
        ):
            w = QLabel(txt)
            w.setAlignment(align)
            w.setFont(
                QFont(
                    "Cascadia Mono",
                    fs,
                    QFont.Weight.Bold if bold else QFont.Weight.Normal,
                )
            )
            w.setStyleSheet(f"color: {color}; background: transparent;")
            w.setWordWrap(True)
            return w

        lay.addWidget(_lbl("◈  REMOTE ACCESS", 12, True))
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep)

        # ── QR code ───────────────────────────────────────────────────────────
        self._qr_label = QLabel()
        self._qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._qr_label.setFixedSize(176, 176)
        self._qr_label.setStyleSheet(
            "background: white; border-radius: 10px; padding: 4px;"
        )
        qr_row = QHBoxLayout()
        qr_row.addStretch()
        qr_row.addWidget(self._qr_label)
        qr_row.addStretch()
        lay.addLayout(qr_row)

        self._update_qr(auto_login_url)

        lay.addWidget(
            _lbl("Scan with phone camera to connect instantly", 8, color=C.TEXT_DIM)
        )

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 1px 0;")
        lay.addWidget(sep2)

        lay.addWidget(
            _lbl(
                "Or enter manually:",
                7,
                color=C.TEXT_DIM,
                align=Qt.AlignmentFlag.AlignLeft,
            )
        )

        self._url_lbl = QLabel(self._manual_url)
        self._url_lbl.setFont(QFont("Cascadia Mono", 8))
        self._url_lbl.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        self._url_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._url_lbl.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        lay.addWidget(self._url_lbl)

        self._key_lbl = QLabel(key)
        self._key_lbl.setFont(QFont("Cascadia Mono", 28, QFont.Weight.Bold))
        self._key_lbl.setStyleSheet(f"""
            color: {C.ACC};
            background: {C.PANEL2};
            border: 1px solid {C.BORDER_B};
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 10px;
        """)
        self._key_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._key_lbl)

        self._timer_lbl = QLabel()
        self._timer_lbl.setFont(QFont("Cascadia Mono", 8))
        self._timer_lbl.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._timer_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._timer_lbl)

        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        new_btn = QPushButton("NEW KEY")
        new_btn.setFixedHeight(32)
        new_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        new_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        new_btn.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 5px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        new_btn.clicked.connect(self._refresh_key)
        btn_row.addWidget(new_btn)

        close_btn = QPushButton("DISMISS")
        close_btn.setFixedHeight(32)
        close_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        close_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        close_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border: 1px solid {C.BORDER_B}; }}
        """)
        close_btn.clicked.connect(self._do_close)
        btn_row.addWidget(close_btn)
        lay.addLayout(btn_row)

        self._ctimer = QTimer(self)
        self._ctimer.timeout.connect(self._tick)
        self._ctimer.start(1000)
        self._tick()

    def set_new_key_callback(self, fn) -> None:
        self._on_new_key = fn

    def _update_qr(self, url: str) -> None:
        if not url:
            self._qr_label.setText("—")
            return
        try:
            import qrcode as _qrmod
            from io import BytesIO

            qr = _qrmod.QRCode(
                box_size=5,
                border=2,
                error_correction=_qrmod.constants.ERROR_CORRECT_M,
            )
            qr.add_data(url)
            qr.make(fit=True)
            img = qr.make_image(fill_color="black", back_color="white")
            buf = BytesIO()
            img.save(buf, format="PNG")
            px = QPixmap()
            px.loadFromData(buf.getvalue())
            self._qr_label.setPixmap(
                px.scaled(
                    170,
                    170,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        except ImportError:
            self._qr_label.setText("pip install\nqrcode[pil]")
            self._qr_label.setFont(QFont("Cascadia Mono", 8))
            self._qr_label.setStyleSheet(
                "color: #888; background: white; border-radius: 10px; padding: 4px;"
            )
        except Exception:
            self._qr_label.setText(url[:28])
            self._qr_label.setFont(QFont("Cascadia Mono", 7))
            self._qr_label.setStyleSheet(
                f"color: {C.PRI}; background: white; border-radius: 10px; padding: 4px;"
            )

    def _tick(self):
        remaining = max(0, int(self._expiry - time.time()))
        m, s = divmod(remaining, 60)
        self._timer_lbl.setText(f"Key expires in  {m:02d}:{s:02d}")
        if remaining == 0:
            self._do_close()

    def mark_connected(self) -> None:
        """Call from any thread when a phone successfully connects."""
        self._ctimer.stop()
        self._key_lbl.setText("CONNECTED")
        self._key_lbl.setStyleSheet(f"""
            color: {C.GREEN};
            background: rgba(34,197,94,0.08);
            border: 2px solid rgba(34,197,94,0.4);
            border-radius: 8px;
            padding: 6px 4px;
            letter-spacing: 4px;
        """)
        self._qr_label.setText("✓")
        self._qr_label.setFont(QFont("Cascadia Mono", 54, QFont.Weight.Bold))
        self._qr_label.setStyleSheet(
            f"color: {C.TEAL_GLOW}; background: {C.OBSIDIAN}; border-radius: 10px;"
        )
        self._timer_lbl.setText("Phone connected — Onyx ready")
        self._timer_lbl.setStyleSheet(f"color: {C.GREEN}; background: transparent;")

    def _refresh_key(self):
        if self._on_new_key:
            result = self._on_new_key()
            if result:
                url = result[0]
                key = result[1]
                auto = result[2] if len(result) >= 3 else ""
                manual = result[3] if len(result) >= 4 else url
                self._manual_url = manual or url
                self._url_lbl.setText(self._manual_url)
                self._key_lbl.setText(key)
                self._auto_login_url = auto
                self._update_qr(auto or url)
                self._expiry = time.time() + 600
                self._key_lbl.setStyleSheet(f"""
                    color: {C.ACC};
                    background: {C.PANEL2};
                    border: 1px solid {C.BORDER_B};
                    border-radius: 8px;
                    padding: 6px 4px;
                    letter-spacing: 10px;
                """)
                self._timer_lbl.setStyleSheet(
                    f"color: {C.TEXT_MED}; background: transparent;"
                )
                self._ctimer.start(1000)
                self._tick()

    def _do_close(self):
        self._ctimer.stop()
        self.hide()
        self.closed.emit()


# Load the accepted V3 projection and governor without coupling the default-off
# legacy path to their concrete symbols.  The accepted candidate files remain
# byte-exact; this integration only subclasses their public contracts.
_HudProjectionV3Base = getattr(
    importlib.import_module("core.ui_projection_" + "v3"),
    "OnyxUIProjection" + "V3",
)
_HudGovernorV3Base = getattr(
    importlib.import_module("core.render_governor_" + "v3"),
    "RenderGovernor" + "V3",
)
_HudRenderSnapshot = getattr(
    importlib.import_module("core.render_governor_" + "v3"),
    "RenderSnapshot",
)


def _verify_current_hud_contract(root: Path) -> dict[str, object] | None:
    """Select the source or packaged HUD authority for this exact host."""

    if is_frozen():
        # The full-source V25 authority intentionally includes selectors,
        # build code and regression tests that are absent from a curated
        # application bundle.  Frozen hosts authenticate only the sealed
        # packaged subset and its build-time V25 source receipt.
        packaged = importlib.import_module("core.onyx_packaged_runtime_hud_contract_v17")
        return packaged.verify_packaged_runtime_hud_contract(root)
    else:
        acceptance = importlib.import_module("core.onyx_hud_current_acceptance_v48")
        return acceptance.verify_current_hud_acceptance(root)


_CURRENT_HUD_OWNED_MODULES: list[object] = []


def install_current_hud_v10() -> bool:
    """Authenticate and install the accepted current HUD for every launch path."""

    ui_module = sys.modules[__name__]
    _verify_current_hud_contract(resource_root())
    modules = [
        importlib.import_module(f"core.onyx_hud_orb_v{version}")
        for version in range(6, 18)
    ]
    if getattr(ui_module, "_ONYX_HUD_V17_INSTALLATION", None) is not None:
        return modules[-1].install_current(ui_module) is True

    previous_flags: dict[str, str | None] = {}
    installed: list[object] = []
    try:
        # V6-V9 are candidate-gated immutable predecessors.  The explicit
        # current-HUD selector owns their temporary activation flags and
        # restores the caller environment before returning.
        for version, module in zip(range(6, 10), modules[:4], strict=True):
            marker = f"_ONYX_HUD_V{version}_INSTALLATION"
            if getattr(ui_module, marker, None) is not None:
                continue
            flag = module.FLAG_NAME
            previous_flags[flag] = os.environ.get(flag)
            os.environ[flag] = "1"
            if module.install_candidate(ui_module) is not True:
                raise RuntimeError(f"accepted HUD V{version} bootstrap refused")
            installed.append(module)

        if modules[-1].install_current(ui_module) is not True:
            raise RuntimeError("accepted HUD V16 installation refused")
        # V16 owns and recursively rolls back V10-V15.  Recording those
        # internal successors separately would attempt to uninstall them twice.
        installed.append(modules[-1])
        _CURRENT_HUD_OWNED_MODULES[:] = installed
        return True
    except BaseException:
        for module in reversed(installed):
            module.uninstall_candidate(ui_module)
        raise
    finally:
        for flag, previous in previous_flags.items():
            if previous is None:
                os.environ.pop(flag, None)
            else:
                os.environ[flag] = previous


def uninstall_current_hud_v10() -> bool:
    """Rollback exactly the authenticated HUD modules owned by this selector."""

    ui_module = sys.modules[__name__]
    owned = tuple(_CURRENT_HUD_OWNED_MODULES)
    if not owned:
        return False
    for module in reversed(owned):
        if module.uninstall_candidate(ui_module) is not True:
            raise RuntimeError("accepted current HUD rollback was not exact")
    _CURRENT_HUD_OWNED_MODULES.clear()
    return True


class _BalancedHudGovernorV5(_HudGovernorV3Base):
    """16 FPS active ceiling with a sticky 12 FPS adaptive downgrade."""

    def __init__(self) -> None:
        super().__init__()
        self._adaptive_cap = 16

    def target_fps(self, *, now: float | None = None) -> int:
        if not self.animation_running(now=now):
            return 0
        if self._state in {"THINKING", "PROCESSING", "SPEAKING"}:
            return min(16, self._adaptive_cap)
        return 12

    def snapshot(self, *, now: float | None = None):
        current = self._now(now)
        fps = self.target_fps(now=current)
        return _HudRenderSnapshot(
            state=self._state,
            target_fps=fps,
            animation_running=fps > 0,
            particle_budget=64 if fps >= 16 else 48,
            visible=self._visible,
            minimized=self._minimized,
            reduced_motion=self._reduced_motion,
            muted=self._muted,
        )

    def report_frame(self, duration_ms: float, *, now: float | None = None) -> bool:
        duration = float(duration_ms)
        if not math.isfinite(duration) or duration < 0:
            raise ValueError("duration_ms must be finite and non-negative")
        current = self._now(now)
        fps = self.target_fps(now=current)
        if fps == 0:
            self._slow_frames = 0
            self._healthy_frames = 0
            return False
        if duration > (1000.0 / fps) * 1.18:
            self._slow_frames += 1
            self._healthy_frames = 0
            if self._slow_frames >= 3 and self._adaptive_cap != 12:
                self._adaptive_cap = 12
                self._slow_frames = 0
                self._tier_changed_at = current
                return True
        else:
            self._slow_frames = 0
        return False


class _HudV5Projection(_HudProjectionV3Base):
    """Live-only projection that preserves the existing MainWindow contract."""

    liveDataChanged = pyqtSignal()

    def __init__(self, owner: "MainWindow", owner_name: str) -> None:
        self._owner = owner
        self._file_label = "NO FILE ATTACHED"
        self._log_lines: list[str] = []
        self._content_title = "ACTIVE CONTEXT"
        self._content_text = "Onyx is standing by."
        self._content_visible = False
        self._camera_active = False
        self._autonomy_enabled = bool(owner._autonomy_enabled)
        self._metrics = "CPU --  /  MEM --  /  NET --"
        super().__init__(
            owner,
            governor=_BalancedHudGovernorV5(),
            owner_name=owner_name,
            callbacks={
                "command": owner._submit_v5_command,
                "mute": owner._set_v5_muted,
                "settings": owner._request_v5_setup,
                "history": owner._request_v5_history,
                "permissions": owner._request_v5_permissions,
                "close": owner.close,
            },
        )

    @pyqtProperty(str, notify=liveDataChanged)
    def fileLabel(self) -> str:  # noqa: N802 - QML property spelling
        return self._file_label

    @pyqtProperty(str, notify=liveDataChanged)
    def logText(self) -> str:  # noqa: N802
        # The trace panel elides after six lines. Put the newest entry first so
        # wrapping cannot hide it behind startup diagnostics.
        return "\n".join(reversed(self._log_lines[-6:])) or "SYSTEM  /  ONLINE"

    @pyqtProperty(str, notify=liveDataChanged)
    def historyText(self) -> str:  # noqa: N802
        return "\n".join(self._log_lines[-48:]) or "SYSTEM  /  ONLINE"

    @pyqtProperty(str, notify=liveDataChanged)
    def contentTitle(self) -> str:  # noqa: N802
        return self._content_title

    @pyqtProperty(str, notify=liveDataChanged)
    def contentText(self) -> str:  # noqa: N802
        return self._content_text

    @pyqtProperty(bool, notify=liveDataChanged)
    def contentVisible(self) -> bool:  # noqa: N802
        return self._content_visible

    @pyqtProperty(bool, notify=liveDataChanged)
    def cameraActive(self) -> bool:  # noqa: N802
        return self._camera_active

    @pyqtProperty(bool, notify=liveDataChanged)
    def autonomyEnabled(self) -> bool:  # noqa: N802
        return self._autonomy_enabled

    @pyqtProperty(str, notify=liveDataChanged)
    def metricsSummary(self) -> str:  # noqa: N802
        return self._metrics

    def append_log(self, text: str) -> None:
        clean = " ".join(str(text).split())[:320]
        if clean:
            self._log_lines.append(clean)
            del self._log_lines[:-48]
            if clean.startswith("Onyx:"):
                self.set_transcript("ONYX", clean.partition(":")[2].strip())
            self.liveDataChanged.emit()

    def set_file(self, path: str) -> None:
        candidate = Path(path)
        try:
            detail = f"{candidate.name}  /  {_fmt_size(candidate.stat().st_size)}"
        except OSError:
            detail = candidate.name or "NO FILE ATTACHED"
        self._file_label = detail[:160]
        self.liveDataChanged.emit()

    def set_content(self, title: str, text: str, *, visible: bool = True) -> None:
        self._content_title = " ".join(str(title).split())[:80] or "ACTIVE CONTEXT"
        self._content_text = str(text)[:4000]
        self._content_visible = bool(visible)
        self.set_transcript(self._content_title, self._content_text)
        self.liveDataChanged.emit()

    def set_camera_active(self, active: bool) -> None:
        active = bool(active)
        if active != self._camera_active:
            self._camera_active = active
            self.liveDataChanged.emit()

    def set_autonomy_enabled(self, enabled: bool) -> None:
        enabled = bool(enabled)
        if enabled != self._autonomy_enabled:
            self._autonomy_enabled = enabled
            self.liveDataChanged.emit()

    def set_metrics(self, cpu: float, mem: float, net_label: str) -> None:
        self._metrics = f"CPU {cpu:.0f}%  /  MEM {mem:.0f}%  /  NET {net_label}"
        self.liveDataChanged.emit()

    def _host_action(self, name: str, callback) -> bool:
        try:
            result = callback()
        except Exception as exc:
            self._set_action_result(
                f"{name} FAILED", f"{name.lower()}: {type(exc).__name__}"
            )
            return False
        accepted = result is not False
        self._set_action_result(
            f"{name} {'REQUESTED' if accepted else 'UNAVAILABLE'}",
            "" if accepted else f"{name.lower()}: unavailable",
        )
        return accepted

    @pyqtSlot(result=bool)
    def requestFile(self) -> bool:  # noqa: N802
        return self._host_action("FILE", self._owner._request_v5_file)

    @pyqtSlot(str, result=bool)
    def acceptDroppedFile(self, value: str) -> bool:  # noqa: N802
        url = QUrl(str(value))
        path = url.toLocalFile() if url.isLocalFile() else str(value)
        return self._host_action("FILE", lambda: self._owner._accept_v5_file(path))

    @pyqtSlot(result=bool)
    def requestInterrupt(self) -> bool:  # noqa: N802
        return self._host_action("INTERRUPT", self._owner._request_v5_interrupt)

    @pyqtSlot(result=bool)
    def requestAutonomy(self) -> bool:  # noqa: N802
        return self._host_action("AUTONOMY", self._owner._request_v5_autonomy)

    @pyqtSlot(result=bool)
    def requestRemote(self) -> bool:  # noqa: N802
        return self._host_action("REMOTE", self._owner._request_v5_remote)

    @pyqtSlot(result=bool)
    def requestFullscreen(self) -> bool:  # noqa: N802
        return self._host_action("FULLSCREEN", self._owner._request_v5_fullscreen)

    @pyqtSlot(result=bool)
    def requestExit(self) -> bool:  # noqa: N802
        return self._host_action("EXIT ONYX", self._owner._request_owner_exit)

    @pyqtSlot(result=bool)
    def requestSetup(self) -> bool:  # noqa: N802
        return self._host_action("SETUP", self._owner._request_v5_setup)

    @pyqtSlot(result=bool)
    def requestCamera(self) -> bool:  # noqa: N802
        return self._host_action("CAMERA", self._owner._request_v5_camera)

    @pyqtSlot(result=bool)
    def requestDayOps(self) -> bool:  # noqa: N802
        return self._host_action("DAYOPS", self._owner._request_v5_dayops)

    @pyqtSlot(result=bool)
    def requestAdvancedOperations(self) -> bool:  # noqa: N802
        return self._host_action(
            "OPERATIONS", self._owner._request_v5_advanced_operations
        )

    @pyqtSlot()
    def dismissContent(self) -> None:  # noqa: N802
        self._content_visible = False
        self.liveDataChanged.emit()


class _CinematicHudV5Host(QWidget):
    """One long-lived QQuickWidget whose source is atomically loaded or cleared."""

    rendererFailed = pyqtSignal(str)

    def __init__(self, owner: "MainWindow", owner_name: str) -> None:
        super().__init__(owner)
        from PySide6.QtQuickWidgets import QQuickWidget

        global _QML_SCENE_GRAPH_CLAIMED
        _QML_SCENE_GRAPH_CLAIMED = True

        self.projection = _HudV5Projection(owner, owner_name)
        self.bridge = self.projection
        self._motion = OrbMotionPolicyV1()
        self._motion_item: QObject | None = None
        self._motion_last_frame_at: float | None = None
        self._motion_callback_count = 0
        self._motion_timer = QTimer(self)
        self._motion_timer.setTimerType(Qt.TimerType.CoarseTimer)
        self._motion_timer.timeout.connect(self._advance_orb_motion)
        self.projection.stateChanged.connect(self._sync_orb_motion)
        self.projection.renderPolicyChanged.connect(self._sync_orb_motion)
        self.projection.audioLevelChanged.connect(self._sync_orb_motion)
        self._quick = QQuickWidget(self)
        self._source = resource_root() / "qml" / "OnyxLiveShellV5.qml"
        self._scene_signal_connected = False
        self._loaded = False
        self._shutdown = False
        self._quick.setResizeMode(QQuickWidget.ResizeMode.SizeRootObjectToView)
        self._quick.setClearColor(QColor(C.ONYX))
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self._quick)
        self.load_source()
        self.setSizePolicy(QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding)

    def _connect_scene_signal(self) -> None:
        if not self._scene_signal_connected:
            self._quick.sceneGraphError.connect(self._scene_graph_error)
            self._scene_signal_connected = True

    def _disconnect_scene_signal(self) -> None:
        if not self._scene_signal_connected:
            return
        try:
            self._quick.sceneGraphError.disconnect(self._scene_graph_error)
        except (RuntimeError, TypeError):
            pass
        self._scene_signal_connected = False

    def load_source(self) -> None:
        if self._shutdown:
            raise RuntimeError("cinematic HUD host is shut down")
        if self._loaded:
            return
        self._quick.rootContext().setContextProperty(
            "onyxUIProjectionV3", self.projection
        )
        self._connect_scene_signal()
        self._quick.setSource(QUrl.fromLocalFile(str(self._source.resolve())))
        errors = "\n".join(error.toString() for error in self._quick.errors())
        root = self._quick.rootObject()
        if (
            self._quick.status() != type(self._quick).Status.Ready
            or root is None
            or root.objectName() != "onyxLiveShellV5Root"
        ):
            self.suspend()
            raise RuntimeError(errors or "cinematic HUD root failed its contract")
        self._loaded = True
        self._quick.show()
        # The widget's showEvent can fire before the QML finishes loading (while
        # _loaded is still False), leaving the projection lifecycle at
        # visible=False -> animationRunning=False, which freezes the speaking
        # voice-layer lights. Re-sync now that the scene is loaded and shown so
        # the inner lights animate whenever Onyx is in an active/speaking state.
        self.sync_animation()

    def suspend(self) -> None:
        """Stop QML timers and release the scene while retaining one reusable widget."""
        self.projection.set_lifecycle(visible=False, minimized=False)
        self._motion_timer.stop()
        self._motion_item = None
        self._motion_last_frame_at = None
        self._loaded = False
        self._quick.hide()
        self._quick.setSource(QUrl())
        self._disconnect_scene_signal()

    def shutdown(self) -> None:
        """Quiesce the QML host without destroying its tree inside closeEvent.

        Qt delivers the owner's close event through ``QQuickWidget::event``.
        Clearing the QML source or forcing ``DeferredDelete`` from that callback
        re-enters ``QQmlData::destroyed`` while QML is still executing.  Real
        Windows hosts fail-fast in that state.  The QObject parent hierarchy
        owns final destruction after the event returns; this method therefore
        only stops producers and disconnects renderer callbacks.
        """
        if self._shutdown:
            return
        self.projection.set_lifecycle(visible=False, minimized=False)
        self._motion_timer.stop()
        self._motion_item = None
        self._motion_last_frame_at = None
        self._disconnect_scene_signal()
        self._shutdown = True

    @property
    def renderer_mode(self) -> str:
        return "qml-v5"

    def _scene_graph_error(self, _error, message: str) -> None:
        self.projection.set_lifecycle(visible=False, minimized=True)
        self.rendererFailed.emit(str(message)[:240])

    def set_operational_state(self, state: str) -> None:
        self.projection.set_operational_state(state)
        self._sync_orb_motion()

    def set_muted(self, muted: bool) -> None:
        self.projection.set_muted(muted)
        self._sync_orb_motion()

    def set_reduced_motion(self, reduced: bool) -> None:
        self.projection.set_reduced_motion(reduced)
        self._sync_orb_motion()

    def set_audio_level(self, level: float) -> None:
        self.projection.set_audio_level(level)

    def set_visual_attention(self, x: float, y: float, source: str) -> bool:
        """Forward one bounded attention sample into the current QML root."""

        root = self._quick.rootObject() if self._loaded else None
        callback = getattr(root, "setVisualAttention", None) if root is not None else None
        if not callable(callback):
            return False
        callback(
            max(-1.0, min(1.0, float(x))),
            max(-1.0, min(1.0, float(y))),
            str(source)[:24],
        )
        return True

    def _current_orb_motion_item(self) -> QObject | None:
        if self._motion_item is not None:
            return self._motion_item
        root = self._quick.rootObject() if self._loaded else None
        if root is None:
            return None
        for object_name in (
            "onyxOrbLiquidMetalV9Root",
            "onyxOrbCinematicV5Root",
            "onyxOrbEntityV7Root",
        ):
            candidate = root.findChild(QObject, object_name)
            if candidate is not None:
                self._motion_item = candidate
                break
        return self._motion_item

    def _sync_orb_motion(self) -> None:
        window = self.window()
        low_power = os.environ.get("ONYX_ORB_LOW_POWER", "0").strip().casefold() in {
            "1",
            "true",
            "yes",
            "on",
        }
        self._motion.configure(
            state=self.projection.state,
            visible=self._loaded and self.isVisible(),
            minimized=bool(window and window.isMinimized()),
            reduced_motion=self.projection.reducedMotion,
            muted=self.projection.muted,
            low_power=low_power,
            audio_level=self.projection.audioLevel,
        )
        item = self._current_orb_motion_item()
        if not self._motion.running or item is None:
            self._motion_timer.stop()
            self._motion_last_frame_at = None
            if item is not None:
                item.setProperty("scale", 1.0)
                item.setProperty("rotation", 0.0)
            return
        frame = self._motion.next_frame()
        if frame is not None and (
            not self._motion_timer.isActive()
            or self._motion_timer.interval() != frame.interval_ms
        ):
            self._motion_last_frame_at = time.perf_counter()
            self._motion_timer.start(frame.interval_ms)

    def _advance_orb_motion(self) -> None:
        self._motion_callback_count += 1
        started = time.perf_counter()
        previous = self._motion_last_frame_at
        self._motion_last_frame_at = started
        frame = self._motion.next_frame()
        item = self._current_orb_motion_item()
        if frame is None or item is None:
            self._sync_orb_motion()
            return
        item.setProperty("scale", frame.scale)
        item.setProperty("rotation", frame.rotation)
        item.setProperty("phase", frame.phase)
        elapsed_ms = (
            (started - previous) * 1000.0
            if previous is not None
            else (time.perf_counter() - started) * 1000.0
        )
        changed = self._motion.report_frame(elapsed_ms)
        if changed or self._motion_timer.interval() != frame.interval_ms:
            self._sync_orb_motion()

    def orb_motion_stats(self) -> dict[str, int | bool]:
        """Return aggregate diagnostics without exposing renderer objects."""

        return {
            "callbacks": self._motion_callback_count,
            "active_timers": int(self._motion_timer.isActive()),
            "target_fps": self._motion.target_fps,
            "running": self._motion.running,
        }

    def sync_animation(self) -> None:
        projection = getattr(self, "projection", None)
        if projection is None:
            return
        window = self.window()
        projection.set_lifecycle(
            visible=self._loaded and self.isVisible(),
            minimized=bool(window and window.isMinimized()),
        )
        self._sync_orb_motion()

    def showEvent(self, event) -> None:
        super().showEvent(event)
        self.sync_animation()

    def hideEvent(self, event) -> None:
        projection = getattr(self, "projection", None)
        if projection is not None:
            projection.set_lifecycle(visible=False, minimized=False)
        self._motion_timer.stop()
        self._motion_last_frame_at = None
        super().hideEvent(event)


class DayOpsConnectionDialog(QDialog):
    """Trusted local Microsoft onboarding surface for the V19 host bridge."""

    _operation_done = pyqtSignal(str, object)
    _trusted_echo = pyqtSignal(str)

    def __init__(
        self,
        owner: "MainWindow",
        callbacks: dict[str, object],
        runtime_dispatch,
    ) -> None:
        super().__init__(owner)
        if set(callbacks) != {
            "status",
            "connect",
            "sign_in",
            "disconnect",
            "today_brief",
        } or not all(callable(value) for value in callbacks.values()):
            raise ValueError("exact DayOps callbacks are required")
        self._owner = owner
        self._callbacks = callbacks
        if not callable(runtime_dispatch):
            raise ValueError("runtime-owned DayOps dispatcher is required")
        self._runtime_dispatch = runtime_dispatch
        self._cancel = threading.Event()
        self._busy = False
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.setWindowTitle("Onyx DayOps — Microsoft connection")
        self.setModal(False)
        self.resize(680, 650)
        self.setStyleSheet(
            f"QDialog {{ background:{C.ONYX}; color:{C.SILVER}; }}"
            f"QLabel {{ color:{C.STEEL}; }}"
            f"QLineEdit, QTextEdit {{ background:{C.OBSIDIAN}; color:{C.SILVER}; "
            f"border:1px solid {C.GUNMETAL}; border-radius:6px; padding:7px; }}"
            f"QPushButton {{ background:{C.GRAPHITE}; color:{C.SILVER}; "
            f"border:1px solid {C.CORE_TEAL}; border-radius:7px; padding:8px 13px; }}"
            f"QPushButton:disabled {{ color:{C.GUNMETAL}; border-color:{C.GUNMETAL}; }}"
        )

        root = QVBoxLayout(self)
        heading = QLabel("MICROSOFT DAYOPS  /  READ-ONLY CONNECTION")
        heading.setStyleSheet(f"color:{C.TEAL_GLOW}; font-size:15px; font-weight:600;")
        root.addWidget(heading)
        explanation = QLabel(
            "Connect once to let Onyx read your calendar and important unread mail. "
            "Permissions are limited to Calendars.Read and Mail.Read. Tokens remain "
            "in the operating-system vault; the device code stays in this window."
        )
        explanation.setWordWrap(True)
        root.addWidget(explanation)

        form = QGridLayout()
        self._client_id = QLineEdit()
        self._client_id.setPlaceholderText(
            "Microsoft Entra public client application ID"
        )
        self._tenant_id = QLineEdit()
        self._tenant_id.setPlaceholderText(
            "Tenant ID, or common for a personal account"
        )
        self._account_id = QLineEdit()
        self._account_id.setPlaceholderText("Microsoft account email")
        self._iana_timezone = QLineEdit("America/New_York")
        self._outlook_timezone = QLineEdit("Eastern Standard Time")
        fields = (
            ("CLIENT ID", self._client_id),
            ("TENANT ID", self._tenant_id),
            ("ACCOUNT", self._account_id),
            ("LOCAL TIMEZONE", self._iana_timezone),
            ("OUTLOOK TIMEZONE", self._outlook_timezone),
        )
        for row, (label, widget) in enumerate(fields):
            form.addWidget(QLabel(label), row, 0)
            form.addWidget(widget, row, 1)
        form.setColumnStretch(1, 1)
        root.addLayout(form)

        self._status = QLabel("STATUS  /  CHECKING")
        self._status.setStyleSheet(f"color:{C.TEAL_GLOW};")
        root.addWidget(self._status)
        self._output = QTextEdit()
        self._output.setReadOnly(True)
        self._output.setPlaceholderText(
            "Microsoft will provide a verification URL and one-time code here."
        )
        root.addWidget(self._output, 1)

        actions = QHBoxLayout()
        self._connect_button = QPushButton("CONNECT MICROSOFT")
        self._today_button = QPushButton("TODAY BRIEF")
        self._refresh_button = QPushButton("REFRESH STATUS")
        self._disconnect_button = QPushButton("DISCONNECT")
        self._cancel_button = QPushButton("CANCEL SIGN-IN")
        self._close_button = QPushButton("CLOSE")
        for button in (
            self._connect_button,
            self._today_button,
            self._refresh_button,
            self._disconnect_button,
            self._cancel_button,
            self._close_button,
        ):
            actions.addWidget(button)
        root.addLayout(actions)

        self._connect_button.clicked.connect(self._connect)
        self._today_button.clicked.connect(self._today_brief)
        self._refresh_button.clicked.connect(self.refresh_status)
        self._disconnect_button.clicked.connect(self._disconnect)
        self._cancel_button.clicked.connect(self._cancel.set)
        self._close_button.clicked.connect(self.close)
        self._operation_done.connect(self._finish_operation)
        self._trusted_echo.connect(self._append_trusted_echo)
        self._set_busy(False)

    def _set_busy(self, busy: bool) -> None:
        self._busy = bool(busy)
        for button in (
            self._connect_button,
            self._today_button,
            self._refresh_button,
            self._disconnect_button,
        ):
            button.setEnabled(not self._busy)
        self._cancel_button.setEnabled(self._busy)
        self._close_button.setEnabled(not self._busy)

    @staticmethod
    def _public_result(value: object) -> dict[str, object]:
        if isinstance(value, dict):
            return dict(value)
        converter = getattr(value, "as_dict", None)
        if callable(converter):
            converted = converter()
            if isinstance(converted, dict):
                return dict(converted)
        return {"status": "completed"}

    def _start(self, operation: str, worker) -> None:
        if self._busy:
            return
        self._cancel.clear()
        self._set_busy(True)
        self._status.setText(f"STATUS  /  {operation.upper()} IN PROGRESS")

        def complete(result: object = None, error: BaseException | None = None) -> None:
            try:
                public = self._public_result(result)
            except Exception as exc:
                error = exc
                public = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
            if error is not None:
                public = {
                    "status": "failed",
                    "error_type": type(error).__name__,
                }
            self._operation_done.emit(operation, public)

        if not self._runtime_dispatch(f"dayops-{operation}", worker, complete):
            complete(error=RuntimeError("runtime is quiesced"))

    def _append_trusted_echo(self, value: str) -> None:
        clean = str(value).strip()[:500]
        if clean:
            self._output.append(clean)

    def _connect(self) -> None:
        payload = {
            "client_id": self._client_id.text().strip(),
            "tenant_id": self._tenant_id.text().strip(),
            "account_id": self._account_id.text().strip(),
            "iana_timezone": self._iana_timezone.text().strip(),
            "outlook_timezone": self._outlook_timezone.text().strip(),
        }
        if any(not value for value in payload.values()):
            self._status.setText("STATUS  /  ALL CONNECTION FIELDS ARE REQUIRED")
            return
        self._output.clear()

        def worker():
            prepared = self._public_result(self._callbacks["connect"](payload))
            if prepared.get("status") == "connected":
                return prepared
            return self._callbacks["sign_in"](
                self._trusted_echo.emit,
                self._cancel.is_set,
            )

        self._start("connect", worker)

    def refresh_status(self) -> None:
        self._start("status", self._callbacks["status"])

    def _today_brief(self) -> None:
        self._start("today brief", self._callbacks["today_brief"])

    def _disconnect(self) -> None:
        decision = QMessageBox.question(
            self,
            "Disconnect Microsoft?",
            "Remove the locally vaulted Microsoft session from Onyx?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if decision == QMessageBox.StandardButton.Yes:
            self._start("disconnect", self._callbacks["disconnect"])

    def _finish_operation(self, operation: str, result: object) -> None:
        payload = self._public_result(result)
        self._set_busy(False)
        status = str(payload.get("status", "completed"))[:80]
        error_type = str(payload.get("error_type", ""))[:100]
        self._status.setText(
            f"STATUS  /  {status.upper()}"
            + (f"  /  {error_type}" if error_type else "")
        )
        # Display only the controller's explicitly public result. Device codes
        # are emitted separately and are never copied into the Onyx log.
        rendered = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        self._output.append(
            _dayops_visible_render(rendered, limit=12_000, payload=payload)
        )
        if operation == "today brief" and status == "completed":
            projection = self._owner._v5_projection
            if projection is not None:
                projection.set_content(
                    "TODAY BRIEF",
                    _dayops_visible_render(rendered, limit=4_000, payload=payload),
                )


class MainWindow(QMainWindow):
    _log_sig = pyqtSignal(str)
    _state_sig = pyqtSignal(str)
    _audio_sig = pyqtSignal(float)  # live speech amplitude (0..1) → orb
    _content_sig = pyqtSignal(str, str)  # (title, text) — thread-safe content display
    _reconfig_sig = pyqtSignal()  # trigger setup overlay from any thread
    _camera_sig = pyqtSignal(bytes)  # show camera frame preview (small overlay)
    _cam_stream_sig = pyqtSignal(bool)  # True=start live stream, False=stop
    _cam_frame_sig = pyqtSignal(bytes)  # live camera frame → HUD area
    _cam_attention_sig = pyqtSignal(float, float, float)
    _cam_calibration_sig = pyqtSignal(str, float)
    _permission_sig = pyqtSignal(object, object, object)
    _shutdown_recovery_sig = pyqtSignal(str, object, object)
    _exit_sig = pyqtSignal(int)
    _background_sig = pyqtSignal()

    def changeEvent(self, event):
        super().changeEvent(event)
        if event.type() == QEvent.Type.WindowStateChange and hasattr(self, "hud"):
            self.hud.sync_animation()

    def event(self, event):
        # Intercept the native title-bar Close before activation wrappers reach
        # closeEvent. This preserves every live dispatcher while a packaged
        # resident window moves to the background.
        if (
            event.type() == QEvent.Type.Close
            and getattr(self, "_close_to_background", False)
            and not getattr(self, "_exit_requested", False)
        ):
            event.ignore()
            self._send_to_background()
            return True
        return super().event(event)

    def _show_permission_dialog(self, request: dict, done, result: list) -> None:
        """Display an approval request on the trusted local desktop UI thread."""
        try:
            # An approval the owner never sees is an approval that times out,
            # and a timeout is recorded as a refusal.  Surface the window before
            # prompting, exactly as the shutdown-recovery prompt already does.
            self.showNormal()
            self.show()
            self.raise_()
            self.activateWindow()
            summary = (
                request.get("summary") or "Execute the displayed development plan."
            )
            details = request.get("details")
            if details is None:
                details = {
                    key: value
                    for key, value in request.items()
                    if key not in {"digest", "summary"}
                }
            rendered = json.dumps(details, indent=2, ensure_ascii=False)
            dialog = QDialog(self)
            dialog.setWindowTitle("Onyx permission required")
            dialog.resize(820, 680)
            layout = QVBoxLayout(dialog)
            heading = QLabel(str(summary))
            heading.setWordWrap(True)
            layout.addWidget(heading)
            payload = QTextEdit()
            payload.setReadOnly(True)
            payload.setPlainText(
                f"Approval digest: {request.get('digest', '')}\n\n{rendered}"
            )
            layout.addWidget(payload, stretch=1)
            buttons = QDialogButtonBox(
                QDialogButtonBox.StandardButton.Yes | QDialogButtonBox.StandardButton.No
            )
            buttons.accepted.connect(dialog.accept)
            buttons.rejected.connect(dialog.reject)
            layout.addWidget(buttons)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                result.append(request.get("digest"))
        finally:
            done.set()

    @pyqtSlot(str, object, object)
    def _show_shutdown_recovery(self, message: str, retry, force_exit) -> None:
        """Offer recovery only on the trusted local desktop surface."""

        self.showNormal()
        self.show()
        self.raise_()
        self.activateWindow()
        dialog = QMessageBox(self)
        dialog.setWindowTitle("Onyx shutdown needs attention")
        dialog.setIcon(QMessageBox.Icon.Warning)
        dialog.setText("Onyx could not prove that every runtime component stopped.")
        dialog.setInformativeText(str(message))
        retry_button = dialog.addButton(
            "Retry Shutdown", QMessageBox.ButtonRole.AcceptRole
        )
        force_button = dialog.addButton(
            "Force Exit", QMessageBox.ButtonRole.DestructiveRole
        )
        dialog.addButton("Keep Onyx Open", QMessageBox.ButtonRole.RejectRole)
        dialog.exec()
        clicked = dialog.clickedButton()
        if clicked is retry_button and callable(retry):
            retry()
        elif clicked is force_button and callable(force_exit):
            confirmation = QMessageBox.question(
                self,
                "Force exit Onyx?",
                "Force exit may leave an external operation incomplete. Continue?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if confirmation == QMessageBox.StandardButton.Yes:
                force_exit()

    def __init__(self, face_path: str):
        super().__init__()
        self._face_path = face_path
        # A packaged assistant is a resident process. Closing its visible
        # window must not silently kill voice, automations, dashboard or
        # missions. Source/dev windows retain normal close behavior so test
        # cleanup and local development are not trapped in the background.
        self._close_to_background = _close_to_background_enabled()
        self._exit_requested = False
        self._background_notice_emitted = False
        self._tray_available = False
        self._exit_sig.connect(self._schedule_explicit_exit)
        self._shutdown_recovery_sig.connect(self._show_shutdown_recovery)
        self._hud_v5_requested = HUD_V5_LIVE
        self._hud_v5_live = False
        self._v5_log_connected = False
        self._v5_projection: _HudV5Projection | None = None
        self._v5_host: _CinematicHudV5Host | None = None
        self._v5_central: QWidget | None = None
        self._legacy_central: QWidget | None = None
        self._camera_attention = (0.0, 0.0, 0.0)
        self._camera_attention_last_at = 0.0
        self._camera_calibration_phase = "idle"
        self.setWindowTitle("Onyx — Cyryx Labs")
        self.setMinimumSize(_MIN_W, _MIN_H)
        self.resize(_DEFAULT_W, _DEFAULT_H)

        screen = QApplication.primaryScreen().availableGeometry()
        self.move(
            (screen.width() - _DEFAULT_W) // 2,
            (screen.height() - _DEFAULT_H) // 2,
        )

        self.on_text_command = None
        self.on_file_attachment = None  # host-only: raw path never reaches model
        self.on_remote_clicked = None  # callable: () -> (url, key) | None
        self.on_interrupt = None  # callable: () -> None — stop Onyx mid-speech
        self.on_exit_requested = None  # callable: (reason) -> bool — runtime-owned exit
        # V19 host-only DayOps callbacks. Public onboarding identifiers and
        # device-code instructions stay on this trusted local surface; they are
        # never appended to the model-visible transcript or general log.
        self.on_dayops_status = None
        self.on_dayops_connect = None
        self.on_dayops_sign_in = None
        self.on_dayops_disconnect = None
        self.on_dayops_today_brief = None
        # The live runtime owns every external UI worker.  UI code may submit
        # work, but never creates an anonymous daemon that can outlive cleanup.
        self.on_runtime_worker = None
        # V20 host-only, on-demand projections. These callbacks never poll and
        # never dispatch external work; the HUD invokes them only on owner action.
        self.on_advanced_status = None
        self.on_advanced_attention = None
        self._muted = False
        self._current_file: str | None = None
        self._remote_overlay: RemoteKeyOverlay | None = None
        self._dayops_dialog: DayOpsConnectionDialog | None = None

        central = QWidget()
        central.setStyleSheet(f"background: {C.ONYX};")
        self.setCentralWidget(central)

        root = QVBoxLayout(central)
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_header())

        self._left_panel = self._build_left_panel()

        # Full-bleed entity stage: the Orb is the environment, not a center column.
        self.hud = OrbHost(
            face_path,
            force_fallback=True if self._hud_v5_requested else None,
        )
        self.hud.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_panel = self._build_content_panel()

        # Live camera container — replaces HUD when camera stream is active
        _cam_cont = QWidget()
        self._cam_container = _cam_cont
        _cam_cont.setStyleSheet(f"background: {C.ONYX};")
        _cam_v = QVBoxLayout(_cam_cont)
        _cam_v.setContentsMargins(0, 0, 0, 0)
        _cam_v.setSpacing(0)
        _cam_hdr = QHBoxLayout()
        _cam_hdr.setContentsMargins(8, 5, 8, 5)
        _cam_title = QLabel("◈  CAMERA FEED")
        _cam_title.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        _cam_title.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        _cam_hdr.addWidget(_cam_title)
        _cam_hdr.addStretch()
        _cam_x = QPushButton("✕  CLOSE")
        _cam_x.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        _cam_x.setCursor(Qt.CursorShape.PointingHandCursor)
        _cam_x.setStyleSheet(f"""
            QPushButton {{
                color: {C.TEXT_DIM}; background: transparent;
                border: none; padding: 2px 6px;
            }}
            QPushButton:hover {{ color: {C.PRI}; }}
        """)
        _cam_x.clicked.connect(self.stop_camera_stream)
        _cam_hdr.addWidget(_cam_x)
        _cam_v.addLayout(_cam_hdr)
        self._cam_live_lbl = QLabel()
        self._cam_live_lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._cam_live_lbl.setStyleSheet("background: transparent;")
        self._cam_live_lbl.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        _cam_v.addWidget(self._cam_live_lbl, stretch=1)

        # Stack: 0 = animated HUD, 1 = live camera
        self._hud_cam_stack = QStackedWidget()
        self._hud_cam_stack.addWidget(self.hud)
        self._hud_cam_stack.addWidget(_cam_cont)

        self._center_split = QSplitter(Qt.Orientation.Vertical)
        self._center_split.setStyleSheet(f"""
            QSplitter {{
                background: #050607;
                border: none;
            }}
            QSplitter::handle {{
                background: #1B2227;
                height: 4px;
            }}
            QSplitter::handle:hover {{
                background: {C.PRI_DIM};
            }}
        """)
        self._center_split.addWidget(self._hud_cam_stack)
        self._center_split.addWidget(self._content_panel)
        self._center_split.setStretchFactor(0, 3)
        self._center_split.setStretchFactor(1, 1)
        self._center_split.setCollapsible(0, False)

        self._right_panel = self._build_activity_panel()
        self._command_dock = self._build_command_dock()

        scene = QWidget()
        scene.setObjectName("EntityStage")
        scene.setStyleSheet(
            f"QWidget#EntityStage {{ background: {C.ONYX}; border: none; }}"
        )
        stage = QStackedLayout(scene)
        stage.setContentsMargins(0, 0, 0, 0)
        stage.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stage.addWidget(self._center_split)

        self._entity_hud_overlay = EntityHudOverlay()
        stage.addWidget(self._entity_hud_overlay)

        controls = QWidget()
        controls.setObjectName("EntityControls")
        controls.setStyleSheet("QWidget#EntityControls { background: transparent; }")
        projection = QGridLayout(controls)
        projection.setContentsMargins(20, 10, 20, 10)
        projection.setHorizontalSpacing(18)
        projection.setVerticalSpacing(8)
        projection.setColumnStretch(1, 1)
        projection.setRowStretch(0, 1)
        projection.addWidget(
            self._left_panel,
            0,
            0,
            alignment=Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignTop,
        )
        projection.addWidget(
            self._right_panel,
            0,
            2,
            alignment=Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignTop,
        )
        projection.addWidget(
            self._command_dock,
            1,
            0,
            1,
            3,
            alignment=Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignBottom,
        )
        stage.addWidget(controls)
        stage.setCurrentWidget(controls)
        self._entity_hud_overlay.raise_()
        controls.raise_()

        root.addWidget(scene, stretch=1)
        root.addWidget(self._build_footer())

        self._clock_tmr = QTimer(self)
        self._clock_tmr.timeout.connect(self._tick_clock)
        self._clock_tmr.start(1000)
        self._tick_clock()

        # Metrik güncelleme timer'ı
        _metrics.start()
        QApplication.instance().aboutToQuit.connect(_metrics.shutdown)
        self._metric_tmr = QTimer(self)
        self._metric_tmr.timeout.connect(self._update_metrics)
        self._metric_tmr.start(2000)
        self._update_metrics()

        self._log_sig.connect(self._log.append_log)
        self._state_sig.connect(self._apply_state)
        self._audio_sig.connect(self._apply_audio_level)
        self._content_sig.connect(self._show_content)
        self._reconfig_sig.connect(self._show_setup)
        self._camera_sig.connect(self._show_camera_frame)
        self._cam_stream_sig.connect(self._on_cam_stream)
        self._cam_frame_sig.connect(self._on_cam_frame)
        self._cam_attention_sig.connect(self._on_cam_attention)
        self._cam_calibration_sig.connect(self._on_cam_calibration)
        self._permission_sig.connect(self._show_permission_dialog)
        self._cam_stop = threading.Event()

        if self._hud_v5_requested:
            try:
                self._activate_v5_shell()
            except Exception as exc:
                self._hud_v5_live = False
                self._log.append_log(
                    f"SYS: Cinematic HUD unavailable; legacy UI restored ({type(exc).__name__})."
                )

        # Camera preview overlay (child of central widget, positioned in resizeEvent)
        self._cam_preview = _CameraPreview(self.centralWidget())

        # QCursor polling is deliberate: the QQuickWidget sits behind native
        # controls, so local WebEngine pointer events cannot cover the complete
        # window. This single UI-thread timer observes the owner window without
        # adding a renderer loop or intercepting button/input events.
        self._attention_tmr = QTimer(self)
        self._attention_tmr.setTimerType(Qt.TimerType.PreciseTimer)
        self._attention_tmr.timeout.connect(self._sync_visual_attention)
        # QWebEngine JavaScript crosses a process boundary. Twenty host samples
        # per second, followed by QML coalescing, keeps tracking responsive
        # without flooding the renderer with unchanged IPC calls.
        self._attention_tmr.start(50)

        self._overlay: SetupOverlay | None = None
        self._setup_open_pending = False
        self._ready = self._check_config()
        if not self._ready:
            self._show_setup()

        sc_mute = QShortcut(QKeySequence("F4"), self)
        sc_mute.activated.connect(self._toggle_mute)
        sc_full = QShortcut(QKeySequence("F11"), self)
        sc_full.activated.connect(self._toggle_fullscreen)
        sc_intr = QShortcut(QKeySequence("Escape"), self)
        sc_intr.activated.connect(self._do_interrupt)

    def _configured_owner_name(self) -> str:
        try:
            data = json.loads(API_FILE.read_text(encoding="utf-8"))
            value = " ".join(str(data.get("owner_name", "")).split())[:80]
            return value or "Sir"
        except Exception:
            return "Sir"

    def _activate_v5_shell(self) -> None:
        """Atomically select the sole QML renderer while retaining software fallback."""
        if self._hud_v5_live:
            return
        legacy_central = self.centralWidget()
        legacy_stack = self._hud_cam_stack
        legacy_hud = self.hud

        if self._v5_host is None:
            try:
                host = _CinematicHudV5Host(self, self._configured_owner_name())
            except Exception:
                raise
            live_central = QWidget()
            live_central.setObjectName("OnyxCinematicSurfaceV5")
            live_central.setStyleSheet(f"background: {C.ONYX}; border: none;")
            live_layout = QVBoxLayout(live_central)
            live_layout.setContentsMargins(0, 0, 0, 0)
            live_layout.setSpacing(0)
            live_stack = QStackedWidget()
            live_stack.addWidget(host)
            live_layout.addWidget(live_stack)
            self._v5_host = host
            self._v5_central = live_central
            self._v5_cam_stack = live_stack
            host.rendererFailed.connect(self._on_v5_renderer_failed)
        else:
            host = self._v5_host
            live_central = self._v5_central
            live_stack = self._v5_cam_stack
            host.load_source()

        if live_central is None:
            raise RuntimeError("cinematic central widget is unavailable")
        projection = host.projection
        legacy_stack.removeWidget(self._cam_container)
        if live_stack.indexOf(self._cam_container) < 0:
            live_stack.addWidget(self._cam_container)
        live_stack.setCurrentWidget(host)

        detached = self.takeCentralWidget()
        if detached is not legacy_central:
            raise RuntimeError("legacy central widget changed during activation")
        legacy_central.setParent(self)
        legacy_central.hide()
        self.setCentralWidget(live_central)

        self._legacy_central = legacy_central
        self._legacy_hud = legacy_hud
        self._legacy_cam_stack = legacy_stack
        self._hud_cam_stack = live_stack
        self.hud = host
        self._v5_projection = projection
        self._hud_v5_live = True
        legacy_hud.sync_animation()
        projection.set_muted(self._muted)
        projection.set_operational_state(
            "LISTENING" if self._check_config() else "INITIALISING"
        )
        projection.append_log("SYSTEM  /  CINEMATIC HUD V5 ONLINE")
        self._log_sig.connect(projection.append_log)
        self._v5_log_connected = True

    def _on_v5_renderer_failed(self, message: str) -> None:
        QTimer.singleShot(0, lambda: self._restore_legacy_shell(message))

    def _restore_legacy_shell(self, reason: str = "renderer failure") -> None:
        """One-way fail-safe used for any live QML or scene-graph failure."""
        if not self._hud_v5_live or self._legacy_central is None:
            return
        projection = self._v5_projection
        state = projection.state if projection is not None else "ERROR"
        if self._v5_host is not None:
            self._v5_host.suspend()
        if projection is not None and self._v5_log_connected:
            try:
                self._log_sig.disconnect(projection.append_log)
            except (RuntimeError, TypeError):
                pass
            self._v5_log_connected = False
        live_central = self.takeCentralWidget()
        self._hud_cam_stack.removeWidget(self._cam_container)
        self._legacy_cam_stack.addWidget(self._cam_container)
        self._legacy_cam_stack.setCurrentIndex(0)
        self.setCentralWidget(self._legacy_central)
        self._legacy_central.show()
        self.hud = self._legacy_hud
        self._hud_cam_stack = self._legacy_cam_stack
        self._hud_v5_live = False
        self.hud.set_operational_state(state)
        self.hud.set_muted(self._muted)
        self.hud.sync_animation()
        if hasattr(self, "_cam_preview"):
            self._cam_preview.setParent(self.centralWidget())
        if live_central is not None:
            live_central.setParent(self)
            live_central.hide()
        self._log.append_log(
            f"SYS: Cinematic HUD stopped; legacy UI restored ({str(reason)[:120]})."
        )
        self._v5_projection = None

    def _submit_v5_command(self, text: str) -> bool:
        callback = self.on_text_command
        if callback is None:
            return False
        self._log.append_log(f"You: {text}")
        if self._v5_projection is not None:
            self._v5_projection.append_log(f"YOU  /  {text}")
        dispatcher = self.on_runtime_worker
        if not callable(dispatcher):
            return False
        return bool(dispatcher("text-command-v5", lambda: callback(text), None))

    def _set_v5_muted(self, requested: bool) -> bool:
        requested = bool(requested)
        if requested != self._muted:
            self._toggle_mute()
        return self._muted == requested

    def _request_v5_file(self) -> bool:
        path, _ = QFileDialog.getOpenFileName(
            self, "Select a file for Onyx", str(Path.home()), "All files (*)"
        )
        return self._accept_v5_file(path) if path else False

    def _accept_v5_file(self, path: str) -> bool:
        candidate = Path(str(path)).expanduser()
        if not candidate.is_file():
            return False
        self._on_file_selected(str(candidate.resolve()))
        return True

    def _request_v5_interrupt(self) -> bool:
        if self.on_interrupt is None:
            return False
        self._do_interrupt()
        return True

    def _request_v5_autonomy(self) -> bool:
        previous = self._autonomy_enabled
        self._toggle_owner_autonomy()
        if self._v5_projection is not None:
            self._v5_projection.set_autonomy_enabled(self._autonomy_enabled)
        return self._autonomy_enabled != previous

    def _request_v5_remote(self) -> bool:
        if self.on_remote_clicked is None:
            return False
        self._open_remote()
        return True

    def _request_v5_fullscreen(self) -> bool:
        self._toggle_fullscreen()
        return True

    def _request_v5_setup(self) -> bool:
        # A QML mouse callback is still executing while this slot runs. Creating
        # a QWidget child synchronously at that point re-enters QQuickWidget's
        # native event path and can fail-fast inside Qt6Core on packaged Windows
        # builds. Queue the unchanged setup overlay for the next UI-loop turn.
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.raise_()
            return True
        if self._setup_open_pending:
            return True
        self._setup_open_pending = True
        QTimer.singleShot(0, self._show_setup)
        return True

    def _request_v5_dayops(self) -> bool:
        callbacks = {
            "status": self.on_dayops_status,
            "connect": self.on_dayops_connect,
            "sign_in": self.on_dayops_sign_in,
            "disconnect": self.on_dayops_disconnect,
            "today_brief": self.on_dayops_today_brief,
        }
        if not all(callable(value) for value in callbacks.values()):
            if self._v5_projection is not None:
                self._v5_projection.set_content(
                    "DAYOPS CONNECTION",
                    "Microsoft calendar and mail onboarding is unavailable in this runtime.",
                )
            return False
        if self._dayops_dialog is None:
            self._dayops_dialog = DayOpsConnectionDialog(
                self, callbacks, self.on_runtime_worker
            )
            self._dayops_dialog.finished.connect(self._forget_dayops_dialog)
        self._dayops_dialog.show()
        self._dayops_dialog.raise_()
        self._dayops_dialog.activateWindow()
        self._dayops_dialog.refresh_status()
        return True

    def _request_v5_advanced_operations(self) -> bool:
        projection = self._v5_projection
        if projection is None:
            return False
        if not callable(self.on_advanced_status) or not callable(
            self.on_advanced_attention
        ):
            projection.set_content(
                "ADVANCED OPERATIONS",
                "Operational goals and attention are unavailable in this runtime.",
            )
            return False
        try:
            status = self.on_advanced_status()
            attention = self.on_advanced_attention()
            if not isinstance(status, dict) or not isinstance(attention, dict):
                raise TypeError("advanced operations projection contract drifted")
            rendered = _advanced_operations_visible_render(status, attention)
        except Exception as exc:
            projection.set_content(
                "ADVANCED OPERATIONS",
                f"Projection failed closed ({type(exc).__name__}).",
            )
            return False
        projection.set_content("ADVANCED OPERATIONS", rendered)
        return True

    def _forget_dayops_dialog(self, _result: int) -> None:
        self._dayops_dialog = None

    def _request_v5_history(self) -> bool:
        if self._v5_projection is None:
            return False
        self._v5_projection.set_content("SESSION ACTIVITY", self._v5_projection.historyText)
        return True

    def _request_v5_permissions(self) -> bool:
        if self._v5_projection is None:
            return False
        self._v5_projection.set_content(
            "PERMISSION CONTROL",
            "Sensitive and high-consequence actions remain governed. "
            "When a decision is required, Onyx opens the trusted local approval surface.",
        )
        return True

    def _request_v5_camera(self) -> bool:
        if self._v5_projection is not None and self._v5_projection.cameraActive:
            self.stop_camera_stream()
        else:
            self.start_camera_stream()
        return True

    def _show_camera_frame(self, img_bytes: bytes):
        """Slot — display camera preview overlay (main thread)."""
        self._cam_preview.show_frame(img_bytes)
        cw = self.centralWidget()
        pw = _CameraPreview._W
        ph = self._cam_preview.height()
        self._cam_preview.setGeometry(
            cw.width() - _RIGHT_W - pw - 12,
            cw.height() - ph - 28,
            pw,
            ph,
        )

    # --- Live camera stream in HUD area ------------------------------------
    def _on_cam_stream(self, start: bool) -> None:
        if self._v5_projection is not None:
            self._v5_projection.set_camera_active(start)
        if self._hud_v5_live and self._v5_host is not None:
            # Keep the humanoid visible so camera gestures can visibly direct
            # its attention. The existing feed remains available as the small
            # trusted local preview instead of replacing the entity.
            self._hud_cam_stack.setCurrentWidget(self._v5_host)
            if not start:
                self._cam_preview.hide()
                self._camera_attention_last_at = 0.0
            return
        if start:
            self._hud_cam_stack.setCurrentIndex(1)
        else:
            self._hud_cam_stack.setCurrentIndex(0)
            self._cam_live_lbl.clear()

    def _on_cam_frame(self, data: bytes) -> None:
        if self._hud_v5_live:
            self._cam_preview.show_frame(data)
            return
        px = QPixmap()
        px.loadFromData(data)
        if not px.isNull():
            w, h = self._cam_live_lbl.width(), self._cam_live_lbl.height()
            if w > 1 and h > 1:
                self._cam_live_lbl.setPixmap(
                    px.scaled(
                        w,
                        h,
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                )

    def _on_cam_attention(self, x: float, y: float, confidence: float) -> None:
        confidence = max(0.0, min(1.0, float(confidence)))
        if confidence < 0.12:
            return
        self._camera_attention = (
            max(-1.0, min(1.0, float(x))),
            max(-1.0, min(1.0, float(y))),
            confidence,
        )
        self._camera_attention_last_at = time.monotonic()
        self._set_visual_attention(
            self._camera_attention[0], self._camera_attention[1], "camera"
        )

    def _on_cam_calibration(self, phase: str, progress: float) -> None:
        phase = str(phase).strip().lower()
        if phase == self._camera_calibration_phase:
            return
        self._camera_calibration_phase = phase
        messages = {
            "background": "CAMERA: calibration started; keep the scene still briefly.",
            "gesture": "CAMERA: move one hand across the preview to calibrate attention.",
            "ready": "CAMERA: hand-attention calibration ready for this session.",
            "unavailable": "CAMERA: calibration unavailable; camera could not be opened.",
        }
        message = messages.get(phase)
        if message:
            bounded = max(0.0, min(1.0, float(progress)))
            self._log_sig.emit(message + f" ({bounded:.0%})")

    def _set_visual_attention(self, x: float, y: float, source: str) -> bool:
        host = self._v5_host
        if not self._hud_v5_live or host is None:
            return False
        return host.set_visual_attention(x, y, source)

    def _sync_visual_attention(self) -> None:
        projection = self._v5_projection
        camera_is_live = bool(projection is not None and projection.cameraActive)
        if camera_is_live and time.monotonic() - self._camera_attention_last_at < 0.55:
            x, y, _confidence = self._camera_attention
            self._set_visual_attention(x, y, "camera")
            return

        local = self.mapFromGlobal(QCursor.pos())
        width, height = self.width(), self.height()
        if width < 2 or height < 2 or not self.rect().contains(local):
            self._set_visual_attention(0.0, 0.0, "pointer")
            return
        x = max(-1.0, min(1.0, (local.x() / width - 0.5) * 2.0))
        y = max(-1.0, min(1.0, (0.5 - local.y() / height) * 2.0))
        self._set_visual_attention(x, y, "pointer")

    def start_camera_stream(self) -> None:
        self._cam_stop.clear()
        self._cam_stream_sig.emit(True)
        t = threading.Thread(target=self._cam_loop, daemon=True, name="cam-stream")
        t.start()

    def _cam_loop(self) -> None:
        try:
            import cv2

            attention = CameraGestureAttentionTrackerV1()
            last_calibration_phase = ""

            # Reuse camera index detected by screen_processor (cached in api_keys.json)
            cam_idx = 0
            try:
                import json as _j

                cfg = _j.loads((CONFIG_DIR / "api_keys.json").read_text())
                cam_idx = int(cfg.get("camera_index", 0))
            except Exception:
                pass
            try:
                backend = cv2.CAP_DSHOW if _OS == "Windows" else cv2.CAP_ANY
            except AttributeError:
                backend = 0
            cap = cv2.VideoCapture(cam_idx, backend)
            if not cap.isOpened():
                cap = cv2.VideoCapture(0)
            if not cap.isOpened():
                self._cam_calibration_sig.emit("unavailable", 0.0)
                return
            # warm-up frames
            for _ in range(5):
                cap.read()
            while not self._cam_stop.wait(0.033) and cap.isOpened():
                ret, frame = cap.read()
                if ret and frame is not None:
                    observation = attention.update(frame)
                    calibration_phase = attention.calibration_phase
                    if calibration_phase != last_calibration_phase:
                        last_calibration_phase = calibration_phase
                        self._cam_calibration_sig.emit(
                            calibration_phase,
                            attention.calibration_progress,
                        )
                    if observation is not None:
                        self._cam_attention_sig.emit(
                            observation.x,
                            observation.y,
                            observation.confidence,
                        )
                    _, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 65])
                    self._cam_frame_sig.emit(buf.tobytes())
            cap.release()
        except Exception as e:
            print(f"[Camera] Stream error: {e}")
        finally:
            self._cam_stream_sig.emit(False)

    def stop_camera_stream(self) -> None:
        self._cam_stop.set()

    # ------------------------------------------------------------------
    # Icon generation — Cyryx neural Orb, rendered with Pillow
    # ------------------------------------------------------------------
    @staticmethod
    def _build_onyx_icon(out_path: Path) -> bool:
        """
        Render an Onyx neural Orb icon at 4x resolution and downsample
        for crisp results at all sizes. Saves a multi-res .ico to out_path.
        Returns True on success.
        """
        try:
            import math
            import PIL.Image
            import PIL.ImageDraw
            import PIL.ImageFilter
        except ImportError:
            return False

        CYAN = (0, 212, 255)
        DIM = (0, 100, 140)
        DARK = (0, 6, 10)
        GLOW = (0, 160, 200)
        WHITE = (220, 240, 255)

        def _render(sz: int) -> PIL.Image.Image:
            # Cyryx neural particle Orb. The older renderer below is retained
            # only as unreachable migration history for frozen bundles.
            S = sz * 4
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2
            radius = S // 2 - 3
            d.ellipse(
                [cx - radius, cy - radius, cx + radius, cy + radius],
                fill=(2, 4, 11, 255),
            )
            glow = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow)
            shell = int(radius * 0.72)
            gd.ellipse(
                [cx - shell, cy - shell, cx + shell, cy + shell], fill=(0, 190, 255, 78)
            )
            glow = glow.filter(PIL.ImageFilter.GaussianBlur(max(2, S // 11)))
            img = PIL.Image.alpha_composite(img, glow)
            d = PIL.ImageDraw.Draw(img)
            rng = random.Random(481)
            for _ in range(max(100, sz * 4)):
                angle = rng.random() * math.tau
                r = shell * math.sqrt(rng.random())
                x, y = cx + math.cos(angle) * r, cy + math.sin(angle) * r
                dot = max(1, int(S / 190 * rng.uniform(0.6, 1.7)))
                alpha = int(70 + 180 * (r / shell))
                d.ellipse(
                    [x - dot, y - dot, x + dot, y + dot], fill=(36, 216, 255, alpha)
                )
            for ox, oy, scale in [
                (-0.16, -0.10, 0.095),
                (0.14, -0.02, 0.075),
                (-0.01, 0.18, 0.065),
            ]:
                ncx, ncy, nr = cx + ox * radius, cy + oy * radius, scale * radius
                node = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
                nd = PIL.ImageDraw.Draw(node)
                nd.ellipse(
                    [ncx - nr * 2.5, ncy - nr * 2.5, ncx + nr * 2.5, ncy + nr * 2.5],
                    fill=(32, 234, 255, 140),
                )
                node = node.filter(PIL.ImageFilter.GaussianBlur(max(1, S // 40)))
                img = PIL.Image.alpha_composite(img, node)
                d = PIL.ImageDraw.Draw(img)
                d.ellipse(
                    [
                        ncx - nr * 0.42,
                        ncy - nr * 0.42,
                        ncx + nr * 0.42,
                        ncy + nr * 0.42,
                    ],
                    fill=(220, 250, 255, 255),
                )
            return img.resize((sz, sz), PIL.Image.LANCZOS)

            S = sz * 4  # draw at 4× then downscale
            img = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            d = PIL.ImageDraw.Draw(img)
            cx = cy = S // 2

            # ── filled background circle ──────────────────────────────────
            R = S // 2 - 2
            d.ellipse([cx - R, cy - R, cx + R, cy + R], fill=(*DARK, 255))

            # ── outer border ring ─────────────────────────────────────────
            lw = max(2, S // 40)
            d.ellipse([cx - R, cy - R, cx + R, cy + R], outline=(*CYAN, 220), width=lw)

            # ── mid decorative ring ───────────────────────────────────────
            R2 = int(R * 0.72)
            d.ellipse(
                [cx - R2, cy - R2, cx + R2, cy + R2],
                outline=(*DIM, 180),
                width=max(1, lw // 2),
            )

            # ── 6 radial spokes (hex bolt) ────────────────────────────────
            R_inner = int(R * 0.30)
            R_outer = int(R * 0.62)
            spoke_w = max(1, S // 80)
            for i in range(6):
                angle = math.radians(i * 60 - 30)
                x1 = cx + int(R_inner * math.cos(angle))
                y1 = cy + int(R_inner * math.sin(angle))
                x2 = cx + int(R_outer * math.cos(angle))
                y2 = cy + int(R_outer * math.sin(angle))
                d.line([x1, y1, x2, y2], fill=(*GLOW, 200), width=spoke_w)

            # ── 6 tick marks on outer ring ────────────────────────────────
            for i in range(6):
                angle = math.radians(i * 60)
                for dr in range(lw * 2):
                    rx = R - lw - dr
                    d.point(
                        [
                            cx + int(rx * math.cos(angle)),
                            cy + int(rx * math.sin(angle)),
                        ],
                        fill=(*WHITE, 220),
                    )

            # ── inner glowing ring ────────────────────────────────────────
            Ri = int(R * 0.26)
            d.ellipse(
                [cx - Ri, cy - Ri, cx + Ri, cy + Ri],
                outline=(*CYAN, 255),
                width=max(2, lw),
            )

            # ── bright glow soft blur applied before core ─────────────────
            # (draw a slightly larger cyan circle on a separate layer)
            glow_layer = PIL.Image.new("RGBA", (S, S), (0, 0, 0, 0))
            gd = PIL.ImageDraw.Draw(glow_layer)
            Rc = int(R * 0.13)
            gd.ellipse(
                [cx - Rc * 2, cy - Rc * 2, cx + Rc * 2, cy + Rc * 2], fill=(*CYAN, 110)
            )
            glow_layer = glow_layer.filter(PIL.ImageFilter.GaussianBlur(S // 14))
            img = PIL.Image.alpha_composite(img, glow_layer)
            d = PIL.ImageDraw.Draw(img)

            # ── core dot ──────────────────────────────────────────────────
            d.ellipse([cx - Rc, cy - Rc, cx + Rc, cy + Rc], fill=(*WHITE, 255))

            # ── downscale to target size ──────────────────────────────────
            return img.resize((sz, sz), PIL.Image.LANCZOS)

        try:
            official_master = _application_icon_path()
            if official_master is not None:
                with PIL.Image.open(official_master) as opened:
                    source = opened.convert("RGBA")
                sizes = [256, 128, 64, 48, 32, 24, 16]
                frames = [
                    source.resize((size, size), PIL.Image.Resampling.LANCZOS)
                    for size in sizes
                ]
                frames[0].save(
                    out_path,
                    format="ICO",
                    append_images=frames[1:],
                    sizes=[(size, size) for size in sizes],
                )
                return True

            sizes = [256, 128, 64, 48, 32, 16]
            frames = [_render(s) for s in sizes]
            frames[0].save(
                out_path,
                format="ICO",
                append_images=frames[1:],
                sizes=[(s, s) for s in sizes],
            )
            return True
        except Exception as e:
            print(f"[Shortcut] ⚠️  Icon generation failed: {e}")
            return False

    @staticmethod
    def _create_lnk_windows(
        lnk: str, target: str, args: str, work_dir: str, icon_loc: str
    ) -> None:
        """
        Create a Windows .lnk shortcut WITHOUT launching PowerShell or cmd.
        Tries win32com (pywin32) first; falls back to wscript.exe + VBScript.
        wscript.exe is a GUI-mode host — it never opens a console window.
        """
        # A frozen Onyx shortcut has no arguments.  Writing a quoted empty
        # value stores two literal quote characters in the .lnk and some
        # PyInstaller/Explorer paths forward those characters as a real argv
        # token.  Quote only a non-empty source launcher path.
        argument_value = f'"{args}"' if args else ""
        # ── Option 1: pywin32 (pure Python COM, zero subprocess) ──────────
        try:
            from win32com.client import Dispatch  # type: ignore

            sh = Dispatch("WScript.Shell")
            sc = sh.CreateShortCut(lnk)
            sc.TargetPath = target
            sc.Arguments = argument_value
            sc.WorkingDirectory = work_dir
            sc.Description = "Onyx AI Assistant"
            sc.IconLocation = icon_loc
            sc.save()
            # WScript's COM proxy can keep the link open until released,
            # preventing the property store from assigning its taskbar ID.
            del sc
            del sh
            import gc

            gc.collect()
            _set_windows_shortcut_app_id(lnk)
            return
        except ImportError:
            pass

        # ── Option 2: wscript.exe + VBScript (always available on Windows,
        #    GUI-mode executable — never opens a console window) ────────────
        vbs_argument_value = argument_value.replace('"', '""')
        vbs = "\n".join(
            [
                'Set ws = CreateObject("WScript.Shell")',
                f'Set sc = ws.CreateShortcut("{lnk}")',
                f'sc.TargetPath = "{target}"',
                f'sc.Arguments = "{vbs_argument_value}"',
                f'sc.WorkingDirectory = "{work_dir}"',
                'sc.Description = "Onyx AI Assistant"',
                f'sc.IconLocation = "{icon_loc}"',
                "sc.Save",
            ]
        )
        import tempfile

        fd, tmp = tempfile.mkstemp(suffix=".vbs")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(vbs)
            proc = subprocess.Popen(
                ["wscript.exe", "/nologo", tmp],
                creationflags=subprocess.DETACHED_PROCESS | subprocess.CREATE_NO_WINDOW,
            )
            proc.wait(timeout=10)
            _set_windows_shortcut_app_id(lnk)
        finally:
            try:
                os.unlink(tmp)
            except Exception:
                pass

    def _desktop_path(self, current_os: str) -> Path:
        """Resolve the active Windows Desktop, with an explicit safe fallback."""
        fallback = Path.home() / "Desktop"
        if current_os != "Windows":
            return fallback
        try:
            from win32com.client import Dispatch  # type: ignore

            shell = Dispatch("WScript.Shell")
            resolved = shell.SpecialFolders("Desktop")
            if not resolved:
                raise RuntimeError("WScript.Shell returned an empty Desktop path")
            return Path(str(resolved))
        except Exception as exc:
            self._log.append_log(
                "WARN: Active Windows Desktop resolution failed; "
                f"using fallback {fallback}: {exc}"
            )
            return fallback

    def _create_desktop_shortcut(self):
        """
        Create a desktop shortcut on Windows / macOS / Linux.
        Never opens a terminal, console, or PowerShell window on any platform.
        """
        import stat as _stat

        script = Path(__file__).resolve().parent / "main.py"
        python = Path(sys.executable)
        current_os = platform.system()
        desktop = self._desktop_path(current_os)

        if is_frozen():
            try:
                desktop.mkdir(parents=True, exist_ok=True)
                if current_os == "Windows":
                    lnk = str(desktop / "Onyx.lnk")
                    self._create_lnk_windows(
                        lnk, str(python), "", str(python.parent), f"{python},0"
                    )
                elif current_os == "Darwin":
                    app_bundle = python.resolve().parents[2]
                    alias = desktop / "Onyx.app"
                    if not alias.exists():
                        os.symlink(app_bundle, alias, target_is_directory=True)
                else:
                    icon = BASE_DIR / "assets" / "onyx.png"
                    icon_line = f"Icon={icon}\n" if icon.is_file() else "Icon=onyx\n"
                    desk = desktop / "Onyx.desktop"
                    desk.write_text(
                        "[Desktop Entry]\n"
                        "Name=Onyx\n"
                        f"Exec={python}\n"
                        "Type=Application\n"
                        "Terminal=false\n"
                        "Categories=Utility;Office;\n" + icon_line,
                        encoding="utf-8",
                    )
                    desk.chmod(desk.stat().st_mode | 0o755)
                self._log.append_log("SYS: Desktop shortcut created.")
            except Exception as exc:
                self._log.append_log(f"ERR: Shortcut failed — {exc}")
            return

        # Cyryx neural Orb icon (.ico — also exported as .png for Linux/macOS)
        ico_path = Path(__file__).resolve().parent / "config" / "onyx.ico"
        if not ico_path.exists():
            self._build_onyx_icon(ico_path)

        try:
            _os = current_os

            # ── Windows ───────────────────────────────────────────────────────
            if _os == "Windows":
                project_dir = Path(__file__).resolve().parent
                target = str(project_dir / ".venv" / "Scripts" / "pythonw.exe")
                launcher = project_dir / "scripts" / "launch_onyx.pyw"
                lnk = str(desktop / "Onyx.lnk")
                self._create_lnk_windows(
                    lnk,
                    target,
                    str(launcher),
                    str(project_dir),
                    str(ico_path),
                )

            # ── macOS — proper .app bundle (no Terminal window) ───────────────
            elif _os == "Darwin":
                app = desktop / "Onyx.app"
                mac_dir = app / "Contents" / "MacOS"
                res_dir = app / "Contents" / "Resources"
                mac_dir.mkdir(parents=True, exist_ok=True)
                res_dir.mkdir(exist_ok=True)

                # Launcher executable (bash — runs as background process,
                # macOS does NOT open Terminal for executables inside .app bundles)
                launcher = mac_dir / "Onyx"
                launcher.write_text(
                    "#!/usr/bin/env bash\n"
                    f'cd "{script.parent}"\n'
                    f'exec "{python}" "{script}"\n'
                )
                launcher.chmod(
                    launcher.stat().st_mode
                    | _stat.S_IEXEC
                    | _stat.S_IXGRP
                    | _stat.S_IXOTH
                )

                # Minimal Info.plist (required for .app recognition)
                (app / "Contents" / "Info.plist").write_text(
                    '<?xml version="1.0" encoding="UTF-8"?>\n'
                    '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
                    '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
                    '<plist version="1.0"><dict>\n'
                    "  <key>CFBundleExecutable</key><string>Onyx</string>\n"
                    "  <key>CFBundleIdentifier</key>"
                    "<string>com.onyx.assistant</string>\n"
                    "  <key>CFBundleName</key><string>Onyx</string>\n"
                    "  <key>CFBundlePackageType</key><string>APPL</string>\n"
                    "  <key>CFBundleVersion</key><string>1.0</string>\n"
                    "</dict></plist>\n"
                )

                # Optional: copy icon as .icns (skip silently if Pillow is missing)
                try:
                    import PIL.Image

                    icns = res_dir / "AppIcon.icns"
                    PIL.Image.open(ico_path).save(icns, format="ICNS")
                    # Inject icon reference into plist
                    plist = app / "Contents" / "Info.plist"
                    txt = plist.read_text()
                    plist.write_text(
                        txt.replace(
                            "</dict></plist>",
                            "  <key>CFBundleIconFile</key>"
                            "<string>AppIcon</string>\n</dict></plist>\n",
                        )
                    )
                except Exception:
                    pass  # icon is optional

            # ── Linux — .desktop file (Terminal=false, no console) ────────────
            else:
                # Export .ico → .png for better desktop integration
                png_path = ico_path.with_suffix(".png")
                if not png_path.exists() and ico_path.exists():
                    try:
                        import PIL.Image

                        PIL.Image.open(ico_path).resize(
                            (256, 256), PIL.Image.LANCZOS
                        ).save(png_path, format="PNG")
                    except Exception:
                        png_path = ico_path  # fallback to .ico

                icon_line = f"Icon={png_path}\n" if png_path.exists() else ""
                desk = desktop / "Onyx.desktop"
                desk.write_text(
                    "[Desktop Entry]\n"
                    "Name=Onyx\n"
                    f"Exec={python} {script}\n"
                    f"Path={script.parent}\n"
                    "Type=Application\n"
                    "Terminal=false\n"
                    "Categories=Utility;\n" + icon_line
                )
                desk.chmod(desk.stat().st_mode | 0o755)

            self._log.append_log("SYS: Desktop shortcut created.")
        except Exception as e:
            self._log.append_log(f"ERR: Shortcut failed — {e}")

    def _toggle_fullscreen(self):
        if self.isFullScreen():
            self.showNormal()
        else:
            self.showFullScreen()

    def _request_owner_exit(self) -> bool:
        callback = self.on_exit_requested
        if callable(callback):
            # Once the runtime owns shutdown, refusal must remain a refusal;
            # never bypass its governed cleanup with a local process exit.
            return callback("hud-exit-action") is not False
        # Onboarding runs before OnyxLive binds its callback. At that bounded
        # stage no runtime exists to quiesce, so a local exit is safe.
        self.request_explicit_exit()
        return True

    @pyqtSlot(int)
    def _schedule_explicit_exit(self, delay_ms: int = 0) -> None:
        delay = max(0, min(int(delay_ms), 10_000))
        QTimer.singleShot(delay, self.request_explicit_exit)

    @pyqtSlot()
    def request_explicit_exit(self) -> None:
        self._exit_requested = True
        print("[Onyx Lifecycle] Explicit application exit requested.", flush=True)
        self.close()

    def _send_to_background(self) -> None:
        if self._tray_available:
            self.hide()
        else:
            # Some Linux desktops intentionally expose no StatusNotifier host.
            # Keep a taskbar/application-switcher restore path there.
            self.showMinimized()
        if not self._background_notice_emitted:
            self._background_notice_emitted = True
            message = "SYS: Window closed; Onyx remains active in the background."
            self._log_sig.emit(message)
            self._background_sig.emit()
        print(
            "[Onyx Lifecycle] Window minimized; resident runtime preserved.", flush=True
        )

    def closeEvent(self, event):
        if self._close_to_background and not self._exit_requested:
            event.ignore()
            self._send_to_background()
            return
        if not self._exit_requested and callable(self.on_exit_requested):
            # Source/dev windows must use the same runtime-owned cleanup path as
            # the trusted EXIT action. Accepting the native X immediately used
            # to tear down Qt first and only then cancel PortAudio, leaving its
            # capture/playback workers alive at the cleanup boundary.
            event.ignore()
            self.on_exit_requested("window-close")
            return
        print("[Onyx Lifecycle] Main window closeEvent accepted.", flush=True)
        self._cam_stop.set()
        self._clock_tmr.stop()
        self._metric_tmr.stop()
        _metrics.shutdown()
        self._attention_tmr.stop()
        host = self._v5_host
        if host is not None:
            projection = host.projection
            if self._v5_log_connected:
                try:
                    self._log_sig.disconnect(projection.append_log)
                except (RuntimeError, TypeError):
                    pass
                self._v5_log_connected = False
            try:
                host.rendererFailed.disconnect(self._on_v5_renderer_failed)
            except (RuntimeError, TypeError):
                pass
            host.shutdown()
        super().closeEvent(event)
        app = QApplication.instance()
        if app is not None:
            QTimer.singleShot(0, app.quit)

    def resizeEvent(self, event):
        super().resizeEvent(event)
        cw = self.centralWidget()
        if self._overlay and self._overlay.isVisible():
            ow, oh = 460, 390
            self._overlay.setGeometry(
                (cw.width() - ow) // 2,
                (cw.height() - oh) // 2,
                ow,
                oh,
            )
        if self._remote_overlay and self._remote_overlay.isVisible():
            ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
            self._remote_overlay.setGeometry(
                (cw.width() - ow) // 2,
                (cw.height() - oh) // 2,
                ow,
                oh,
            )
        # Camera preview — bottom-right corner of the center/HUD area
        pw = _CameraPreview._W
        ph = self._cam_preview.height() or _CameraPreview._H
        right_inset = 24 if self._hud_v5_live else _RIGHT_W + 12
        self._cam_preview.setGeometry(
            cw.width() - right_inset - pw,
            cw.height() - ph - 28,
            pw,
            ph,
        )

    def _update_metrics(self):
        snap = _metrics.snapshot()

        # CPU
        cpu = snap["cpu"]
        self._bar_cpu.set_value(cpu, f"{cpu:.0f}%")

        # MEM
        mem = snap["mem"]
        self._bar_mem.set_value(mem, f"{mem:.0f}%")

        # NET
        net = snap["net"]
        if net < 1.0:
            net_str = f"{net * 1024:.0f}KB/s"
        else:
            net_str = f"{net:.1f}MB/s"
        net_pct = min(100, net * 10)  # 10 MB/s = %100
        self._bar_net.set_value(net_pct, net_str)

        # GPU
        gpu = snap["gpu"]
        if gpu >= 0:
            self._bar_gpu.set_value(gpu, f"{gpu:.0f}%")
        else:
            self._bar_gpu.set_value(0, "N/A")

        # TMP
        tmp = snap["tmp"]
        if tmp >= 0:
            tmp_pct = min(100, (tmp / 100) * 100)
            self._bar_tmp.set_value(tmp_pct, f"{tmp:.0f}°C")
        else:
            self._bar_tmp.set_value(0, "N/A")

        try:
            boot_t = psutil.boot_time()
            elapsed = time.time() - boot_t
            h = int(elapsed // 3600)
            m = int((elapsed % 3600) // 60)
            self._uptime_lbl.setText(f"UP  {h:02d}:{m:02d}")
        except Exception:
            self._uptime_lbl.setText("UP  --:--")

        try:
            proc_count = len(psutil.pids())
            self._proc_lbl.setText(f"PROC  {proc_count}")
        except Exception:
            self._proc_lbl.setText("PROC  --")

        if self._v5_projection is not None:
            self._v5_projection.set_metrics(cpu, mem, net_str)

    def _build_header(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(52)
        w.setStyleSheet(f"background: {C.ONYX}; border-bottom: 1px solid {C.GUNMETAL};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(24, 0, 24, 0)

        def _badge(txt, color=C.TEXT_MED):
            label = QLabel(txt)
            label.setFont(QFont("Cascadia Mono", 8))
            label.setStyleSheet(f"color: {color}; background: transparent;")
            return label

        brand = QVBoxLayout()
        brand.setSpacing(0)
        brand.addWidget(_badge("CYRYX LABS", C.TEXT_MED))
        brand.addWidget(_badge("GOVERNED AI SYSTEM", C.TEXT_DIM))
        lay.addLayout(brand)
        lay.addStretch()

        mid = QVBoxLayout()
        mid.setSpacing(1)
        title = QLabel("ONYX")
        title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        title.setFont(QFont("Bahnschrift", 15, QFont.Weight.DemiBold))
        title.setStyleSheet(
            f"color: {C.SILVER}; background: transparent; letter-spacing: 5px;"
        )
        mid.addWidget(title)
        sub = QLabel("AGENTIC COMMAND ENTITY")
        sub.setAlignment(Qt.AlignmentFlag.AlignCenter)
        sub.setFont(QFont("Segoe UI", 7, QFont.Weight.Medium))
        sub.setStyleSheet(f"color: {C.PRI_DIM}; background: transparent;")
        mid.addWidget(sub)
        lay.addLayout(mid)
        lay.addStretch()

        right_col = QVBoxLayout()
        right_col.setSpacing(2)
        self._clock_lbl = QLabel("00:00:00")
        self._clock_lbl.setFont(QFont("Cascadia Mono", 14, QFont.Weight.Bold))
        self._clock_lbl.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        self._clock_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._clock_lbl)
        self._date_lbl = QLabel("")
        self._date_lbl.setFont(QFont("Cascadia Mono", 7))
        self._date_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        self._date_lbl.setAlignment(Qt.AlignmentFlag.AlignRight)
        right_col.addWidget(self._date_lbl)
        lay.addLayout(right_col)
        return w

    def _tick_clock(self):
        self._clock_lbl.setText(time.strftime("%H:%M:%S"))
        self._date_lbl.setText(time.strftime("%a %d %b %Y"))

    def _build_left_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("TelemetryPanel")
        w.setFixedWidth(_LEFT_W)
        w.setStyleSheet("""
            QWidget#TelemetryPanel {
                background: transparent;
                border: none;
            }
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(10)

        hdr = QLabel("ENTITY TELEMETRY")
        hdr.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(
            f"color: {C.PRI}; background: transparent; "
            f"border-left: 2px solid {C.PRI}; padding: 2px 0 2px 8px;"
        )
        lay.addWidget(hdr)
        lay.addSpacing(2)

        self._bar_cpu = MetricBar("CPU", C.PRI)
        self._bar_mem = MetricBar("MEM", C.ACC2)
        self._bar_net = MetricBar("NET", C.GREEN)
        self._bar_gpu = MetricBar("GPU", C.ACC)
        self._bar_tmp = MetricBar("TMP", C.RED)

        for bar in [
            self._bar_cpu,
            self._bar_mem,
            self._bar_net,
            self._bar_gpu,
            self._bar_tmp,
        ]:
            lay.addWidget(bar)

        lay.addSpacing(4)

        info_panel = QWidget()
        info_panel.setStyleSheet(
            f"background: transparent; border: none; "
            f"border-top: 1px solid {C.GUNMETAL}; "
            f"border-left: 1px solid {C.CORE_TEAL};"
        )
        ip_lay = QVBoxLayout(info_panel)
        ip_lay.setContentsMargins(6, 5, 6, 5)
        ip_lay.setSpacing(3)

        self._uptime_lbl = QLabel("UP  --:--")
        self._uptime_lbl.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self._uptime_lbl.setStyleSheet(
            f"color: {C.GREEN}; background: transparent; border: none;"
        )
        ip_lay.addWidget(self._uptime_lbl)

        self._proc_lbl = QLabel("PROC  --")
        self._proc_lbl.setFont(QFont("Cascadia Mono", 8))
        self._proc_lbl.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; border: none;"
        )
        ip_lay.addWidget(self._proc_lbl)

        os_name = {"Windows": "WIN", "Darwin": "macOS", "Linux": "LINUX"}.get(
            _OS, _OS.upper()
        )
        os_lbl = QLabel(f"OS  {os_name}")
        os_lbl.setFont(QFont("Cascadia Mono", 8))
        os_lbl.setStyleSheet(f"color: {C.ACC2}; background: transparent; border: none;")
        ip_lay.addWidget(os_lbl)

        lay.addWidget(info_panel)
        lay.addSpacing(4)

        lay.addStretch()

        for txt, col in [
            ("SOUL KERNEL\nLOADED", C.GREEN),
            ("LOCAL TOOLS\nCLOUD MODEL", C.PRI),
            ("CYRYX COMMAND\nSECURE", C.ACC2),
        ]:
            lbl = QLabel(txt)
            lbl.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
            lbl.setAlignment(Qt.AlignmentFlag.AlignCenter)
            lbl.setStyleSheet(
                f"color: {col}; background: transparent;"
                f"border: none; border-left: 2px solid {col}; padding: 5px 7px;"
            )
            lay.addWidget(lbl)

        return w

    def _build_activity_panel(self) -> QWidget:
        """A light peripheral activity rail; primary controls live in the command deck."""
        w = QWidget()
        w.setObjectName("ActivityRail")
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet("""
            QWidget#ActivityRail {
                background: transparent;
                border: none;
            }
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(0, 12, 0, 8)
        lay.setSpacing(10)

        hdr = QLabel("COGNITIVE TRACE")
        hdr.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        hdr.setStyleSheet(
            f"color: {C.TEXT_MED}; background: transparent; "
            f"border-right: 2px solid {C.PRI_DIM}; padding: 2px 8px 2px 0;"
        )
        hdr.setAlignment(Qt.AlignmentFlag.AlignRight)
        lay.addWidget(hdr)

        self._log = LogWidget()
        self._log.setStyleSheet(f"""
            QTextEdit {{
                background: rgba(10, 13, 15, 170);
                color: {C.TEXT};
                border: none;
                border-top: 1px solid {C.GUNMETAL};
                border-right: 1px solid {C.CORE_TEAL};
                border-radius: 0;
                padding: 10px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{ background: transparent; width: 5px; border: none; }}
            QScrollBar::handle:vertical {{ background: {C.BORDER_B}; border-radius: 2px; min-height: 20px; }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{ height: 0; }}
        """)
        lay.addWidget(self._log, stretch=1)

        session = QLabel("MISSION LEDGER  /  LOCAL TRACE")
        session.setFont(QFont("Cascadia Mono", 6))
        session.setAlignment(Qt.AlignmentFlag.AlignRight)
        session.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        lay.addWidget(session)
        return w

    def _build_command_dock(self) -> QWidget:
        """Cinematic lower command deck containing every operational control."""
        deck = HolographicPanel()
        deck.setObjectName("CommandDeck")
        deck.setFixedHeight(132)
        deck.setMinimumWidth(760)
        deck.setMaximumWidth(930)
        outer = QVBoxLayout(deck)
        outer.setContentsMargins(16, 8, 16, 8)
        outer.setSpacing(6)

        channel = QHBoxLayout()
        channel.setSpacing(12)

        context_col = QVBoxLayout()
        context_col.setSpacing(2)
        context_lbl = QLabel("ATLAS CONTEXT")
        context_lbl.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        context_lbl.setStyleSheet(f"color: {C.TEXT_DIM}; background: transparent;")
        context_col.addWidget(context_lbl)
        self._drop_zone = FileDropZone()
        self._drop_zone.setFixedSize(218, 48)
        self._drop_zone.file_selected.connect(self._on_file_selected)
        context_col.addWidget(self._drop_zone)
        self._file_hint = QLabel("No file loaded")
        self._file_hint.setFont(QFont("Cascadia Mono", 6))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setMaximumWidth(218)
        self._file_hint.setWordWrap(False)
        context_col.addWidget(self._file_hint)
        channel.addLayout(context_col)

        command_col = QVBoxLayout()
        command_col.setSpacing(4)
        command_lbl = QLabel("MISSION COMMAND  /  DIRECT · CREATE · EXECUTE")
        command_lbl.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        command_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        command_col.addWidget(command_lbl)
        command_col.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(30)
        self._interrupt_btn.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet(f"""
            QPushButton {{
                background: rgba(27, 34, 39, 190); color: {C.RED};
                border: 1px solid {C.RED}; border-radius: 8px;
            }}
            QPushButton:hover {{ background: rgba(167, 77, 87, 45); color: {C.SILVER}; }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        command_col.addWidget(self._interrupt_btn)
        channel.addLayout(command_col, stretch=1)
        outer.addLayout(channel)

        actions = QHBoxLayout()
        actions.setSpacing(8)
        self._mute_btn = QPushButton("MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(28)
        self._mute_btn.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        actions.addWidget(self._mute_btn, stretch=2)

        try:
            _cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cfg = {}
        self._autonomy_enabled = (
            _cfg.get("trust_profile") == "autonomous"
            and _cfg.get("owner_autonomy_enabled") is True
        )
        self._autonomy_btn = QPushButton()
        self._autonomy_btn.setFixedHeight(28)
        self._autonomy_btn.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
        self._autonomy_btn.setToolTip(
            "Broad browser/computer control can create external effects. "
            "Direct high-consequence tools remain confirmation-gated."
        )
        self._autonomy_btn.clicked.connect(self._toggle_owner_autonomy)
        self._style_autonomy_btn()
        actions.addWidget(self._autonomy_btn, stretch=2)

        def _dock_button(text: str) -> QPushButton:
            button = QPushButton(text)
            button.setFixedHeight(28)
            button.setFont(QFont("Cascadia Mono", 7))
            button.setCursor(Qt.CursorShape.PointingHandCursor)
            button.setStyleSheet(f"""
                QPushButton {{
                    background: rgba(17, 22, 26, 200); color: {C.TEXT_MED};
                    border: 1px solid {C.GUNMETAL}; border-radius: 8px;
                }}
                QPushButton:hover {{
                    background: rgba(15, 107, 104, 55); color: {C.PRI}; border-color: {C.PRI_DIM};
                }}
            """)
            return button

        remote_btn = _dock_button("REMOTE")
        remote_btn.clicked.connect(self._open_remote)
        actions.addWidget(remote_btn)
        fs_btn = _dock_button("FULLSCREEN  [F11]")
        fs_btn.clicked.connect(self._toggle_fullscreen)
        actions.addWidget(fs_btn)
        sc_btn = _dock_button("DESKTOP SHORTCUT")
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        actions.addWidget(sc_btn)
        outer.addLayout(actions)
        return deck

    def _build_right_panel(self) -> QWidget:
        w = QWidget()
        w.setObjectName("OperationsPanel")
        w.setFixedWidth(_RIGHT_W)
        w.setStyleSheet("""
            QWidget#OperationsPanel {
                background: rgba(10, 13, 15, 224);
                border: 1px solid #1B2227;
                border-radius: 14px;
            }
        """)
        lay = QVBoxLayout(w)
        lay.setContentsMargins(13, 14, 13, 14)
        lay.setSpacing(8)

        def _sec(txt):
            label = QLabel(f"▸ {txt}")
            label.setFont(QFont("Cascadia Mono", 7, QFont.Weight.Bold))
            label.setStyleSheet(
                f"color: {C.TEXT_MED}; background: transparent; letter-spacing: 1px;"
            )
            return label

        lay.addWidget(_sec("ACTIVITY LOG"))
        self._log = LogWidget()
        lay.addWidget(self._log, stretch=1)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep)

        lay.addWidget(_sec("FILE UPLOAD"))
        self._drop_zone = FileDropZone()
        self._drop_zone.file_selected.connect(self._on_file_selected)
        lay.addWidget(self._drop_zone)

        self._file_hint = QLabel("No file loaded — drop or click above to upload")
        self._file_hint.setFont(QFont("Cascadia Mono", 7))
        self._file_hint.setStyleSheet(f"color: {C.TEXT_MED}; background: transparent;")
        self._file_hint.setWordWrap(True)
        lay.addWidget(self._file_hint)

        sep2 = QFrame()
        sep2.setFrameShape(QFrame.Shape.HLine)
        sep2.setStyleSheet(f"color: {C.BORDER}; margin: 2px 0;")
        lay.addWidget(sep2)

        lay.addWidget(_sec("COMMAND INPUT"))
        lay.addLayout(self._build_input_row())

        self._interrupt_btn = QPushButton("✋  INTERRUPT  [ESC]")
        self._interrupt_btn.setFixedHeight(34)
        self._interrupt_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self._interrupt_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._interrupt_btn.setStyleSheet("""
            QPushButton {{
                background: #11161A; color: #A74D57;
                border: 1px solid #A74D57; border-radius: 7px;
            }}
            QPushButton:hover {{
                background: #1B2227; color: #C7C9CC; border: 1px solid #A74D57;
            }}
            QPushButton:pressed {{
                background: #0A0D0F;
            }}
        """)
        self._interrupt_btn.clicked.connect(self._do_interrupt)
        lay.addWidget(self._interrupt_btn)

        self._mute_btn = QPushButton("🎙  MICROPHONE ACTIVE")
        self._mute_btn.setFixedHeight(30)
        self._mute_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self._mute_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self._mute_btn.clicked.connect(self._toggle_mute)
        self._style_mute_btn()
        lay.addWidget(self._mute_btn)

        try:
            _cfg = json.loads(API_FILE.read_text(encoding="utf-8"))
        except Exception:
            _cfg = {}
        self._autonomy_enabled = (
            _cfg.get("trust_profile") == "autonomous"
            and _cfg.get("owner_autonomy_enabled") is True
        )
        self._autonomy_btn = QPushButton()
        self._autonomy_btn.setFixedHeight(30)
        self._autonomy_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self._autonomy_btn.setToolTip(
            "Broad browser/computer control can create external effects. Direct high-consequence tools remain confirmation-gated."
        )
        self._autonomy_btn.clicked.connect(self._toggle_owner_autonomy)
        self._style_autonomy_btn()
        lay.addWidget(self._autonomy_btn)

        remote_btn = QPushButton("◉  REMOTE CONTROL")
        remote_btn.setFixedHeight(30)
        remote_btn.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        remote_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        remote_btn.setStyleSheet(f"""
            QPushButton {{
                background: #11161A; color: {C.TEXT_MED};
                border: 1px solid #1B2227; border-radius: 7px;
            }}
            QPushButton:hover {{
                background: {C.PRI_GHO}; color: {C.PRI}; border: 1px solid {C.PRI_DIM};
            }}
        """)
        remote_btn.clicked.connect(self._open_remote)
        lay.addWidget(remote_btn)

        fs_btn = QPushButton("⛶  FULLSCREEN  [F11]")
        fs_btn.setFixedHeight(26)
        fs_btn.setFont(QFont("Cascadia Mono", 7))
        fs_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        fs_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_MED};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.PRI}; border: 1px solid {C.BORDER_B};
            }}
        """)
        fs_btn.clicked.connect(self._toggle_fullscreen)
        lay.addWidget(fs_btn)

        sc_btn = QPushButton("⊞  CREATE DESKTOP SHORTCUT")
        sc_btn.setFixedHeight(26)
        sc_btn.setFont(QFont("Cascadia Mono", 7))
        sc_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        sc_btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 3px;
            }}
            QPushButton:hover {{
                color: {C.ACC2}; border: 1px solid {C.BORDER_B};
            }}
        """)
        sc_btn.clicked.connect(self._create_desktop_shortcut)
        lay.addWidget(sc_btn)

        return w

    def _build_input_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(5)
        self._input = QLineEdit()
        self._input.setPlaceholderText("Type a command or question…")
        self._input.setFont(QFont("Cascadia Mono", 9))
        self._input.setFixedHeight(30)
        self._input.setStyleSheet(f"""
            QLineEdit {{
                background: {C.OBSIDIAN}; color: {C.WHITE};
                border: 1px solid {C.BORDER}; border-radius: 3px; padding: 3px 7px;
            }}
            QLineEdit:focus {{ border: 1px solid {C.PRI}; }}
        """)
        self._input.returnPressed.connect(self._send)
        row.addWidget(self._input)

        send = QPushButton("▸")
        send.setFixedSize(30, 30)
        send.setFont(QFont("Cascadia Mono", 11, QFont.Weight.Bold))
        send.setCursor(Qt.CursorShape.PointingHandCursor)
        send.setStyleSheet(f"""
            QPushButton {{
                background: {C.PANEL}; color: {C.PRI};
                border: 1px solid {C.PRI_DIM}; border-radius: 3px;
            }}
            QPushButton:hover {{ background: {C.PRI_GHO}; border: 1px solid {C.PRI}; }}
        """)
        send.clicked.connect(self._send)
        row.addWidget(send)
        return row

    def _build_content_panel(self) -> QWidget:
        """
        Collapsible panel below the HUD — shows search results, news, briefings.
        Hidden by default; appears when show_content() is called.
        """
        w = QWidget()
        w.setObjectName("ContentPanel")
        w.setStyleSheet(f"""
            QWidget#ContentPanel {{
                background: {C.PANEL};
                border-top: 1px solid {C.BORDER_B};
            }}
        """)
        w.hide()

        lay = QVBoxLayout(w)
        lay.setContentsMargins(12, 7, 12, 8)
        lay.setSpacing(5)

        # ── header row ───────────────────────────────────────────────────────
        hdr = QHBoxLayout()
        hdr.setSpacing(6)

        dot = QLabel("◈")
        dot.setFont(QFont("Cascadia Mono", 9, QFont.Weight.Bold))
        dot.setStyleSheet(f"color: {C.PRI}; background: transparent;")
        hdr.addWidget(dot)

        self._content_title_lbl = QLabel("BRIEFING")
        self._content_title_lbl.setFont(QFont("Cascadia Mono", 8, QFont.Weight.Bold))
        self._content_title_lbl.setStyleSheet(
            f"color: {C.PRI}; background: transparent; letter-spacing: 1px;"
        )
        hdr.addWidget(self._content_title_lbl)
        hdr.addStretch()

        self._content_ts_lbl = QLabel("")
        self._content_ts_lbl.setFont(QFont("Cascadia Mono", 7))
        self._content_ts_lbl.setStyleSheet(
            f"color: {C.TEXT_DIM}; background: transparent;"
        )
        hdr.addWidget(self._content_ts_lbl)

        dismiss = QPushButton("DISMISS  ✕")
        dismiss.setFont(QFont("Cascadia Mono", 7))
        dismiss.setFixedHeight(18)
        dismiss.setCursor(Qt.CursorShape.PointingHandCursor)
        dismiss.setStyleSheet(f"""
            QPushButton {{
                background: transparent; color: {C.TEXT_DIM};
                border: 1px solid {C.BORDER}; border-radius: 2px; padding: 0 5px;
            }}
            QPushButton:hover {{ color: {C.TEXT}; border-color: {C.BORDER_B}; }}
        """)
        dismiss.clicked.connect(w.hide)
        hdr.addWidget(dismiss)
        lay.addLayout(hdr)

        # ── separator ─────────────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet(f"color: {C.BORDER};")
        lay.addWidget(sep)

        # ── text display ──────────────────────────────────────────────────────
        self._content_display = QTextEdit()
        self._content_display.setReadOnly(True)
        self._content_display.setFont(QFont("Cascadia Mono", 8))
        self._content_display.setMinimumHeight(60)
        self._content_display.setSizePolicy(
            QSizePolicy.Policy.Expanding, QSizePolicy.Policy.Expanding
        )
        self._content_display.setStyleSheet(f"""
            QTextEdit {{
                background: {C.DARK};
                color: {C.TEXT};
                border: 1px solid {C.BORDER};
                border-radius: 3px;
                padding: 6px 8px;
                selection-background-color: {C.PRI_GHO};
            }}
            QScrollBar:vertical {{
                background: {C.BG}; width: 6px; border: none;
            }}
            QScrollBar::handle:vertical {{
                background: {C.BORDER_B}; border-radius: 3px; min-height: 16px;
            }}
            QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
                height: 0; border: none;
            }}
        """)
        lay.addWidget(self._content_display)

        return w

    def _show_content(self, title: str, text: str):
        """Slot — runs on Qt main thread. Updates and shows the content panel."""
        if self._v5_projection is not None:
            self._v5_projection.set_content(title, text)
        import time as _time

        self._content_title_lbl.setText(title.upper()[:48])
        self._content_ts_lbl.setText(_time.strftime("%H:%M:%S"))
        self._content_display.setPlainText(text)
        self._content_display.moveCursor(
            self._content_display.textCursor().MoveOperation.Start
        )
        first_show = not self._content_panel.isVisible()
        self._content_panel.show()
        if first_show:
            total = self._center_split.height()
            self._center_split.setSizes([max(total - 220, 120), 220])

    def _build_footer(self) -> QWidget:
        w = QWidget()
        w.setFixedHeight(22)
        w.setStyleSheet(f"background: {C.DARK}; border-top: 1px solid {C.BORDER};")
        lay = QHBoxLayout(w)
        lay.setContentsMargins(14, 0, 14, 0)

        def _fl(txt, color=C.TEXT_MED):
            label = QLabel(txt)
            label.setFont(QFont("Cascadia Mono", 7))
            label.setStyleSheet(f"color: {color}; background: transparent;")
            return label

        lay.addWidget(_fl("[F4] Mute  ·  [F11] Fullscreen"))
        lay.addStretch()
        lay.addWidget(_fl("ONYX  /  GOVERNED  /  AGENTIC"))
        lay.addStretch()
        lay.addWidget(_fl("CYRYX LABS", C.PRI_DIM))
        return w

    def _on_file_selected(self, path: str):
        self._current_file = path
        p = Path(path)
        cat = _file_category(p)
        icon, _ = _FILE_ICONS.get(cat, _FILE_ICONS["unknown"])
        size = _fmt_size(p.stat().st_size)
        self._file_hint.setText(
            f"{icon}  {p.name}  ·  {size}  ·  Tell Onyx what to do with it"
        )
        self._log.append_log(f"FILE: {p.name} ({size}) loaded")
        if self._v5_projection is not None:
            self._v5_projection.set_file(path)
            self._v5_projection.append_log(f"FILE  /  {p.name}  /  {size}")
        _dispatch_selected_file(
            host_callback=self.on_file_attachment,
            legacy_model_callback=self.on_text_command,
            path=path,
            filename=p.name,
            suffix=p.suffix.lstrip("."),
            size=size,
            runtime_dispatch=self.on_runtime_worker,
        )

    def notify_phone_connected(self) -> None:
        if self._remote_overlay and self._remote_overlay.isVisible():
            self._remote_overlay.mark_connected()

    def _open_remote(self):
        if not self.on_remote_clicked:
            self._log.append_log("SYS: Dashboard not running — remote unavailable.")
            return
        result = self.on_remote_clicked()
        if not result:
            self._log.append_log("SYS: Could not generate remote key.")
            return
        url = result[0]
        key = result[1]
        auto = result[2] if len(result) >= 3 else ""
        manual = result[3] if len(result) >= 4 else url
        if self._remote_overlay:
            self._remote_overlay._do_close()
        cw = self.centralWidget()
        ow, oh = RemoteKeyOverlay._OW, RemoteKeyOverlay._OH
        ov = RemoteKeyOverlay(
            url, key, auto_login_url=auto, manual_url=manual, expiry_secs=600, parent=cw
        )
        ov.set_new_key_callback(self.on_remote_clicked)
        ov.setGeometry(
            (cw.width() - ow) // 2,
            (cw.height() - oh) // 2,
            ow,
            oh,
        )
        ov.closed.connect(lambda: setattr(self, "_remote_overlay", None))
        ov.show()
        self._remote_overlay = ov
        self._log.append_log(f"SYS: Remote key generated — manual: {manual or url}")

    def _do_interrupt(self):
        if self.on_interrupt:
            self.on_interrupt()

    def _toggle_mute(self):
        self._muted = not self._muted
        self.hud.set_muted(self._muted)
        self._style_mute_btn()
        if self._muted:
            self._apply_state("MUTED")
            self._log.append_log("SYS: Microphone muted.")
        else:
            self._apply_state("LISTENING")
            self._log.append_log("SYS: Microphone active.")

    def _style_mute_btn(self):
        if self._muted:
            self._mute_btn.setText("MICROPHONE MUTED")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.GRAPHITE}; color: {C.MUTED_C};
                    border: 1px solid {C.MUTED_C}; border-radius: 7px;
                }}
            """)
        else:
            self._mute_btn.setText("MICROPHONE ACTIVE")
            self._mute_btn.setStyleSheet(f"""
                QPushButton {{
                    background: {C.GRAPHITE}; color: {C.TEAL_GLOW};
                    border: 1px solid {C.CORE_TEAL}; border-radius: 7px;
                }}
                QPushButton:hover {{ background: rgba(15, 107, 104, 45); }}
            """)

    def _style_autonomy_btn(self):
        state = "ON" if self._autonomy_enabled else "OFF"
        color = C.TEAL_GLOW if self._autonomy_enabled else C.TEXT_DIM
        border = C.CORE_TEAL if self._autonomy_enabled else C.GUNMETAL
        self._autonomy_btn.setText(f"OWNER AUTONOMY {state}")
        self._autonomy_btn.setStyleSheet(
            f"QPushButton {{ background:{C.GRAPHITE}; color:{color}; "
            f"border:1px solid {border}; border-radius:7px; }}"
        )
        if self._v5_projection is not None:
            self._v5_projection.set_autonomy_enabled(self._autonomy_enabled)

    def _toggle_owner_autonomy(self):
        original = self._autonomy_enabled
        try:
            data = (
                json.loads(API_FILE.read_text(encoding="utf-8"))
                if API_FILE.exists()
                else {}
            )
            if not isinstance(data, dict):
                data = {}
            enabling = not self._autonomy_enabled
            if enabling:
                decision = QMessageBox.question(
                    self,
                    "Enable owner autonomy?",
                    _owner_autonomy_warning(data.get("autonomous_workspace_roots", [])),
                    QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                    QMessageBox.StandardButton.No,
                )
                if decision != QMessageBox.StandardButton.Yes:
                    return
            self._autonomy_enabled = enabling
            data["trust_profile"] = (
                "autonomous" if self._autonomy_enabled else "cautious"
            )
            data["owner_autonomy_enabled"] = self._autonomy_enabled
            from core.credentials import save_settings

            save_settings(
                {
                    "trust_profile": data["trust_profile"],
                    "owner_autonomy_enabled": self._autonomy_enabled,
                },
                API_FILE,
            )
            from core.permission_broker import (
                configure_owner_autonomy,
                set_trust_profile,
            )

            set_trust_profile(data["trust_profile"])
            configure_owner_autonomy(
                self._autonomy_enabled, data.get("autonomous_workspace_roots", [])
            )
            self._style_autonomy_btn()
            self._log.append_log(
                f"SYS: OWNER AUTONOMY {'ON' if self._autonomy_enabled else 'OFF'}. Broad UI control may create external effects."
            )
        except Exception:
            self._autonomy_enabled = original
            self._style_autonomy_btn()
            self._log.append_log("ERR: Owner autonomy setting was not changed.")

    def _send(self):
        txt = self._input.text().strip()
        if not txt:
            return
        self._input.clear()
        self._log.append_log(f"You: {txt}")
        if self.on_text_command:
            dispatcher = self.on_runtime_worker
            if callable(dispatcher):
                dispatcher(
                    "text-command-legacy",
                    lambda: self.on_text_command(txt),
                    None,
                )

    def _apply_state(self, state: str):
        self.hud.set_operational_state(state)

    def _apply_audio_level(self, level: float):
        # `hud` inherits set_audio_level (clamp + governor pacing + notify)
        # from the accepted OnyxUIProjection contract.
        setter = getattr(self.hud, "set_audio_level", None)
        if setter is not None:
            setter(level)

    def _check_config(self) -> bool:
        try:
            from core.credentials import migrate_legacy, status

            migrate_legacy(API_FILE)
            credential_ready = bool(status().get("configured"))
            if not API_FILE.exists():
                return False
            d = json.loads(API_FILE.read_text(encoding="utf-8"))
            return (
                credential_ready
                and bool(d.get("os_system"))
                and bool(str(d.get("owner_name", "")).strip())
            )
        except Exception:
            return False

    def _show_setup(self):
        self._setup_open_pending = False
        if self._overlay is not None and self._overlay.isVisible():
            self._overlay.raise_()
            return
        try:
            from core.credentials import status

            configured = bool(status().get("configured"))
        except Exception:
            configured = False
        ov = SetupOverlay(
            self.centralWidget(),
            credential_configured=configured,
            dismissible=self._ready,
        )
        cw = self.centralWidget()
        ow, oh = 500, 620
        ov.setGeometry(
            (cw.width() - ow) // 2,
            (cw.height() - oh) // 2,
            ow,
            oh,
        )
        self._overlay = ov
        ov.done.connect(self._on_setup_done)
        ov.dismissed.connect(self._dismiss_setup)
        ov.show()
        ov.raise_()

    def _dismiss_setup(self) -> None:
        """Return from an already-configured Setup overlay without mutation."""

        self._setup_open_pending = False
        overlay = self._overlay
        if overlay is None:
            return
        overlay.hide()
        overlay.deleteLater()
        self._overlay = None

    def _on_setup_done(self, key: str, os_name: str, owner_name: str = ""):
        previous = None
        attempted_store = False
        try:
            from core.credentials import (
                CredentialError,
                delete,
                get,
                save_settings,
                set,
            )

            previous = get(required=False)
            if key:
                attempted_store = True
                set(key)
            elif not previous:
                raise CredentialError("Gemini credential is not configured")
            save_settings(
                {"os_system": os_name, "owner_name": owner_name.strip()[:80]}, API_FILE
            )
            selected_voice = getattr(self._overlay, "selected_voice", None)
            if type(selected_voice) is str:
                selected_voice = LiveVoicePreferenceV1(
                    memory_dir() / "live_voice_preference_v1.json"
                ).set(selected_voice)
            else:
                selected_voice = None
        except Exception as exc:
            if attempted_store:
                try:
                    if previous:
                        set(previous)
                    else:
                        delete()
                except Exception:
                    pass
            safe_message = (
                str(exc)
                if isinstance(exc, CredentialError)
                else "Secure setup could not update local settings"
            )
            if self._overlay:
                self._overlay.show_error(safe_message)
            self._log.append_log("ERR: Secure credential storage failed.")
            return
        self._ready = True
        if self._overlay:
            self._overlay.hide()
            self._overlay = None
        self._apply_state("LISTENING")
        self._log.append_log(f"SYS: Welcome, {owner_name}. Onyx is online.")
        if selected_voice:
            self._log.append_log(
                f"SYS: Gemini Live voice selected: {selected_voice}; session refresh automatic."
            )
        if self._v5_projection is not None:
            self._v5_projection.set_owner_name(owner_name)
            self._v5_projection.append_log(
                f"SYSTEM  /  WELCOME {owner_name or 'SIR'}  /  ONLINE"
            )


class _RootShim:
    def __init__(self, app: QApplication):
        self._app = app

    def mainloop(self):
        print("[Onyx Lifecycle] Qt event loop entered.", flush=True)
        self._app.exec()
        print("[Onyx Lifecycle] Qt event loop returned.", flush=True)

    def protocol(self, *_):
        pass


class OnyxUI:
    def __init__(self, face_path: str, size=None):
        _configure_native_app_identity()
        self._app = QApplication.instance() or QApplication(sys.argv)
        self._closing = threading.Event()
        self._app.setQuitOnLastWindowClosed(False)
        self._app.aboutToQuit.connect(self._on_about_to_quit)
        self._app.setApplicationName("Onyx")
        self._app.setApplicationDisplayName("Onyx")
        self._app.setOrganizationName("Cyryx Labs")
        self._app.setOrganizationDomain("cyryx.labs")
        self._app.setDesktopFileName(WINDOWS_APP_USER_MODEL_ID)
        self._app.setStyle("Fusion")
        icon_path = _application_icon_path()
        if icon_path is not None:
            icon = QIcon(str(icon_path))
            if not icon.isNull():
                self._app.setWindowIcon(icon)
        self._win = MainWindow(face_path)
        if not self._app.windowIcon().isNull():
            self._win.setWindowIcon(self._app.windowIcon())
        self._resident_controls = _ResidentControls(
            self._win,
            self._app.windowIcon(),
        )
        self._win._tray_available = self._resident_controls.tray_available
        self._win._background_sig.connect(
            self._resident_controls.notify_background_once
        )
        self._resident_controls.exitRequested.connect(self.request_owner_shutdown)
        self._win.show()
        self.root = _RootShim(self._app)

    @property
    def closing(self) -> bool:
        return self._closing.is_set()

    def request_exit(self, *, delay_ms: int = 0) -> None:
        """Request a deliberate Qt-thread exit without treating window close as quit."""

        self._win._exit_sig.emit(max(0, min(int(delay_ms), 10_000)))

    def present_shutdown_recovery(self, message: str, retry, force_exit) -> None:
        """Show retry/force choices on the trusted Qt thread."""

        self._win._shutdown_recovery_sig.emit(str(message), retry, force_exit)

    @pyqtSlot(str)
    def request_owner_shutdown(self, reason: str = "local-exit") -> None:
        """Route local UI intent to the runtime; quit directly only before it exists."""

        callback = self._win.on_exit_requested
        if callable(callback):
            callback(str(reason))
            return
        self.request_exit()

    def _on_about_to_quit(self) -> None:
        self._closing.set()
        resident = getattr(self, "_resident_controls", None)
        if resident is not None:
            resident.shutdown()
        print("[Onyx Lifecycle] QApplication aboutToQuit emitted.", flush=True)

    @property
    def on_exit_requested(self):
        return self._win.on_exit_requested

    @on_exit_requested.setter
    def on_exit_requested(self, callback) -> None:
        self._win.on_exit_requested = callback

    @property
    def muted(self) -> bool:
        return self._win._muted

    @muted.setter
    def muted(self, v: bool):
        if v != self._win._muted:
            self._win._toggle_mute()

    @property
    def current_file(self) -> str | None:
        return self._win._current_file

    @property
    def on_text_command(self):
        return self._win.on_text_command

    @on_text_command.setter
    def on_text_command(self, cb):
        self._win.on_text_command = cb

    @property
    def on_file_attachment(self):
        return self._win.on_file_attachment

    @on_file_attachment.setter
    def on_file_attachment(self, cb):
        self._win.on_file_attachment = cb

    @property
    def on_runtime_worker(self):
        return self._win.on_runtime_worker

    @on_runtime_worker.setter
    def on_runtime_worker(self, cb):
        self._win.on_runtime_worker = cb

    @property
    def on_remote_clicked(self):
        return self._win.on_remote_clicked

    @on_remote_clicked.setter
    def on_remote_clicked(self, cb):
        self._win.on_remote_clicked = cb

    @property
    def on_interrupt(self):
        return self._win.on_interrupt

    @on_interrupt.setter
    def on_interrupt(self, cb):
        self._win.on_interrupt = cb

    @property
    def on_dayops_status(self):
        return self._win.on_dayops_status

    @on_dayops_status.setter
    def on_dayops_status(self, cb):
        self._win.on_dayops_status = cb

    @property
    def on_dayops_connect(self):
        return self._win.on_dayops_connect

    @on_dayops_connect.setter
    def on_dayops_connect(self, cb):
        self._win.on_dayops_connect = cb

    @property
    def on_dayops_sign_in(self):
        return self._win.on_dayops_sign_in

    @on_dayops_sign_in.setter
    def on_dayops_sign_in(self, cb):
        self._win.on_dayops_sign_in = cb

    @property
    def on_dayops_disconnect(self):
        return self._win.on_dayops_disconnect

    @on_dayops_disconnect.setter
    def on_dayops_disconnect(self, cb):
        self._win.on_dayops_disconnect = cb

    @property
    def on_dayops_today_brief(self):
        return self._win.on_dayops_today_brief

    @on_dayops_today_brief.setter
    def on_dayops_today_brief(self, cb):
        self._win.on_dayops_today_brief = cb

    @property
    def on_advanced_status(self):
        return self._win.on_advanced_status

    @on_advanced_status.setter
    def on_advanced_status(self, cb):
        self._win.on_advanced_status = cb

    @property
    def on_advanced_attention(self):
        return self._win.on_advanced_attention

    @on_advanced_attention.setter
    def on_advanced_attention(self, cb):
        self._win.on_advanced_attention = cb

    def notify_phone_connected(self) -> None:
        self._win.notify_phone_connected()

    def set_state(self, state: str):
        self._win._state_sig.emit(state)

    def set_audio_level(self, level: float):
        """Thread-safe: feed live speech amplitude (0..1) to the orb."""
        try:
            self._win._audio_sig.emit(float(level))
        except (TypeError, ValueError):
            pass

    def write_log(self, text: str):
        self._win._log_sig.emit(text)

    def wait_for_api_key(self) -> bool:
        while not self._win._ready and not self._closing.is_set():
            time.sleep(0.1)
        return self._win._ready and not self._closing.is_set()

    def show_content(self, title: str, text: str):
        """Thread-safe: display content in the panel below the HUD."""
        self._win._content_sig.emit(title[:48], text[:4000])

    def prompt_reconfig(self):
        """Thread-safe: show the API key setup overlay (e.g. after an auth error)."""
        self._win._ready = False
        self._win._reconfig_sig.emit()

    def show_camera_frame(self, img_bytes: bytes):
        """Thread-safe: show a webcam frame in the small overlay (screen captures)."""
        self._win._camera_sig.emit(img_bytes)

    def start_camera_stream(self) -> None:
        """Thread-safe: start live camera feed in the full HUD area."""
        self._win.start_camera_stream()

    def stop_camera_stream(self) -> None:
        """Thread-safe: stop the live camera feed."""
        self._win.stop_camera_stream()

    def start_speaking(self):
        self.set_state("SPEAKING")

    def stop_speaking(self):
        if not self.muted:
            self.set_state("LISTENING")

    # The governance action binding stays valid for 15 minutes.  Waiting longer
    # than that would let an approval land against an expired binding, so the
    # prompt is bounded well inside it while still giving the owner time to
    # return to the machine.  Timing out remains a refusal: fail-closed.
    PERMISSION_PROMPT_TIMEOUT_S = 600

    def request_permission(self, request: dict) -> str | None:
        """Synchronously wait for a decision rendered by the local Qt UI."""
        done = threading.Event()
        result: list[str] = []
        self._win._permission_sig.emit(request, done, result)
        if not done.wait(timeout=self.PERMISSION_PROMPT_TIMEOUT_S):
            return None
        return result[0] if result else None

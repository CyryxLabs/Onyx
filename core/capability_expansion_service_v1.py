"""Canonical composition for Onyx capability-expansion domains.

IDS decision: CREATE. The domain modules and canonical runtime existed, but no
host-owned composition instantiated their stores, gates, and model dispatch in
one fail-closed boundary.
"""

from __future__ import annotations

import os
import sqlite3
import threading
from dataclasses import asdict, is_dataclass
from pathlib import Path
from typing import Callable, Mapping

from core.capability_expansion_runtime_v1 import CapabilityExpansionRuntimeV1
from core.camera_gesture_attention_v1 import CameraGestureAttention
from core.clipboard_intelligence_v1 import ClipboardIntelligenceStoreV1
from core.continuous_learning_v1 import OnyxOwnerInterviewV1
from core.governed_personalization_v1 import (
    GovernedPersonalizationError,
    GovernedPersonalizationStoreV1,
    PersonalizationFeatureGateV1,
)
from core.plugin_runtime_v1 import PluginHostV1
from core.plugin_docker_sandbox_v1 import create_plugin_docker_sandbox_v1
from core.social_publish_v1 import (
    CaptionGenerationRequestV1,
    CaptionRequestV1,
    SocialProviderAdapterV1,
    SocialPublicationV1,
    SocialPublishFeatureGateV1,
    create_social_publication_v1,
    generate_caption_draft,
    preview_caption,
)
from core.social_video_asset_v1 import SocialVideoAssetBrokerV1
from core.wellness_tracker_v1 import WellnessTrackerStoreV1
from core.vision_repetition_counter_v1 import (
    VisionRepetitionContractError,
    VisionRepetitionCounterV1,
)

_FLAGS = {
    "plugin": "ONYX_PLUGIN_RUNTIME_V1",
    "clipboard": "ONYX_CLIPBOARD_INTELLIGENCE_V1",
    "wellness": "ONYX_WELLNESS_TRACKER_V1",
    "personalization": "ONYX_GOVERNED_PERSONALIZATION_V1",
    "social": "ONYX_SOCIAL_PUBLISH_V1",
}
INSTALLED_LOCAL_DEFAULT_FLAGS = (
    "ONYX_WELLNESS_TRACKER_V1",
    "ONYX_CLIPBOARD_INTELLIGENCE_V1",
    "ONYX_PLUGIN_RUNTIME_V1",
    "ONYX_SOCIAL_PUBLISH_V1",
)
_SAFE_MODEL_OPERATIONS = {
    "plugin": frozenset(
        {"status", "list", "inspect", "enable", "disable", "remove", "execute"}
    ),
    "clipboard": frozenset({"status", "opt_in", "pause", "resume", "revoke"}),
    "wellness": frozenset(
        {
            "status",
            "create",
            "correct",
            "remove",
            "repetition_status",
            "repetition_start",
            "repetition_stop",
        }
    ),
    "personalization": frozenset(
        {
            "status",
            "create",
            "confirm",
            "update",
            "remove",
            "onboarding_status",
            "onboarding_answer",
        }
    ),
    "social": frozenset({"status", "generate", "preview", "video_inspect"}),
}


class CapabilityExpansionServiceV1:
    """Own stores and route every domain call through one canonical runtime."""

    def __init__(
        self,
        memory_root: Path | str,
        *,
        owner_profile_id: str = "owner",
        workspace_id: str = "default",
        config: Mapping[str, object] | None = None,
        environ: Mapping[str, str] | None = None,
        social_adapter: SocialProviderAdapterV1 | None = None,
        social_video_roots: tuple[Path | str, ...] | None = None,
    ) -> None:
        root = Path(memory_root).expanduser().resolve()
        root.mkdir(parents=True, exist_ok=True)
        source = os.environ if environ is None else environ
        settings = dict(config or {})
        enabled = {
            capability: settings.get(flag) is True or source.get(flag) == "true"
            for capability, flag in _FLAGS.items()
        }

        plugin_sandbox, plugin_attestation_key = create_plugin_docker_sandbox_v1(
            source
        )
        self.plugin = PluginHostV1(
            root / "capability_plugins_v1.json",
            workspace_id=workspace_id,
            allow_trusted_test_plugins=enabled["plugin"],
            native_sandbox=plugin_sandbox,
            native_sandbox_attestation_key=plugin_attestation_key,
        )
        self.clipboard = ClipboardIntelligenceStoreV1(
            root / "capability_clipboard_v1.sqlite3"
        )
        self.wellness = WellnessTrackerStoreV1(
            root / "capability_wellness_v1.sqlite3"
        )
        self._repetition = VisionRepetitionCounterV1()
        self._repetition_lock = threading.RLock()
        self.personalization = None
        if enabled["personalization"]:
            try:
                self.personalization = GovernedPersonalizationStoreV1(
                    root / "capability_personalization_v1.sqlite3",
                    owner_profile_id=owner_profile_id,
                    workspace_id=workspace_id,
                    gate=PersonalizationFeatureGateV1(
                        enabled=True,
                        sensitive_enabled=settings.get(
                            "ONYX_GOVERNED_PERSONALIZATION_SENSITIVE_V1"
                        )
                        is True
                        or source.get("ONYX_GOVERNED_PERSONALIZATION_SENSITIVE_V1")
                        == "true",
                    ),
                )
            except (GovernedPersonalizationError, OSError, sqlite3.Error):
                # Personalization is additive. A damaged/unwritable local
                # profile must degrade unavailable instead of preventing the
                # existing assistant runtime from starting.
                self.personalization = None
        self.social: SocialPublicationV1 | None = None
        self._official_social_configured = False
        self._official_social_error = None
        if enabled["social"] and social_adapter is not None:
            self.social = create_social_publication_v1(
                gate=SocialPublishFeatureGateV1(True),
                adapter=social_adapter,
                ledger_path=root / "capability_social_v1.sqlite3",
            )
        elif enabled["social"] and settings.get("ONYX_SOCIAL_OFFICIAL_FACEBOOK_V1") is True:
            from core.social_official_adapter_v1 import (
                FacebookPageConfigV1,
                SocialOfficialAdapterError,
                create_social_official_publication_v1,
            )
            try:
                self.social = create_social_official_publication_v1(
                    gate=SocialPublishFeatureGateV1(True),
                    config=FacebookPageConfigV1(settings.get("ONYX_SOCIAL_FACEBOOK_PAGE_ID")),
                    ledger_path=root / "capability_social_v1.sqlite3",
                )
                self._official_social_configured = self.social is not None
            except (SocialOfficialAdapterError, PermissionError, OSError, sqlite3.Error):
                # Credentials/configuration do not prevent the assistant from
                # starting. Never serialize provider bodies or secret values.
                self._official_social_error = "official-facebook-configuration-or-vault-unavailable"
        requested_video_roots = social_video_roots or (root,)
        # The public service boundary accepts configuration-friendly strings,
        # while the security broker deliberately accepts only absolute Path
        # objects.  Normalize strings here and leave absolute/existence checks
        # inside the broker so one canonical policy still governs every root.
        normalized_video_roots = tuple(
            Path(item).expanduser() if isinstance(item, str) else item
            for item in requested_video_roots
        )
        self.social_video = SocialVideoAssetBrokerV1(normalized_video_roots)
        available = {
            "plugin": True,
            "clipboard": True,
            "wellness": True,
            "personalization": self.personalization is not None,
            # Local caption drafting, preview, and governed video inspection do
            # not require a publishing provider. Live dispatch remains a
            # separately reported adapter state.
            "social": True,
        }
        self.runtime = CapabilityExpansionRuntimeV1(
            enabled=enabled, available=available
        )
        self.owner_profile_id = owner_profile_id
        self.workspace_id = workspace_id

    def kill(self) -> None:
        self.runtime.kill()
        self.plugin.cancel()

    def revoke(self, capability: str) -> None:
        self.runtime.revoke(capability)
        if capability == "plugin":
            self.plugin.cancel()

    def redacted_status(self, capability: str | None = None) -> dict[str, object]:
        return self.runtime.status(capability)

    @property
    def repetition_active(self) -> bool:
        with self._repetition_lock:
            return self._repetition.active

    def dispatch_model(self, arguments: Mapping[str, object], *, trace_id: str = "") -> dict[str, object]:
        args = dict(arguments)
        capability = args.pop("capability", None)
        operation = args.pop("operation", None)
        if capability == "all" and operation == "status" and not args:
            return {"capabilities": self.redacted_status()}
        if type(capability) is not str or type(operation) is not str:
            raise PermissionError("capability and operation are required")
        if operation not in _SAFE_MODEL_OPERATIONS.get(capability, frozenset()):
            raise PermissionError("operation is unavailable to the model")
        # Clipboard payload is never accepted from model arguments. Preview is
        # a separate host-only entrypoint requiring an explicit UI gesture.
        if capability == "clipboard" and any(
            key in args for key in ("text", "content", "clipboard", "snapshot")
        ):
            raise PermissionError("raw clipboard model arguments are forbidden")
        result, receipt = self.runtime.dispatch(
            capability,
            operation,
            lambda: self._domain_dispatch(capability, operation, args),
            binding={"argument_names": sorted(args)},
            trace_id=trace_id,
        )
        return {"result": self._payload(result), "receipt": asdict(receipt)}

    def clipboard_preview_from_host_gesture(
        self,
        reader: Callable[[], str],
        *,
        gesture_confirmed: bool,
        trace_id: str = "",
    ) -> dict[str, object]:
        if gesture_confirmed is not True or not callable(reader):
            raise PermissionError("explicit host clipboard gesture is required")
        result, receipt = self.runtime.dispatch(
            "clipboard",
            "preview",
            lambda: self.clipboard.analyze_snapshot(
                self.owner_profile_id, self.workspace_id, reader
            ),
            binding={"source": "explicit-host-gesture"},
            trace_id=trace_id,
        )
        return {"result": self._payload(result), "receipt": asdict(receipt)}

    def start_camera_repetition_from_host(
        self,
        activity: str,
        *,
        owner_confirmed: bool,
        trace_id: str = "",
    ) -> dict[str, object]:
        """Open an owner-confirmed, frame-free repetition tracking session."""

        if owner_confirmed is not True:
            raise PermissionError("explicit owner confirmation is required")

        def start() -> object:
            with self._repetition_lock:
                return self._repetition.start(activity)

        result, receipt = self.runtime.dispatch(
            "wellness",
            "repetition_start",
            start,
            binding={"source": "camera-gesture-attention-v1"},
            trace_id=trace_id,
        )
        return {"result": self._payload(result), "receipt": asdict(receipt)}

    def observe_camera_repetition_from_host(
        self,
        observation: CameraGestureAttention,
        *,
        observed_at: float,
    ) -> dict[str, object]:
        """Consume one normalized observation; raw camera frames are forbidden."""

        if type(observation) is not CameraGestureAttention:
            raise VisionRepetitionContractError(
                "only a normalized camera-attention observation is accepted"
            )
        self.runtime.assert_dispatchable("wellness", "repetition_observe")
        with self._repetition_lock:
            estimate = self._repetition.update(
                observation.y,
                observation.confidence,
                observed_at,
            )
        return {
            "result": self._payload(estimate),
            "source": "camera-gesture-attention-v1",
            "frame_retained": False,
            "identity_processed": False,
        }

    def stop_camera_repetition_from_host(
        self,
        *,
        occurred_at: str,
        timezone_name: str,
        idempotency_key: str,
        trace_id: str = "",
    ) -> dict[str, object]:
        """Stop tracking and materialize a non-counting owner-confirmable draft."""

        def stop_and_materialize() -> dict[str, object]:
            with self._repetition_lock:
                if not self._repetition.active:
                    raise VisionRepetitionContractError(
                        "repetition counter is not active"
                    )
                estimate = self._repetition.snapshot()
                draft = None
                if estimate.repetitions > 0:
                    draft = self.wellness.create_vision_estimate(
                        self.owner_profile_id,
                        self.workspace_id,
                        kind="exercise",
                        activity=estimate.activity,
                        value=estimate.repetitions,
                        unit="repetitions",
                        occurred_at=occurred_at,
                        timezone_name=timezone_name,
                        idempotency_key=idempotency_key,
                    )
                stopped = self._repetition.stop()
                return {
                    "estimate": stopped,
                    "draft": draft,
                    "confirmation_required": draft is not None,
                }

        result, receipt = self.runtime.dispatch(
            "wellness",
            "repetition_stop",
            stop_and_materialize,
            binding={
                "idempotency_key": idempotency_key,
                "source": "camera-gesture-attention-v1",
                "timezone": timezone_name,
            },
            trace_id=trace_id,
        )
        return {"result": self._payload(result), "receipt": asdict(receipt)}

    def _domain_dispatch(self, capability: str, operation: str, args: dict[str, object]) -> object:
        if capability == "plugin":
            if operation == "status":
                return self.plugin.status()
            if operation == "list":
                return self.plugin.list()
            if operation == "inspect":
                return self.plugin.inspect(str(args["plugin_id"]))
            if operation == "execute":
                return self.plugin.execute(
                    str(args["plugin_id"]),
                    str(args["plugin_operation"]),
                    args.get("payload"),
                )
            return getattr(self.plugin, operation)(str(args["plugin_id"]))
        if capability == "clipboard":
            if operation == "status":
                return self.clipboard.status(self.owner_profile_id, self.workspace_id)
            if operation == "opt_in":
                return self.clipboard.opt_in(self.owner_profile_id, self.workspace_id)
            if operation == "resume":
                return self.clipboard.opt_in(self.owner_profile_id, self.workspace_id)
            return getattr(self.clipboard, operation)(self.owner_profile_id, self.workspace_id)
        if capability == "wellness":
            if operation == "repetition_status":
                with self._repetition_lock:
                    return self._repetition.snapshot()
            if operation == "repetition_start":
                with self._repetition_lock:
                    return self._repetition.start(str(args["activity"]))
            if operation == "repetition_stop":
                return self._stop_repetition_for_model(args)
            if operation == "status":
                return self.wellness.totals(
                    self.owner_profile_id,
                    self.workspace_id,
                    day=str(args["day"]),
                    timezone_name=str(args["timezone"]),
                )
            if operation == "create":
                kind = args.pop("kind")
                if kind != "calorie" and "numeric_value" in args:
                    args["value"] = args.pop("numeric_value")
                method = self.wellness.create_calorie if kind == "calorie" else self.wellness.create_exercise
                return method(self.owner_profile_id, self.workspace_id, **args)
            return getattr(self.wellness, operation)(
                str(args.pop("entry_id")), self.owner_profile_id, self.workspace_id, **args
            )
        if capability == "personalization" and self.personalization is not None:
            interview = OnyxOwnerInterviewV1(self.personalization)
            if operation == "onboarding_status":
                return interview.status()
            if operation == "onboarding_answer":
                return interview.answer(
                    str(args["question_id"]),
                    args["value"],
                )
            if operation == "status":
                return self.personalization.inspect()
            method = "edit" if operation == "update" else "revoke" if operation == "remove" else operation
            return getattr(self.personalization, method)(**args)
        if capability == "social":
            if operation == "generate":
                return generate_caption_draft(
                    CaptionGenerationRequestV1(
                        brief=str(args["brief"]),
                        brand=str(args.get("brand", "Cyryx Labs")),
                        platform=str(args["platform"]),
                        source_refs=tuple(str(item) for item in args.get("source_refs", ())),
                    )
                )
            if operation == "preview":
                return preview_caption(self._social_request(args))
            if operation == "video_inspect":
                return self.social_video.inspect(
                    Path(str(args["media_path"])),
                    workspace_id=self.workspace_id,
                    principal_id=self.owner_profile_id,
                    lease_seconds=float(args.get("lease_seconds", 300.0)),
                ).to_dict()
            if operation == "status":
                digest = str(args.get("request_digest", "")).strip()
                if digest and self.social is not None:
                    return self.social.status(digest)
                return {
                    "schema": "OnyxSocialCapabilityStatus.v1",
                    "caption_generation": "available",
                    "preview": "available",
                    "video_inspection": "available",
                    "publishing": (
                        "owner-cli-ready" if self._official_social_configured else
                        "available" if self.social is not None else "oauth-adapter-required"
                    ),
                    "official_platforms": ["facebook-page-feed-text"] if self._official_social_configured else [],
                    "official_configuration_error": self._official_social_error,
                    "live_publication_certified": False,
                }
        raise PermissionError("capability operation is unavailable")

    def _social_request(self, args: dict[str, object]) -> CaptionRequestV1:
        return CaptionRequestV1(
            workspace_id=self.workspace_id,
            principal_id=self.owner_profile_id,
            account_id=str(args["account_id"]),
            target=str(args["target"]),
            caption=str(args["caption"]),
            media_digests=tuple(str(item) for item in args.get("media_digests", ())),
            provenance=tuple(str(item) for item in args.get("provenance", ())),
            warnings=tuple(str(item) for item in args.get("warnings", ())),
        )

    def _stop_repetition_for_model(self, args: dict[str, object]) -> dict[str, object]:
        with self._repetition_lock:
            if not self._repetition.active:
                raise VisionRepetitionContractError("repetition counter is not active")
            estimate = self._repetition.snapshot()
            draft = None
            if estimate.repetitions > 0:
                draft = self.wellness.create_vision_estimate(
                    self.owner_profile_id,
                    self.workspace_id,
                    kind="exercise",
                    activity=estimate.activity,
                    value=estimate.repetitions,
                    unit="repetitions",
                    occurred_at=str(args["occurred_at"]),
                    timezone_name=str(args["timezone_name"]),
                    idempotency_key=str(args["idempotency_key"]),
                )
            stopped = self._repetition.stop()
        return {
            "estimate": stopped,
            "draft": draft,
            "confirmation_required": draft is not None,
        }

    @staticmethod
    def _payload(value: object) -> object:
        if is_dataclass(value):
            value = asdict(value)
        elif isinstance(value, tuple):
            value = [CapabilityExpansionServiceV1._payload(item) for item in value]
        if isinstance(value, dict):
            return {
                key: CapabilityExpansionServiceV1._payload(item)
                for key, item in value.items()
                if not any(secret in key.casefold() for secret in ("token", "secret", "auth", "credential"))
            }
        return value


def with_installed_local_capabilities_v1(
    settings: Mapping[str, object] | None,
) -> dict[str, object]:
    """Enable shipped local domains while preserving an explicit owner opt-out."""

    configured = dict(settings or {})
    for flag in INSTALLED_LOCAL_DEFAULT_FLAGS:
        configured.setdefault(flag, True)
    return configured


__all__ = [
    "CapabilityExpansionServiceV1",
    "INSTALLED_LOCAL_DEFAULT_FLAGS",
    "with_installed_local_capabilities_v1",
]

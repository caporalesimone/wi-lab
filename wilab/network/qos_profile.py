"""QoS Profile Manager — orchestrates profile execution over QosManager."""

import json
import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional

import jsonschema

from ..models import (
    QosProfile,
    QosProfileMode,
    QosProfileStep,
    QosQualityAdvanced,
)
from .qos import QosManager

logger = logging.getLogger(__name__)

_SCHEMA_FILENAME = "profile.schema.json"


@dataclass
class _ActiveProfile:
    """Runtime state for an active profile on a single interface."""

    profile_id: str
    description: str
    mode: QosProfileMode
    steps: list  # list[QosProfileStep] — kept as list for dataclass compat
    step_index: int = 0
    direction: int = 1  # +1 forward, -1 backward (bounce)
    step_started_at: float = 0.0
    started_at: float = 0.0
    stop_event: threading.Event = field(default_factory=threading.Event)
    thread: Optional[threading.Thread] = None
    active: bool = True


class QosProfileManager:
    """Manages QoS profile catalogue and per-interface profile execution."""

    def __init__(self, catalogue_dir: str) -> None:
        self._catalogue_dir = Path(catalogue_dir)
        self._profiles: Dict[str, QosProfile] = {}
        self._active: Dict[str, _ActiveProfile] = {}  # interface -> _ActiveProfile
        self._lock = threading.Lock()
        self._load_catalogue()
        logger.info(
            "QosProfileManager initialized with %d profiles from %s",
            len(self._profiles),
            self._catalogue_dir,
        )

    # ------------------------------------------------------------------
    # Catalogue
    # ------------------------------------------------------------------

    def _load_catalogue(self) -> None:
        schema_path = self._catalogue_dir / _SCHEMA_FILENAME
        if not schema_path.exists():
            logger.warning("Profile schema not found at %s", schema_path)
            return

        with open(schema_path) as f:
            schema = json.load(f)

        # Collect JSON files: default.json first, then the rest alphabetically
        json_files: list[Path] = []
        default_path = self._catalogue_dir / "default.json"
        if default_path.exists():
            json_files.append(default_path)

        for p in sorted(self._catalogue_dir.glob("*.json")):
            if p.name == _SCHEMA_FILENAME or p.name == "default.json":
                continue
            json_files.append(p)

        for json_file in json_files:
            try:
                with open(json_file) as f:
                    data = json.load(f)
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("Skipping invalid JSON file '%s': %s", json_file.name, exc)
                continue

            try:
                jsonschema.validate(data, schema)
            except jsonschema.ValidationError as exc:
                logger.warning(
                    "Schema validation failed for '%s': %s", json_file.name, exc.message
                )
                continue

            for raw_profile in data:
                pid = raw_profile["id"]
                if pid in self._profiles:
                    logger.warning(
                        "Profile '%s' in '%s' conflicts with an existing entry, skipping",
                        pid,
                        json_file.name,
                    )
                    continue
                steps = [
                    QosProfileStep(
                        duration_sec=s["duration_sec"],
                        quality=s.get("quality"),
                        dl_speed_kbit=s.get("dl_speed_kbit"),
                        ul_speed_kbit=s.get("ul_speed_kbit"),
                        advanced=QosQualityAdvanced(**s["advanced"]) if s.get("advanced") else None,
                    )
                    for s in raw_profile["steps"]
                ]
                self._profiles[pid] = QosProfile(
                    id=pid,
                    description=raw_profile.get("description", ""),
                    mode=QosProfileMode(raw_profile["mode"]),
                    steps=steps,
                )

    # ------------------------------------------------------------------
    # Public API — catalogue
    # ------------------------------------------------------------------

    def list_profiles(self) -> List[QosProfile]:
        return list(self._profiles.values())

    def get_profile(self, profile_id: str) -> Optional[QosProfile]:
        return self._profiles.get(profile_id)

    # ------------------------------------------------------------------
    # Public API — profile execution
    # ------------------------------------------------------------------

    def is_active(self, interface: str) -> bool:
        with self._lock:
            ap = self._active.get(interface)
            return ap is not None and ap.active

    def get_state(self, interface: str) -> Optional[_ActiveProfile]:
        with self._lock:
            return self._active.get(interface)

    def start_profile(
        self,
        interface: str,
        profile: QosProfile,
        qos_manager: QosManager,
    ) -> None:
        with self._lock:
            existing = self._active.get(interface)
            if existing is not None and existing.active:
                raise RuntimeError(f"A profile is already active on {interface}")

            now = time.monotonic()
            ap = _ActiveProfile(
                profile_id=profile.id,
                description=profile.description,
                mode=profile.mode,
                steps=list(profile.steps),
                step_index=0,
                direction=1,
                step_started_at=now,
                started_at=now,
            )
            t = threading.Thread(
                target=self._run_profile,
                args=(interface, ap, qos_manager),
                name=f"qos-profile-{interface}",
                daemon=True,
            )
            ap.thread = t
            self._active[interface] = ap
            t.start()

    def stop_profile(self, interface: str, qos_manager: QosManager) -> None:
        with self._lock:
            ap = self._active.get(interface)
            if ap is None:
                return

        ap.stop_event.set()
        if ap.thread is not None:
            ap.thread.join(timeout=5)

        try:
            qos_manager.clear_qos(interface)
        except Exception as exc:
            logger.warning("Failed to clear QoS on %s: %s", interface, exc)

        with self._lock:
            self._active.pop(interface, None)

    # ------------------------------------------------------------------
    # Inline / generated profile helper
    # ------------------------------------------------------------------

    @staticmethod
    def build_inline_profile(
        download_speed_kbit: Optional[int] = None,
        upload_speed_kbit: Optional[int] = None,
        download_quality: Optional[int] = None,
        upload_quality: Optional[int] = None,
        advanced: Optional[QosQualityAdvanced] = None,
    ) -> QosProfile:
        """Create an ephemeral hold profile from inline QoS parameters."""
        # Map symmetric quality fields into the step model
        quality = download_quality if download_quality is not None else upload_quality
        step = QosProfileStep(
            duration_sec=1,  # hold mode ignores duration on last (only) step
            quality=quality if advanced is None else None,
            dl_speed_kbit=download_speed_kbit,
            ul_speed_kbit=upload_speed_kbit,
            advanced=advanced,
        )
        pid = f"{uuid.uuid4().hex[:8]}:generated_static"
        return QosProfile(
            id=pid,
            description="Inline static QoS profile",
            mode=QosProfileMode.hold,
            steps=[step],
        )

    # ------------------------------------------------------------------
    # Thread target
    # ------------------------------------------------------------------

    def _run_profile(
        self,
        interface: str,
        ap: _ActiveProfile,
        qos_manager: QosManager,
    ) -> None:
        try:
            while not ap.stop_event.is_set():
                step: QosProfileStep = ap.steps[ap.step_index]
                ap.step_started_at = time.monotonic()

                # Apply step — explicitly set all 6 fields for isolation
                self._apply_step(interface, step, qos_manager)

                # Wait for step duration (or stop event)
                is_last = self._is_last_step(ap)

                if is_last and ap.mode == QosProfileMode.hold:
                    # Hold indefinitely on last step
                    ap.stop_event.wait()
                    break
                else:
                    interrupted = ap.stop_event.wait(timeout=step.duration_sec)
                    if interrupted:
                        break

                # Advance step index
                if not self._advance_step(ap):
                    # once mode: finished
                    break
        except Exception as exc:
            logger.error("Profile execution error on %s: %s", interface, exc)
        finally:
            # Mark inactive
            ap.active = False
            # For 'once' mode, clear QoS when the sequence finishes naturally
            if not ap.stop_event.is_set():
                try:
                    qos_manager.clear_qos(interface)
                except Exception as exc:
                    logger.warning("Failed to clear QoS after profile end on %s: %s", interface, exc)

    @staticmethod
    def _apply_step(
        interface: str,
        step: QosProfileStep,
        qos_manager: QosManager,
    ) -> None:
        """Apply a single step to the interface via QosManager.

        All 6 fields are set explicitly to enforce step isolation
        (no carry-over from previous step).
        """
        dl_quality = step.quality
        ul_quality = step.quality
        dl_advanced = step.advanced
        ul_advanced = step.advanced

        qos_manager.apply_qos(
            interface,
            download_speed_kbit=step.dl_speed_kbit,
            upload_speed_kbit=step.ul_speed_kbit,
            download_quality=dl_quality,
            upload_quality=ul_quality,
            download_quality_advanced=dl_advanced,
            upload_quality_advanced=ul_advanced,
        )

    @staticmethod
    def _is_last_step(ap: _ActiveProfile) -> bool:
        if ap.direction == 1:
            return ap.step_index == len(ap.steps) - 1
        else:
            return ap.step_index == 0

    @staticmethod
    def _advance_step(ap: _ActiveProfile) -> bool:
        """Advance step index. Returns False if the profile sequence is finished."""
        n = len(ap.steps)

        if ap.mode == QosProfileMode.loop:
            ap.step_index = (ap.step_index + 1) % n
            return True

        elif ap.mode == QosProfileMode.bounce:
            next_idx = ap.step_index + ap.direction
            if next_idx < 0:
                ap.direction = 1
                ap.step_index = 1 if n > 1 else 0
            elif next_idx >= n:
                ap.direction = -1
                ap.step_index = n - 2 if n > 2 else 0
            else:
                ap.step_index = next_idx
            return True

        elif ap.mode == QosProfileMode.once:
            if ap.step_index >= n - 1:
                return False
            ap.step_index += 1
            return True

        elif ap.mode == QosProfileMode.hold:
            if ap.step_index >= n - 1:
                return False  # will be caught by hold logic above
            ap.step_index += 1
            return True

        return False

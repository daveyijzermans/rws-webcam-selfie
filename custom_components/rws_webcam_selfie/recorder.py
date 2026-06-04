"""Proximity-driven HLS recorder.

Watches a single device_tracker entity. For every enabled camera, computes the
distance to the device. When the device crosses INTO the configured radius an
ffmpeg subprocess is spawned to record the camera's HLS stream to disk. When
the device leaves the radius (or the max-duration safety cap is hit) the
subprocess is terminated and the recording is finalised.
"""
from __future__ import annotations

import asyncio
import logging
import os
import shutil
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import Event, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_send
from homeassistant.helpers.event import async_track_state_change_event
from homeassistant.util import slugify
from homeassistant.util.location import distance

from .const import (
    ATTR_CAMERA_ID,
    ATTR_DURATION,
    CAMERAS,
    CONF_DEVICE_TRACKER,
    CONF_ENABLED_CAMERAS,
    CONF_FFMPEG_PATH,
    CONF_MAX_DURATION,
    CONF_MEDIA_SUBDIR,
    CONF_RADIUS,
    DEFAULT_FFMPEG_PATH,
    DEFAULT_MAX_DURATION,
    DEFAULT_MEDIA_SUBDIR,
    DEFAULT_RADIUS,
    DOMAIN,
    EVENT_RECORDING_COMPLETE,
    EVENT_RECORDING_FAILED,
    EVENT_RECORDING_STARTED,
    hls_url,
)

_LOGGER = logging.getLogger(__name__)

SIGNAL_PROXIMITY = f"{DOMAIN}_proximity_{{entry_id}}_{{cam_id}}"


@dataclass
class _ActiveRecording:
    cam: dict
    path: Path
    process: asyncio.subprocess.Process
    started_at: datetime
    timeout_handle: asyncio.TimerHandle | None = None
    finished: asyncio.Event = field(default_factory=asyncio.Event)


class ProximityRecorder:
    """Owns the device_tracker subscription and all in-flight recordings."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self._unsub = None
        self._active: dict[int, _ActiveRecording] = {}
        # Whether each enabled camera currently considers the tracker in-range.
        self._in_range: dict[int, bool] = {}

    # ------------------------------------------------------------------ config
    @property
    def _tracker_entity(self) -> str:
        return self.entry.data[CONF_DEVICE_TRACKER]

    @property
    def _radius(self) -> float:
        return float(self.entry.options.get(CONF_RADIUS, DEFAULT_RADIUS))

    @property
    def _max_duration(self) -> int:
        return int(self.entry.options.get(CONF_MAX_DURATION, DEFAULT_MAX_DURATION))

    @property
    def _enabled_camera_ids(self) -> set[int]:
        return {
            int(x) for x in self.entry.options.get(CONF_ENABLED_CAMERAS, [])
        }

    @property
    def _ffmpeg(self) -> str:
        return self.entry.options.get(CONF_FFMPEG_PATH, DEFAULT_FFMPEG_PATH)

    @property
    def _media_root(self) -> Path:
        subdir = self.entry.options.get(CONF_MEDIA_SUBDIR, DEFAULT_MEDIA_SUBDIR)
        return Path(self.hass.config.path("media")) / subdir

    # ------------------------------------------------------------------- start
    async def async_start(self) -> None:
        self._media_root.mkdir(parents=True, exist_ok=True)
        if not shutil.which(self._ffmpeg) and not Path(self._ffmpeg).is_file():
            _LOGGER.warning(
                "ffmpeg binary %r not found on PATH; recordings will fail until "
                "ffmpeg is installed or the path is corrected in options",
                self._ffmpeg,
            )
        self._unsub = async_track_state_change_event(
            self.hass, [self._tracker_entity], self._handle_tracker_event
        )
        # Evaluate once at startup so binary sensors initialise correctly.
        state = self.hass.states.get(self._tracker_entity)
        if state is not None:
            await self._evaluate(state)

    async def async_stop(self) -> None:
        if self._unsub is not None:
            self._unsub()
            self._unsub = None
        await asyncio.gather(
            *(self._stop_recording(cam_id) for cam_id in list(self._active.keys())),
            return_exceptions=True,
        )

    # ------------------------------------------------------------ tracker hook
    @callback
    def _handle_tracker_event(self, event: Event) -> None:
        new_state = event.data.get("new_state")
        if new_state is None:
            return
        self.hass.async_create_task(self._evaluate(new_state))

    async def _evaluate(self, state) -> None:
        lat = state.attributes.get("latitude")
        lon = state.attributes.get("longitude")
        if lat is None or lon is None:
            return

        for cam in CAMERAS:
            if cam["id"] not in self._enabled_camera_ids:
                continue
            d = distance(lat, lon, cam["latitude"], cam["longitude"])
            in_range = d is not None and d <= self._radius
            was_in_range = self._in_range.get(cam["id"], False)
            self._in_range[cam["id"]] = in_range

            async_dispatcher_send(
                self.hass,
                SIGNAL_PROXIMITY.format(entry_id=self.entry.entry_id, cam_id=cam["id"]),
                in_range,
                d,
            )

            if in_range and not was_in_range:
                await self._start_recording(cam, reason="zone_entry")
            elif not in_range and was_in_range:
                await self._stop_recording(cam["id"], reason="zone_exit")

    # ------------------------------------------------------------- recording
    async def manual_start(self, camera_id: int, duration: int | None = None) -> None:
        cam = next((c for c in CAMERAS if c["id"] == camera_id), None)
        if cam is None:
            raise ValueError(f"Unknown camera id {camera_id}")
        await self._start_recording(cam, reason="manual", override_duration=duration)

    async def manual_stop(self, camera_id: int) -> None:
        await self._stop_recording(camera_id, reason="manual")

    async def _start_recording(
        self, cam: dict, reason: str, override_duration: int | None = None
    ) -> None:
        if cam["id"] in self._active:
            return  # already recording this camera

        ts = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        fname = f"{ts}_{slugify(cam['road'])}_{slugify(cam['near'])}_{cam['id']}.mp4"
        path = self._media_root / fname
        url = hls_url(cam)
        duration = override_duration or self._max_duration

        args = [
            self._ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel", "warning",
            "-y",
            "-headers", "Referer: https://www.rwsverkeersinfo.nl/\r\n",
            "-i", url,
            "-t", str(duration),
            "-c", "copy",
            "-movflags", "+faststart",
            str(path),
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE
            )
        except FileNotFoundError:
            _LOGGER.error("ffmpeg binary %r not found", self._ffmpeg)
            self.hass.bus.async_fire(
                EVENT_RECORDING_FAILED,
                {ATTR_CAMERA_ID: cam["id"], "error": "ffmpeg_not_found"},
            )
            return

        rec = _ActiveRecording(cam=cam, path=path, process=proc, started_at=datetime.now())
        self._active[cam["id"]] = rec

        # Safety-net timer in case the tracker never updates again.
        rec.timeout_handle = self.hass.loop.call_later(
            duration + 5,
            lambda: self.hass.async_create_task(
                self._stop_recording(cam["id"], reason="max_duration")
            ),
        )

        self.hass.bus.async_fire(
            EVENT_RECORDING_STARTED,
            {
                ATTR_CAMERA_ID: cam["id"],
                "path": str(path),
                "reason": reason,
                "road": cam["road"],
                "near": cam["near"],
                "stream_url": url,
            },
        )
        _LOGGER.info(
            "Started recording cam %s (%s %s) -> %s (reason=%s)",
            cam["id"], cam["road"], cam["near"], path, reason,
        )

        self.hass.async_create_task(self._await_finish(rec))

    async def _await_finish(self, rec: _ActiveRecording) -> None:
        stdout, stderr = await rec.process.communicate()
        rec.finished.set()
        if rec.timeout_handle:
            rec.timeout_handle.cancel()
        # Drop from active set only if it's still us (manual_stop may have replaced).
        if self._active.get(rec.cam["id"]) is rec:
            self._active.pop(rec.cam["id"], None)

        duration = (datetime.now() - rec.started_at).total_seconds()
        exists = rec.path.is_file() and rec.path.stat().st_size > 0

        if rec.process.returncode == 0 or exists:
            self.hass.bus.async_fire(
                EVENT_RECORDING_COMPLETE,
                {
                    ATTR_CAMERA_ID: rec.cam["id"],
                    ATTR_DURATION: duration,
                    "path": str(rec.path),
                    "size_bytes": rec.path.stat().st_size if exists else 0,
                    "road": rec.cam["road"],
                    "near": rec.cam["near"],
                },
            )
            _LOGGER.info(
                "Recording finished cam %s after %.1fs -> %s",
                rec.cam["id"], duration, rec.path,
            )
        else:
            err = (stderr or b"").decode("utf-8", "ignore")[-500:]
            self.hass.bus.async_fire(
                EVENT_RECORDING_FAILED,
                {
                    ATTR_CAMERA_ID: rec.cam["id"],
                    "error": "ffmpeg_failed",
                    "returncode": rec.process.returncode,
                    "stderr_tail": err,
                },
            )
            _LOGGER.warning(
                "Recording failed cam %s rc=%s: %s",
                rec.cam["id"], rec.process.returncode, err,
            )

    async def _stop_recording(self, camera_id: int, reason: str = "") -> None:
        rec = self._active.get(camera_id)
        if rec is None:
            return
        if rec.process.returncode is not None:
            return
        try:
            rec.process.terminate()
        except ProcessLookupError:
            return
        try:
            await asyncio.wait_for(rec.finished.wait(), timeout=10)
        except asyncio.TimeoutError:
            _LOGGER.warning("ffmpeg for cam %s did not exit; killing", camera_id)
            try:
                rec.process.kill()
            except ProcessLookupError:
                pass
            await rec.finished.wait()

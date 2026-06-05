"""Camera entities for each enabled RWS webcam."""
from __future__ import annotations

import logging
import time

from aiohttp import ClientTimeout

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url

from .const import CAMERAS, CONF_ENABLED_CAMERAS, DOMAIN
from .views import UPSTREAM_HEADERS, camera_proxy_path

_LOGGER = logging.getLogger(__name__)

# Snapshots are only there so map pins / camera cards aren't blank — the image
# content has no functional value. Keep upstream hits very rare to stay polite
# to stream.inmoves.nl and avoid being flagged for automated scraping.
SNAPSHOT_CACHE_TTL = 3 * 60 * 60  # seconds


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    enabled = set(entry.options.get(CONF_ENABLED_CAMERAS, []))
    entities = [
        RWSWebcamCamera(entry, cam) for cam in CAMERAS if str(cam["id"]) in enabled
    ]
    async_add_entities(entities)


class RWSWebcamCamera(Camera):
    """A Rijkswaterstaat motorway webcam exposed as an HA Camera entity."""

    _attr_supported_features = CameraEntityFeature.STREAM
    _attr_has_entity_name = True
    _attr_icon = "mdi:cctv"

    def __init__(self, entry: ConfigEntry, cam: dict) -> None:
        super().__init__()
        self._cam = cam
        self._entry_id = entry.entry_id
        self._snapshot_bytes: bytes | None = None
        self._snapshot_fetched_at: float = 0.0
        self._attr_unique_id = f"{DOMAIN}_camera_{cam['id']}"
        self._attr_name = f"{cam['road']} {cam['near']}"
        self._attr_extra_state_attributes = {
            "camera_id": cam["id"],
            "road": cam["road"],
            "near": cam["near"],
            "latitude": cam["latitude"],
            "longitude": cam["longitude"],
            "description": cam["description"],
            "embed_url": cam["embed_url"],
        }
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"camera_{cam['id']}")},
            name=f"RWS {cam['road']} {cam['near']}",
            manufacturer="Rijkswaterstaat / INMOVES",
            model="Motorway webcam",
            configuration_url=cam["embed_url"],
        )

    async def async_camera_image(
        self, width: int | None = None, height: int | None = None
    ) -> bytes | None:
        """Return the JPEG snapshot, refreshing at most once per TTL window.

        Snapshots only exist so the map pin / camera card thumbnail isn't
        blank; staleness doesn't matter. We cache aggressively to avoid
        hammering stream.inmoves.nl.
        """
        now = time.monotonic()
        if (
            self._snapshot_bytes is not None
            and now - self._snapshot_fetched_at < SNAPSHOT_CACHE_TTL
        ):
            return self._snapshot_bytes

        session = async_get_clientsession(self.hass)
        try:
            async with session.get(
                self._cam["static_url"],
                headers=UPSTREAM_HEADERS,
                timeout=ClientTimeout(total=10),
            ) as resp:
                if resp.status != 200:
                    _LOGGER.debug(
                        "Snapshot for cam %s returned HTTP %s",
                        self._cam["id"], resp.status,
                    )
                    # Keep serving the previous image (if any) until the
                    # next TTL window — don't fall through to None.
                    self._snapshot_fetched_at = now
                    return self._snapshot_bytes
                self._snapshot_bytes = await resp.read()
                self._snapshot_fetched_at = now
                return self._snapshot_bytes
        except Exception as err:  # noqa: BLE001
            _LOGGER.debug("Snapshot fetch failed for cam %s: %s", self._cam["id"], err)
            self._snapshot_fetched_at = now
            return self._snapshot_bytes

    async def stream_source(self) -> str | None:
        # stream.inmoves.nl requires a Referer header that PyAV cannot send,
        # so we point at our in-process proxy view which adds the header.
        base = get_url(
            self.hass,
            allow_internal=True,
            allow_external=False,
            allow_ip=True,
            require_current_request=False,
            prefer_external=False,
        )
        return f"{base}{camera_proxy_path(self._cam)}"

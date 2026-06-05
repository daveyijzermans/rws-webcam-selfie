"""Camera entities for each enabled RWS webcam."""
from __future__ import annotations

from homeassistant.components.camera import Camera, CameraEntityFeature
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.helpers.network import get_url

from .const import CAMERAS, CONF_ENABLED_CAMERAS, DOMAIN
from .views import camera_proxy_path


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

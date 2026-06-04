"""Per-camera in-range binary sensors."""
from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity import DeviceInfo
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import CAMERAS, CONF_ENABLED_CAMERAS, DOMAIN
from .recorder import SIGNAL_PROXIMITY


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    enabled = set(entry.options.get(CONF_ENABLED_CAMERAS, []))
    async_add_entities(
        RWSInRange(entry, cam) for cam in CAMERAS if str(cam["id"]) in enabled
    )


class RWSInRange(BinarySensorEntity):
    """True while the tracked device is within the configured radius of the camera."""

    _attr_has_entity_name = True
    _attr_device_class = BinarySensorDeviceClass.PRESENCE

    def __init__(self, entry: ConfigEntry, cam: dict) -> None:
        self._cam = cam
        self._entry_id = entry.entry_id
        self._attr_unique_id = f"{DOMAIN}_in_range_{cam['id']}"
        self._attr_name = "In range"
        self._attr_is_on = False
        self._attr_extra_state_attributes = {"distance_m": None}
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, f"camera_{cam['id']}")},
        )

    async def async_added_to_hass(self) -> None:
        from homeassistant.helpers.dispatcher import async_dispatcher_connect

        self.async_on_remove(
            async_dispatcher_connect(
                self.hass,
                SIGNAL_PROXIMITY.format(entry_id=self._entry_id, cam_id=self._cam["id"]),
                self._handle_update,
            )
        )

    @callback
    def _handle_update(self, in_range: bool, distance_m: float | None) -> None:
        self._attr_is_on = in_range
        self._attr_extra_state_attributes = {"distance_m": distance_m}
        self.async_write_ha_state()

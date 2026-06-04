"""RWS Webcam Selfie integration.

Records a clip from a Rijkswaterstaat motorway webcam whenever a tracked
device (typically a phone or car) gets within a configurable radius of the
camera, so you end up with a video of yourself driving past.
"""
from __future__ import annotations

import logging

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.const import Platform

from .const import DOMAIN
from .recorder import ProximityRecorder
from .services import async_register_services, async_unregister_services

_LOGGER = logging.getLogger(__name__)

PLATFORMS: list[Platform] = [Platform.CAMERA, Platform.BINARY_SENSOR]


async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up RWS Webcam Selfie from a config entry."""
    hass.data.setdefault(DOMAIN, {})

    recorder = ProximityRecorder(hass, entry)
    await recorder.async_start()
    hass.data[DOMAIN][entry.entry_id] = {"recorder": recorder}

    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    async_register_services(hass)

    entry.async_on_unload(entry.add_update_listener(_async_update_listener))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    data = hass.data[DOMAIN].pop(entry.entry_id, None)
    if data:
        await data["recorder"].async_stop()
    if not hass.data[DOMAIN]:
        async_unregister_services(hass)
    return unload_ok


async def _async_update_listener(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Reload the entry when options change."""
    await hass.config_entries.async_reload(entry.entry_id)

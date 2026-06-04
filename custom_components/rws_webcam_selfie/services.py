"""Service registration for manual start/stop."""
from __future__ import annotations

import voluptuous as vol

from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_CAMERA_ID,
    ATTR_DURATION,
    DOMAIN,
    SERVICE_START_RECORDING,
    SERVICE_STOP_RECORDING,
)

START_SCHEMA = vol.Schema(
    {
        vol.Required(ATTR_CAMERA_ID): vol.Coerce(int),
        vol.Optional(ATTR_DURATION): vol.All(vol.Coerce(int), vol.Range(min=5, max=1800)),
    }
)

STOP_SCHEMA = vol.Schema({vol.Required(ATTR_CAMERA_ID): vol.Coerce(int)})


def _all_recorders(hass: HomeAssistant):
    return [d["recorder"] for d in hass.data.get(DOMAIN, {}).values()]


def async_register_services(hass: HomeAssistant) -> None:
    if hass.services.has_service(DOMAIN, SERVICE_START_RECORDING):
        return

    async def _start(call: ServiceCall) -> None:
        cam_id = call.data[ATTR_CAMERA_ID]
        duration = call.data.get(ATTR_DURATION)
        for rec in _all_recorders(hass):
            await rec.manual_start(cam_id, duration=duration)

    async def _stop(call: ServiceCall) -> None:
        cam_id = call.data[ATTR_CAMERA_ID]
        for rec in _all_recorders(hass):
            await rec.manual_stop(cam_id)

    hass.services.async_register(DOMAIN, SERVICE_START_RECORDING, _start, schema=START_SCHEMA)
    hass.services.async_register(DOMAIN, SERVICE_STOP_RECORDING, _stop, schema=STOP_SCHEMA)


def async_unregister_services(hass: HomeAssistant) -> None:
    for s in (SERVICE_START_RECORDING, SERVICE_STOP_RECORDING):
        if hass.services.has_service(DOMAIN, s):
            hass.services.async_remove(DOMAIN, s)

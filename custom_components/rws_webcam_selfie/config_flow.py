"""Config flow for RWS Webcam Selfie."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import callback
from homeassistant.helpers import selector

from .const import (
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
)


def _camera_options() -> list[selector.SelectOptionDict]:
    return [
        selector.SelectOptionDict(
            value=str(c["id"]),
            label=f"{c['road']} {c['near']} (#{c['id']})",
        )
        for c in CAMERAS
    ]


def _all_camera_ids() -> list[str]:
    return [str(c["id"]) for c in CAMERAS]


class RWSWebcamSelfieConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Initial setup flow."""

    VERSION = 1

    async def async_step_user(self, user_input: dict[str, Any] | None = None):
        if self._async_current_entries():
            return self.async_abort(reason="single_instance_allowed")

        errors: dict[str, str] = {}
        if user_input is not None:
            return self.async_create_entry(
                title="RWS Webcam Selfie",
                data={CONF_DEVICE_TRACKER: user_input[CONF_DEVICE_TRACKER]},
                options={
                    CONF_RADIUS: user_input[CONF_RADIUS],
                    CONF_MAX_DURATION: user_input[CONF_MAX_DURATION],
                    CONF_ENABLED_CAMERAS: user_input[CONF_ENABLED_CAMERAS],
                    CONF_MEDIA_SUBDIR: user_input[CONF_MEDIA_SUBDIR],
                    CONF_FFMPEG_PATH: user_input[CONF_FFMPEG_PATH],
                },
            )

        schema = vol.Schema(
            {
                vol.Required(CONF_DEVICE_TRACKER): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="device_tracker")
                ),
                vol.Required(CONF_RADIUS, default=DEFAULT_RADIUS): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=20000, step=100, unit_of_measurement="m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAX_DURATION, default=DEFAULT_MAX_DURATION
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=1800, step=10, unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLED_CAMERAS, default=_all_camera_ids()
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_camera_options(),
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_MEDIA_SUBDIR, default=DEFAULT_MEDIA_SUBDIR
                ): str,
                vol.Required(
                    CONF_FFMPEG_PATH, default=DEFAULT_FFMPEG_PATH
                ): str,
            }
        )
        return self.async_show_form(step_id="user", data_schema=schema, errors=errors)

    @staticmethod
    @callback
    def async_get_options_flow(entry: config_entries.ConfigEntry):
        return RWSWebcamSelfieOptionsFlow(entry)


class RWSWebcamSelfieOptionsFlow(config_entries.OptionsFlow):
    """Options flow."""

    def __init__(self, entry: config_entries.ConfigEntry) -> None:
        self.entry = entry

    async def async_step_init(self, user_input: dict[str, Any] | None = None):
        if user_input is not None:
            return self.async_create_entry(title="", data=user_input)

        opts = self.entry.options
        schema = vol.Schema(
            {
                vol.Required(
                    CONF_RADIUS, default=opts.get(CONF_RADIUS, DEFAULT_RADIUS)
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=100, max=20000, step=100, unit_of_measurement="m",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_MAX_DURATION,
                    default=opts.get(CONF_MAX_DURATION, DEFAULT_MAX_DURATION),
                ): selector.NumberSelector(
                    selector.NumberSelectorConfig(
                        min=10, max=1800, step=10, unit_of_measurement="s",
                        mode=selector.NumberSelectorMode.BOX,
                    )
                ),
                vol.Required(
                    CONF_ENABLED_CAMERAS,
                    default=opts.get(CONF_ENABLED_CAMERAS, _all_camera_ids()),
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=_camera_options(),
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
                vol.Required(
                    CONF_MEDIA_SUBDIR,
                    default=opts.get(CONF_MEDIA_SUBDIR, DEFAULT_MEDIA_SUBDIR),
                ): str,
                vol.Required(
                    CONF_FFMPEG_PATH,
                    default=opts.get(CONF_FFMPEG_PATH, DEFAULT_FFMPEG_PATH),
                ): str,
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

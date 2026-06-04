"""HTTP view that proxies HLS requests to stream.inmoves.nl.

PyAV (used by HA's stream component) cannot inject a Referer header, but
stream.inmoves.nl returns 404 without it. This view forwards every request
under /api/rws_webcam_selfie/<cam_id>/<path> to the upstream HLS endpoint,
adding the Referer/UA headers, and streams the response back. The HLS
playlists use relative URLs so a single catch-all proxy is enough.
"""
from __future__ import annotations

import logging

from aiohttp import ClientTimeout, web

from homeassistant.components.http import HomeAssistantView
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .const import CAMERAS

_LOGGER = logging.getLogger(__name__)

PROXY_URL_PREFIX = "/api/rws_webcam_selfie/stream"
UPSTREAM_HEADERS = {
    "Referer": "https://www.rwsverkeersinfo.nl/",
    "User-Agent": "Mozilla/5.0",
}


def camera_proxy_path(cam: dict) -> str:
    """Return the proxy URL path (without host) for a camera's playlist."""
    return f"{PROXY_URL_PREFIX}/{cam['id']}/playlist.m3u8"


class RWSWebcamProxyView(HomeAssistantView):
    """Public proxy: PyAV cannot send auth headers, so we don't require any."""

    url = PROXY_URL_PREFIX + "/{cam_id}/{tail:.+}"
    name = "api:rws_webcam_selfie:proxy"
    requires_auth = False

    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._by_id = {str(c["id"]): c for c in CAMERAS}

    async def get(self, request: web.Request, cam_id: str, tail: str) -> web.StreamResponse:
        cam = self._by_id.get(cam_id)
        if cam is None:
            return web.Response(status=404, text="Unknown camera")

        upstream = (
            f"https://stream.inmoves.nl/{cam['hls_app']}/"
            f"{cam['hls_streamname']}/{tail}"
        )
        session = async_get_clientsession(self.hass)
        try:
            upstream_resp = await session.get(
                upstream,
                headers=UPSTREAM_HEADERS,
                timeout=ClientTimeout(total=15),
                allow_redirects=True,
            )
        except Exception as err:  # noqa: BLE001
            _LOGGER.warning("Upstream fetch failed for %s: %s", upstream, err)
            return web.Response(status=502, text=f"upstream error: {err}")

        response = web.StreamResponse(status=upstream_resp.status)
        ctype = upstream_resp.headers.get("Content-Type")
        if ctype:
            response.content_type = ctype.split(";")[0].strip()
        # Allow long-lived HLS playlists to stream through cleanly.
        await response.prepare(request)
        try:
            async for chunk in upstream_resp.content.iter_chunked(64 * 1024):
                await response.write(chunk)
        finally:
            upstream_resp.release()
        return response

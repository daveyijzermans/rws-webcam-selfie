"""Media source that exposes drive-past recordings as a top-level tile.

Discovery: the `media_source` integration auto-loads any custom_component that
exposes an `async_get_media_source(hass)` coroutine returning a MediaSource.
The returned source appears as its own tile in the Media browser (alongside
"My media", "Radio Browser", etc.) — no config required.

Files live under <config>/<media_subdir>/ (default `rws_webcam_selfie/`) and
are served back to the frontend by a small HomeAssistantView. aiohttp's
FileResponse honours HTTP Range requests automatically so seeking inside an
MP4 works without extra code.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path

from aiohttp import web

from homeassistant.components import http
from homeassistant.components.media_player import MediaClass
from homeassistant.components.media_source import (
    BrowseMediaSource,
    MediaSource,
    MediaSourceItem,
    PlayMedia,
    Unresolvable,
)
from homeassistant.core import HomeAssistant

from .const import DOMAIN

_LOGGER = logging.getLogger(__name__)

URL_PREFIX = f"/api/{DOMAIN}_media"

# Recordings are named YYYY-MM-DD_HH-MM-SS_<road>_<near>_<id>.mp4 by recorder.py.
_FILE_RE = re.compile(
    r"^(?P<ts>\d{4}-\d{2}-\d{2}_\d{2}-\d{2}-\d{2})_"
    r"(?P<road>[^_]+)_(?P<near>.+?)_(?P<id>\d+)\.mp4$"
)


async def async_get_media_source(hass: HomeAssistant) -> "RWSMediaSource":
    """Return the singleton MediaSource and register its file-serving view."""
    source = RWSMediaSource(hass)
    if not hass.data.get(f"{DOMAIN}_media_view_registered"):
        hass.http.register_view(RWSMediaView(source))
        hass.data[f"{DOMAIN}_media_view_registered"] = True
    return source


class RWSMediaSource(MediaSource):
    """Browse drive-past recordings across every active config entry."""

    name = "RWS Webcam Selfie"

    def __init__(self, hass: HomeAssistant) -> None:
        super().__init__(DOMAIN)
        self.hass = hass

    # -------------------------------------------------------------- helpers
    def _roots(self) -> list[Path]:
        """All on-disk recording directories belonging to active entries."""
        roots: list[Path] = []
        for entry_data in self.hass.data.get(DOMAIN, {}).values():
            if not isinstance(entry_data, dict):
                continue
            recorder = entry_data.get("recorder")
            if recorder is None:
                continue
            root = recorder._media_root  # noqa: SLF001 — internal by design
            if root.is_dir():
                roots.append(root)
        return roots

    def _locate(self, filename: str) -> Path | None:
        if "/" in filename or ".." in filename or not filename.endswith(".mp4"):
            return None
        for root in self._roots():
            candidate = root / filename
            if candidate.is_file():
                return candidate
        return None

    def _list_files(self) -> list[tuple[str, float]]:
        items: list[tuple[str, float]] = []
        for root in self._roots():
            for p in root.glob("*.mp4"):
                try:
                    items.append((p.name, p.stat().st_mtime))
                except OSError:
                    continue
        items.sort(key=lambda x: x[1], reverse=True)
        return items

    # -------------------------------------------------------------- browse
    async def async_browse_media(self, item: MediaSourceItem) -> BrowseMediaSource:
        if item.identifier:
            path = await self.hass.async_add_executor_job(self._locate, item.identifier)
            if path is None:
                raise Unresolvable(f"Recording not found: {item.identifier}")
            return _leaf(item.identifier)

        files = await self.hass.async_add_executor_job(self._list_files)
        root_node = BrowseMediaSource(
            domain=DOMAIN,
            identifier="",
            media_class=MediaClass.DIRECTORY,
            media_content_type="",
            title=self.name,
            can_play=False,
            can_expand=True,
            children_media_class=MediaClass.VIDEO,
        )
        root_node.children = [_leaf(name) for name, _ in files]
        return root_node

    # -------------------------------------------------------------- resolve
    async def async_resolve_media(self, item: MediaSourceItem) -> PlayMedia:
        path = await self.hass.async_add_executor_job(self._locate, item.identifier)
        if path is None:
            raise Unresolvable(f"Recording not found: {item.identifier}")
        return PlayMedia(f"{URL_PREFIX}/{item.identifier}", "video/mp4")


def _leaf(filename: str) -> BrowseMediaSource:
    return BrowseMediaSource(
        domain=DOMAIN,
        identifier=filename,
        media_class=MediaClass.VIDEO,
        media_content_type="video/mp4",
        title=_pretty_title(filename),
        can_play=True,
        can_expand=False,
    )


def _pretty_title(filename: str) -> str:
    m = _FILE_RE.match(filename)
    if not m:
        return filename
    try:
        dt = datetime.strptime(m.group("ts"), "%Y-%m-%d_%H-%M-%S")
        ts = dt.strftime("%Y-%m-%d %H:%M")
    except ValueError:
        ts = m.group("ts")
    road = m.group("road").upper()
    near = m.group("near").replace("_", " ")
    return f"{ts}  {road} {near}"


class RWSMediaView(http.HomeAssistantView):
    """Streams MP4 files back to the frontend with Range support."""

    url = URL_PREFIX + "/{filename}"
    name = f"api:{DOMAIN}:media"
    requires_auth = True

    def __init__(self, source: RWSMediaSource) -> None:
        self.source = source

    async def get(self, request: web.Request, filename: str) -> web.FileResponse:
        path = await self.source.hass.async_add_executor_job(
            self.source._locate, filename
        )
        if path is None:
            raise web.HTTPNotFound
        return web.FileResponse(path)

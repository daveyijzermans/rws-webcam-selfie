#!/usr/bin/env python3
"""Regenerate custom_components/rws_webcam_selfie/const.py from the live API.

Fetches https://api.rwsverkeersinfo.nl/api/cameras/ and resolves each camera's
HLS streamname by scraping its embed page, then rewrites the CAMERAS list in
const.py in place.
"""
from __future__ import annotations

import concurrent.futures
import json
import pathlib
import re
import sys
import urllib.request

API_URL = "https://api.rwsverkeersinfo.nl/api/cameras/"
HEADERS = {
    "User-Agent": "Mozilla/5.0 rws-webcam-selfie/refresh",
    "Referer": "https://www.rwsverkeersinfo.nl/",
}
CONST_PATH = (
    pathlib.Path(__file__).resolve().parent.parent
    / "custom_components"
    / "rws_webcam_selfie"
    / "const.py"
)


def _fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=15) as resp:
        return resp.read().decode("utf-8", "ignore")


def _resolve(cam: dict) -> dict:
    html = _fetch(cam["stream_url"])
    m = re.search(r"doShowCam\(\s*'([^']+)'\s*,\s*'([^']+)'", html)
    if not m:
        raise RuntimeError(f"streamname not found for camera {cam['id']} ({cam['stream_url']})")
    cam = dict(cam)
    cam["hls_app"], cam["hls_streamname"] = m.group(1), m.group(2)
    return cam


def _format_block(cams: list[dict]) -> str:
    parts = []
    for c in cams:
        parts.append(
            "    {\n"
            f"        \"id\": {c['id']},\n"
            f"        \"latitude\": {float(c['latitude'])},\n"
            f"        \"longitude\": {float(c['longitude'])},\n"
            f"        \"road\": {json.dumps(c['road'])},\n"
            f"        \"near\": {json.dumps(c['near'])},\n"
            f"        \"description\": {json.dumps(c.get('location_description') or '')},\n"
            f"        \"embed_url\": {json.dumps(c['stream_url'])},\n"
            f"        \"static_url\": {json.dumps(c['static_url'])},\n"
            f"        \"hls_app\": {json.dumps(c['hls_app'])},\n"
            f"        \"hls_streamname\": {json.dumps(c['hls_streamname'])},\n"
            "    },"
        )
    return "\n".join(parts)


def main() -> int:
    raw = json.loads(_fetch(API_URL))
    if not isinstance(raw, list):
        print("Unexpected payload shape:", type(raw), file=sys.stderr)
        return 2
    print(f"Fetched {len(raw)} cameras; resolving streamnames...")
    with concurrent.futures.ThreadPoolExecutor(max_workers=8) as ex:
        resolved = list(ex.map(_resolve, raw))
    resolved.sort(key=lambda c: (c["road"], c["near"]))

    source = CONST_PATH.read_text(encoding="utf-8")
    block = _format_block(resolved)
    new_source = re.sub(
        r"CAMERAS: list\[dict\] = \[.*?\n\]",
        f"CAMERAS: list[dict] = [\n{block}\n]",
        source,
        count=1,
        flags=re.DOTALL,
    )
    if new_source == source:
        print("Failed to substitute CAMERAS block.", file=sys.stderr)
        return 3
    CONST_PATH.write_text(new_source, encoding="utf-8")
    print(f"Wrote {len(resolved)} cameras to {CONST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

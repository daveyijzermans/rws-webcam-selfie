# RWS Webcam Selfie

A Home Assistant custom integration that records a clip from a Rijkswaterstaat
motorway webcam whenever a tracked device (your phone, your car) drives within
a configurable radius of the camera. Drive past → wake up to a video of
yourself doing exactly that.

## How it works

1. The integration ships with a baked snapshot of all 26 public RWS webcams
   (see `custom_components/rws_webcam_selfie/const.py`), each with its
   coordinates and resolved HLS playlist URL on `stream.inmoves.nl`.
2. You point it at a single `device_tracker` entity and a radius (default
   2 km).
3. Per camera, an `In range` binary sensor flips on as soon as the tracker
   enters the radius.
4. On that transition the integration spawns an `ffmpeg` subprocess that pulls
   the HLS livestream and writes an MP4 into your Home Assistant media folder
   (`/media/rws_webcam_selfie/` by default — visible in the Media browser).
5. The recording stops as soon as the tracker leaves the radius, or after a
   safety-cap duration (default 3 min), whichever comes first.

The live streams use HLS with stream copy, so CPU cost is negligible — no
re-encoding.

## Requirements

- Home Assistant 2024.4 or newer.
- `ffmpeg` available to the HA process. HA OS / Supervised ships with it; on
  HA Container or Core make sure `ffmpeg` is on `PATH` or set its full path in
  the integration options.

## Install (HACS)

1. Add this repository as a custom HACS repository (category: Integration).
2. Install **RWS Webcam Selfie**.
3. Restart Home Assistant.
4. **Settings → Devices & Services → Add Integration → RWS Webcam Selfie**.

## Install (manual)

Copy `custom_components/rws_webcam_selfie/` into your HA `config/custom_components/`
directory and restart.

## Configuration

| Option | Default | Notes |
| --- | --- | --- |
| Device tracker | — | Any `device_tracker.*` with lat/lon attributes (Home Assistant Companion app works great). |
| Trigger radius | 2000 m | Recording starts when distance ≤ radius. |
| Max recording duration | 180 s | Hard cap so a stale tracker can't record forever. |
| Enabled cameras | All 26 | Multi-select. |
| Media subdirectory | `rws_webcam_selfie` | Created under HA's media folder. |
| ffmpeg path | `ffmpeg` | Override if not on PATH. |

## Entities

- `camera.rws_<road>_<near>` — one per enabled webcam. Plays the live HLS in
  Lovelace via HA's `stream` component.
- `binary_sensor.rws_<road>_<near>_in_range` — true while you're within the
  trigger radius.

## Events

The integration fires three events you can hook automations to:

- `rws_webcam_selfie_recording_started` — `{camera_id, road, near, path, reason, stream_url}`
- `rws_webcam_selfie_recording_complete` — `{camera_id, road, near, path, duration, size_bytes}`
- `rws_webcam_selfie_recording_failed` — `{camera_id, error, returncode, stderr_tail}`

Example automation that pings you with a link when a recording finishes:

```yaml
automation:
  - alias: "Notify when RWS selfie recorded"
    trigger:
      - platform: event
        event_type: rws_webcam_selfie_recording_complete
    action:
      - service: notify.mobile_app_phone
        data:
          title: "Webcam selfie: {{ trigger.event.data.road }} {{ trigger.event.data.near }}"
          message: "Recorded {{ trigger.event.data.duration | round(1) }}s ({{ (trigger.event.data.size_bytes / 1048576) | round(1) }} MB)"
```

## Services

- `rws_webcam_selfie.start_recording` — `camera_id`, optional `duration` (s).
- `rws_webcam_selfie.stop_recording` — `camera_id`.

## Refreshing the camera list

RWS occasionally adds/removes cameras or rotates streamnames. Re-bake the
snapshot with:

```bash
python scripts/refresh_cameras.py
```

That hits `https://api.rwsverkeersinfo.nl/api/cameras/`, scrapes the embed
page for each camera to resolve its HLS streamname, and rewrites the
`CAMERAS` list in `const.py` in place. Commit the result.

## Notes & caveats

- The HLS streams are public but the embed page enforces a `Referer` check
  before handing out a session cookie. The HLS playlist itself currently
  serves without any auth headers, but ffmpeg is invoked with a
  `Referer: https://www.rwsverkeersinfo.nl/` header anyway to be future-proof.
- Streams are HD (about 800×450 @ ~2.5 Mbit/s in current samples), so a 3-minute
  cap is roughly ~55 MB per recording.
- Cameras can occasionally go dark for maintenance; the integration will fire
  `recording_failed` rather than retrying.

## License

MIT.

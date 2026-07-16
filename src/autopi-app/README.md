# autopi-app

Dashboard UI for live Subaru SSM telemetry. This process **does not talk to the ECU**. It serves the browser UI and AP helpers; the browser streams data from the separate SSM collector over WebSocket.

## Role

| Piece | Responsibility |
|-------|----------------|
| **This app** (`web_main.py`) | HTTP on port `8080` — static UI, config, guest Wi‑Fi QR |
| **SSM collector** (`../ssm-collector/`) | CAN/SSM polling + WebSocket feed on port `8090` |
| **Browser** | Renders gauges/charts; connects to the collector WS URL from `/config.json` |

Run via the repo entry point:

```bash
uv run src/main.py --web
```

Defaults: `WEB_HOST=0.0.0.0`, `WEB_PORT=8080`, `COLLECTOR_WS_URL=ws://localhost:8090/ws`.

## Structure

```
autopi-app/
├── README.md          ← this file
├── web_main.py        FastAPI + uvicorn server
├── static/            Front-end assets (no build step)
│   ├── index.html     Shell: header, gauge/chart mounts, guest Wi‑Fi panel
│   ├── style.css      Layout and theme
│   └── app.js         WebSocket client, Canvas gauges & history charts
└── test/              Placeholder for app tests
```

### `web_main.py`

- Serves `/` → `static/index.html` and mounts `/static`.
- `/config.json` — tells the UI which collector WebSocket to use (`COLLECTOR_WS_URL`).
- `/api/ap-info` and QR SVG routes — guest AP SSID/PSK and dashboard URL (from `/etc/autopi/ap.env` when present). Admin secrets are not exposed to guest clients.
- Captive-portal probe paths — soft-redirect phones on guest Wi‑Fi to the dashboard instead of failing over to cellular.

### `static/`

Vanilla HTML/CSS/JS (no frontend framework). `app.js` builds gauge and chart canvases from collector metadata, keeps ~90s of history, and updates connection/ECU/rate status in the header.

## Related

See the repo root [README](../../README.md) for the full system diagram, and [SETUP.md](../../SETUP.md) for run/deploy details.

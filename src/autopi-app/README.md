# autopi-app

Dashboard UI for live Subaru SSM telemetry. This process **does not talk to the ECU**. It serves the browser UI and AP helpers; the browser streams data from the separate SSM collector over WebSocket.

## Views

| Route | Name | Audience | Contents |
|-------|------|----------|----------|
| `/` | — | Path-based | Trusted/dev (USB, localhost) → `/dashboard`; guest AP → `/detailed` |
| `/detailed` | **Detailed** | Secondary clients (guest AP / phone / tablet) | Live parameter table + history charts; **no** QR panel |
| `/dashboard` | **Dash** / **Car** | Primary client (2‑DIN head unit) | Gauge cluster + motion status; guest Wi‑Fi QR when parked |

Any client may open either view. Nav is for development and secondary devices; the in-car Dash is not driven by pointer or keyboard input.

### Design intent

**Dash (`/dashboard`) — car stereo**

- Shown **full screen** on a **2‑DIN** head-unit display (fixed aspect ratio / resolution).
- **No mouse, keyboard, or touch** in normal use — glanceable only.
- Prioritize **large type**, **easy-to-read fonts**, and **high-contrast** colors so values are readable at a glance and in varying cabin light.
- Layout should fit the screen without relying on scroll or fine interaction.
- QR / Wi‑Fi share UI is for setup and the dev machine, not for the driver while driving. On Dash, the **parked** badge always shows; S142 ON lights it blue and opens the guest Wi‑Fi QR panel, S142 OFF keeps the badge muted (disabled).

**Detailed (`/detailed`) — mobile secondary**

- Normal **phone / tablet** web UI: scrollable, tappable, standard mobile layout.
- Default landing for guests on the AP; richer table + charts for inspection.
- Interaction (scroll, tap, nav) is expected and fine.

## Role

| Piece | Responsibility |
|-------|----------------|
| **This app** (`web_main.py`) | HTTP on port `8080` — views, config, guest Wi‑Fi QR APIs |
| **SSM collector** (`../ssm-collector/`) | CAN/SSM polling + WebSocket feed on port `8090` |
| **Browser** | Renders the selected view; connects to the collector WS URL from `/config.json` |

Run via the repo entry point:

```bash
uv run src/main.py --web
```

Defaults: `WEB_HOST=0.0.0.0`, `WEB_PORT=8080`, `COLLECTOR_WS_URL=ws://localhost:8090/ws`.

### Live UI edits (no full restart)

Static UI files are served with **no-cache** headers. After changing HTML/CSS/JS/configs:

```bash
./sync_ui.sh          # rsync only src/autopi-app → Pi
# then Cmd+R / Ctrl+R in the browser
```

Or **Tasks: Run Task → “autopi: sync UI (no restart)”** (syncs + opens Dash with a cache-bust query).

Only restart the web process when you change `web_main.py` (or other Python).

## Structure

```
autopi-app/
├── README.md
├── web_main.py
├── static/
│   ├── detailed.html   Mobile Detailed view
│   ├── dashboard.html  2‑DIN Dash / Car view
│   ├── style.css
│   └── app.js          Shared WebSocket client + Canvas charts (view via data-view)
└── test/
```

### `web_main.py`

- `/` → `/dashboard` for trusted/dev clients (localhost, USB); `/detailed` for guest AP.
- `/detailed`, `/dashboard` — view shells under `static/`.
- `/config.json` — collector WebSocket URL (`COLLECTOR_WS_URL`).
- `/api/ap-info` and QR SVG routes — guest AP metadata (QR UI is only on Dash).
- Captive-portal probes soft-redirect to the Detailed URL.

### `static/`

Vanilla HTML/CSS/JS. `app.js` reads `body[data-view]` (`detailed` | `dashboard`) to choose layout and whether to load the AP share panel. Style and layout for Dash should follow the car-stereo constraints above; Detailed should stay a conventional mobile page.

## Related

See the repo root [README](../../README.md) for the full system diagram, and [SETUP.md](../../SETUP.md) for run/deploy details.

"""
SSM dashboard UI server — no CAN / SSM polling.

Serves the static web UI under ``static/``. The browser obtains the
collector WebSocket URL from ``/config.json`` (``COLLECTOR_WS_URL``) and
streams live data from ``ssm-collector``. Two HTML views are exposed:

* ``/detailed`` (default) — Detailed table + charts for secondary clients
* ``/dashboard`` — Dash / Car gauges + guest Wi‑Fi QR for the primary client

Also exposes guest Wi‑Fi QR / AP info helpers and captive-portal soft-landing
routes.

Entry
-----
::

    uv run src/main.py --web

Environment
-----------
``WEB_HOST`` / ``WEB_PORT``
    Bind address (defaults ``0.0.0.0`` / ``8080``).
``COLLECTOR_WS_URL``
    WebSocket URL advertised to the UI (default ``ws://localhost:8090/ws``).
``/etc/autopi/ap.env``
    Optional guest AP metadata for QR / ``/api/ap-info``.
"""

from __future__ import annotations

import io
import ipaddress
import os
from pathlib import Path

import segno
import uvicorn
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles

STATIC_DIR = Path(__file__).parent / "static"
CONFIG_DIR = Path(__file__).parent / "configs"
AP_ENV_PATH = Path("/etc/autopi/ap.env")

app = FastAPI(title="autopi SSM dashboard UI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

_NO_CACHE = {
    "Cache-Control": "no-store, no-cache, must-revalidate, max-age=0",
    "Pragma": "no-cache",
    "Expires": "0",
}


@app.middleware("http")
async def disable_ui_cache(request: Request, call_next):
    """
    Prevent browsers from caching HTML/CSS/JS/config so a normal refresh
    picks up UI edits without restarting the web process.
    """
    response = await call_next(request)
    path = request.url.path
    if (
        path.startswith("/static/")
        or path.startswith("/configs/")
        or path in ("/", "/dashboard", "/detailed")
    ):
        for key, val in _NO_CACHE.items():
            response.headers[key] = val
    return response


def collector_ws_url() -> str:
    """
    Resolve the collector WebSocket URL for the browser.

    Returns:
        Value of ``COLLECTOR_WS_URL``, or ``ws://localhost:8090/ws``.
    """
    return os.getenv("COLLECTOR_WS_URL", "ws://localhost:8090/ws")


def _load_ap_env() -> dict[str, str]:
    """
    Parse ``/etc/autopi/ap.env`` into a key/value map.

    Returns:
        Empty dict if the file is missing or unreadable (e.g. permissions).
        Otherwise KEY=VALUE pairs, ignoring blank lines and ``#`` comments.
    """
    if not AP_ENV_PATH.is_file():
        return {}
    try:
        text = AP_ENV_PATH.read_text()
    except PermissionError:
        # 640 root:group — service user must share that group (configure_raspap_dual_ap.sh).
        return {}
    out: dict[str, str] = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        out[key.strip()] = val.strip()
    return out


def _ip_in_subnet(ip: str, cidr: str) -> bool:
    """
    Return True if ``ip`` is inside the ``cidr`` network.

    Args:
        ip: Client IP string.
        cidr: Network in CIDR notation (e.g. ``\"10.3.141.0/24\"``).

    Returns:
        False if either value is not a valid address/network.
    """
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _client_is_trusted(request: Request, ap: dict[str, str]) -> bool:
    """
    Whether the client may see admin-oriented AP metadata.

    Trusted sources: localhost, the configured admin subnet, and common USB
    gadget / Mac Internet Sharing pools. Guest Wi‑Fi clients are not trusted
    (admin PSK must never be exposed there).

    Args:
        request: Incoming FastAPI request (uses ``request.client.host``).
        ap: Parsed ap.env map (may contain ``ADMIN_SUBNET``).

    Returns:
        True if the client is on a trusted path.
    """
    host = request.client.host if request.client else ""
    if host in ("127.0.0.1", "::1"):
        return True
    admin_subnet = ap.get("ADMIN_SUBNET", "10.3.142.0/24")
    # USB gadget: historical shared pool + common Mac Internet Sharing pools
    if (
        _ip_in_subnet(host, admin_subnet)
        or _ip_in_subnet(host, "10.12.194.0/28")
        or _ip_in_subnet(host, "192.168.2.0/24")
        or _ip_in_subnet(host, "192.168.137.0/24")
    ):
        return True
    return False


def _wifi_qr_payload(ssid: str, psk: str) -> str:
    """
    Build a ``WIFI:…`` QR payload string for WPA join.

    Args:
        ssid: Guest network name.
        psk: Guest pre-shared key.

    Returns:
        Escaped ``WIFI:T:WPA;S:…;P:…;;`` string suitable for QR encoding.
    """

    def esc(s: str) -> str:
        """Escape WIFI QR reserved characters in SSID/PSK fields."""
        return (
            s.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace(":", "\\:")
            .replace('"', '\\"')
        )

    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};;"


def _qr_svg(payload: str, *, scale: int) -> str:
    """
    Render ``payload`` as an SVG document string (includes ``xmlns``).

    Args:
        payload: Text encoded into the QR.
        scale: Module scale factor passed to segno.

    Returns:
        UTF-8 SVG markup safe for ``image/svg+xml`` responses.
    """
    qr = segno.make(payload, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, dark="#e8eaed", light="#1a1c1e")
    return buf.getvalue().decode("utf-8")


def _qr_data_uri(payload: str, *, scale: int) -> str:
    """
    Render ``payload`` as an SVG data URI for embedding in JSON/HTML.

    Args:
        payload: Text encoded into the QR.
        scale: Module scale factor passed to segno.

    Returns:
        ``data:image/svg+xml;…`` URI from segno.
    """
    qr = segno.make(payload, error="m")
    return qr.svg_data_uri(scale=scale, dark="#e8eaed", light="#1a1c1e")


def _dashboard_url(ap: dict[str, str]) -> str:
    """
    Resolve the guest-facing app URL (Detailed view by default).

    Prefers ``GUEST_DASHBOARD_URL``, else ``http://<AP_HOSTNAME>:8080/detailed``
    (falling back through ``GUEST_HOSTNAME`` to ``autopi.lan``).

    Args:
        ap: Parsed ap.env map.

    Returns:
        Absolute HTTP URL string for the UI.
    """
    if ap.get("GUEST_DASHBOARD_URL"):
        return ap["GUEST_DASHBOARD_URL"]
    host = ap.get("AP_HOSTNAME") or ap.get("GUEST_HOSTNAME") or "autopi.lan"
    return f"http://{host}:8080/detailed"


@app.get("/")
async def index(request: Request) -> RedirectResponse:
    """
    Path-based landing: Dash for trusted/dev clients, Detailed for guests.

    Trusted = localhost, USB gadget / Mac Internet Sharing pools, admin subnet.
    Guest AP clients (and anyone else) get the Detailed view.
    """
    ap = _load_ap_env()
    if _client_is_trusted(request, ap):
        return RedirectResponse("/dashboard", status_code=302)
    return RedirectResponse("/detailed", status_code=302)


@app.get("/detailed")
async def detailed_view() -> FileResponse:
    """Serve the Detailed view (same gauges/charts as Dash; no guest QR panel)."""
    return FileResponse(STATIC_DIR / "detailed.html", headers=_NO_CACHE)


@app.get("/dashboard")
async def dashboard_view() -> FileResponse:
    """Serve the Dash / Car view (gauges + charts + guest Wi‑Fi QR)."""
    return FileResponse(STATIC_DIR / "dashboard.html", headers=_NO_CACHE)


@app.get("/configs/{name}.json", response_model=None)
async def view_config(name: str) -> FileResponse | JSONResponse:
    """
    Per-view UI config (channel order/colors, Dash refresh rate, history windows).

    Args:
        name: ``dashboard`` or ``detailed``.
    """
    if name not in ("dashboard", "detailed"):
        return JSONResponse({"error": "unknown view"}, status_code=404)
    path = CONFIG_DIR / f"{name}.json"
    if not path.is_file():
        return JSONResponse({"error": "config missing"}, status_code=404)
    return FileResponse(path, media_type="application/json", headers=_NO_CACHE)


# Captive-portal probes (phones hit these on port 80 → redirected to this app).
# Returning a soft landing keeps traffic on Wi‑Fi instead of failing over to cellular.
@app.get("/hotspot-detect.html")
@app.get("/library/test/success.html")
async def apple_captive() -> HTMLResponse:
    """
    Soft landing for Apple captive-portal detection URLs.

    Returns:
        Tiny HTML page that meta-refreshes to the default (Detailed) URL.
    """
    url = _dashboard_url(_load_ap_env())
    return HTMLResponse(
        f"<!DOCTYPE html><html><head><meta http-equiv='refresh' content='0;url={url}'/>"
        f"<title>autopi</title></head><body><p><a href='{url}'>Open detailed view</a></p></body></html>"
    )


@app.get("/generate_204")
@app.get("/gen_204")
@app.get("/connecttest.txt")
@app.get("/ncsi.txt")
@app.get("/redirect")
async def captive_redirect() -> RedirectResponse:
    """
    Redirect Android/Windows/etc. captive probes to the dashboard.

    Returns:
        HTTP 302 to :func:`_dashboard_url`.
    """
    return RedirectResponse(_dashboard_url(_load_ap_env()), status_code=302)


@app.get("/config.json")
async def config() -> JSONResponse:
    """
    Browser bootstrap config (collector WebSocket URL).

    Returns:
        JSON ``{\"collector_ws_url\": \"…\"}``.
    """
    return JSONResponse({"collector_ws_url": collector_ws_url()})


@app.get("/api/ap-info")
async def ap_info(request: Request) -> JSONResponse:
    """
    Guest Wi‑Fi / dashboard QR metadata for the UI share panel.

    Requires ``GUEST_SSID`` and ``GUEST_PSK`` in ap.env. Never includes the
    admin PSK; trusted clients may get an admin hint only.

    Args:
        request: Used for :func:`_client_is_trusted`.

    Returns:
        404 JSON if AP is not configured; otherwise guest SSID/PSK, URLs,
        and QR data URIs.
    """
    ap = _load_ap_env()
    if not ap.get("GUEST_SSID") or not ap.get("GUEST_PSK"):
        return JSONResponse(
            {
                "configured": False,
                "error": "AP not configured (/etc/autopi/ap.env missing or unreadable)",
            },
            status_code=404,
        )

    guest_gw = ap.get("GUEST_GATEWAY", "10.3.141.1")
    ap_hostname = ap.get("AP_HOSTNAME") or ap.get("GUEST_HOSTNAME") or "autopi.lan"
    dash_url = _dashboard_url(ap)
    wifi_payload = _wifi_qr_payload(ap["GUEST_SSID"], ap["GUEST_PSK"])
    payload = {
        "configured": True,
        "guest_ssid": ap["GUEST_SSID"],
        "guest_psk": ap["GUEST_PSK"],
        "guest_gateway": guest_gw,
        "ap_hostname": ap_hostname,
        "guest_dashboard_url": dash_url,
        "guest_wifi_qr": wifi_payload,
        "wifi_qr_data_uri": _qr_data_uri(wifi_payload, scale=6),
        "url_qr_data_uri": _qr_data_uri(dash_url, scale=5),
        "admin_ssid": ap.get("ADMIN_SSID", "autopi-admin"),
        "admin_gateway": ap.get("ADMIN_GATEWAY", "10.3.142.1"),
    }
    # Never expose admin PSK on the guest-reachable API.
    if _client_is_trusted(request, ap):
        payload["admin_psk_hint"] = "see /etc/autopi/ap.env on the Pi (USB/admin only)"
    return JSONResponse(payload)


@app.get("/api/ap-qr.svg")
async def ap_qr_svg() -> Response:
    """
    SVG QR that joins the guest Wi‑Fi network.

    Returns:
        ``image/svg+xml`` on success, or plain-text 404 if AP is not configured.
    """
    ap = _load_ap_env()
    if not ap.get("GUEST_SSID") or not ap.get("GUEST_PSK"):
        return Response("AP not configured", status_code=404, media_type="text/plain")
    svg = _qr_svg(_wifi_qr_payload(ap["GUEST_SSID"], ap["GUEST_PSK"]), scale=6)
    return Response(svg, media_type="image/svg+xml")


@app.get("/api/ap-url-qr.svg")
async def ap_url_qr_svg() -> Response:
    """
    SVG QR that opens the guest dashboard URL.

    Returns:
        ``image/svg+xml`` for the resolved dashboard URL.
    """
    ap = _load_ap_env()
    dash_url = _dashboard_url(ap)
    svg = _qr_svg(dash_url, scale=5)
    return Response(svg, media_type="image/svg+xml")


def main() -> None:
    """
    Bind uvicorn for the dashboard using ``WEB_HOST`` / ``WEB_PORT``.
    """
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    print(f"SSM dashboard UI → http://{host}:{port}/")
    print(f"  collector WS   → {collector_ws_url()}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

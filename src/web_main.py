"""
SSM dashboard UI server — no CAN / SSM polling.

Serves the static web UI. The browser connects to the collector WebSocket
configured via COLLECTOR_WS_URL (default ws://localhost:8090/ws).
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
AP_ENV_PATH = Path("/etc/autopi/ap.env")

app = FastAPI(title="autopi SSM dashboard UI")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


def collector_ws_url() -> str:
    return os.getenv("COLLECTOR_WS_URL", "ws://localhost:8090/ws")


def _load_ap_env() -> dict[str, str]:
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
    try:
        return ipaddress.ip_address(ip) in ipaddress.ip_network(cidr, strict=False)
    except ValueError:
        return False


def _client_is_trusted(request: Request, ap: dict[str, str]) -> bool:
    """Admin AP / USB gadget / localhost may see admin SSID metadata (not needed for QR)."""
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
    # Escape special chars per WIFI QR conventions
    def esc(s: str) -> str:
        return (
            s.replace("\\", "\\\\")
            .replace(";", "\\;")
            .replace(",", "\\,")
            .replace(":", "\\:")
            .replace('"', '\\"')
        )

    return f"WIFI:T:WPA;S:{esc(ssid)};P:{esc(psk)};;"


def _qr_svg(payload: str, *, scale: int) -> str:
    """SVG suitable for <img src> — must include xmlns (svg_inline does not)."""
    qr = segno.make(payload, error="m")
    buf = io.BytesIO()
    qr.save(buf, kind="svg", scale=scale, dark="#e8eaed", light="#1a1c1e")
    return buf.getvalue().decode("utf-8")


def _qr_data_uri(payload: str, *, scale: int) -> str:
    qr = segno.make(payload, error="m")
    return qr.svg_data_uri(scale=scale, dark="#e8eaed", light="#1a1c1e")


def _dashboard_url(ap: dict[str, str]) -> str:
    if ap.get("GUEST_DASHBOARD_URL"):
        return ap["GUEST_DASHBOARD_URL"]
    host = ap.get("AP_HOSTNAME") or ap.get("GUEST_HOSTNAME") or "autopi.lan"
    return f"http://{host}:8080/"


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


# Captive-portal probes (phones hit these on port 80 → redirected to this app).
# Returning a soft landing keeps traffic on Wi‑Fi instead of failing over to cellular.
@app.get("/hotspot-detect.html")
@app.get("/library/test/success.html")
async def apple_captive() -> HTMLResponse:
    url = _dashboard_url(_load_ap_env())
    return HTMLResponse(
        f"<!DOCTYPE html><html><head><meta http-equiv='refresh' content='0;url={url}'/>"
        f"<title>autopi</title></head><body><p><a href='{url}'>Open dashboard</a></p></body></html>"
    )


@app.get("/generate_204")
@app.get("/gen_204")
@app.get("/connecttest.txt")
@app.get("/ncsi.txt")
@app.get("/redirect")
async def captive_redirect() -> RedirectResponse:
    return RedirectResponse(_dashboard_url(_load_ap_env()), status_code=302)


@app.get("/config.json")
async def config() -> JSONResponse:
    return JSONResponse({"collector_ws_url": collector_ws_url()})


@app.get("/api/ap-info")
async def ap_info(request: Request) -> JSONResponse:
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
    ap = _load_ap_env()
    if not ap.get("GUEST_SSID") or not ap.get("GUEST_PSK"):
        return Response("AP not configured", status_code=404, media_type="text/plain")
    svg = _qr_svg(_wifi_qr_payload(ap["GUEST_SSID"], ap["GUEST_PSK"]), scale=6)
    return Response(svg, media_type="image/svg+xml")


@app.get("/api/ap-url-qr.svg")
async def ap_url_qr_svg() -> Response:
    ap = _load_ap_env()
    ap_hostname = ap.get("AP_HOSTNAME") or "autopi.lan"
    dash_url = _dashboard_url(ap)
    svg = _qr_svg(dash_url, scale=5)
    return Response(svg, media_type="image/svg+xml")


def main() -> None:
    host = os.getenv("WEB_HOST", "0.0.0.0")
    port = int(os.getenv("WEB_PORT", "8080"))
    print(f"SSM dashboard UI → http://{host}:{port}/")
    print(f"  collector WS   → {collector_ws_url()}")
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

# autopi setup

One-time Pi setup, deploy, and how to run the app. For project background (SSM, hardware, tools), see [README.md](README.md).

## Requirements

- A configured Pi (see [Hardware](README.md#hardware) in the README)
- SSH key-based authentication to the Pi
- Passwordless `sudo` for the Pi user
- Laptop `.env` with `PI_HOSTNAME`, `PI_HOST`, `PI_USER` (and optional `AP_SSID` / `AP_HOSTNAME`)

## Dev machine: lint hooks (optional but recommended)

On a laptop checkout (not the Pi), install commit hooks so Ruff / secret scans run before each commit. CI runs the same checks on GitHub.

```bash
uv sync --dev
uv run pre-commit install
uv run pre-commit run --all-files   # once, to catch existing issues
```

Hooks refuse `.env` and `docs/romraider/*.xml` in commits. See `.pre-commit-config.yaml` and `.github/workflows/ci.yml`.

## Environment configuration

1. Copy the example environment file to `.env`:
   ```bash
   cp .env.example .env
   ```
2. Edit `.env` and set your Pi connection details:
   ```bash
   PI_HOSTNAME=autopi          # system hostname set by ./pi_setup.sh
   PI_HOST=autopi.local        # how this laptop reaches the Pi (mDNS / IP)
   PI_USER=pi                  # SSH username on the Pi
   AP_SSID=AUTOPI              # guest WiFi network name (QR code)
   AP_HOSTNAME=autopi.lan      # DNS name on the guest AP → http://autopi.lan:8080/
   ```

   Keep `PI_HOST` aligned with `PI_HOSTNAME` (usually `${PI_HOSTNAME}.local`). `AP_SSID` / `AP_HOSTNAME` are independent of the system hostname.

3. Set `ROMRAIDER_XML` to your RomRaider logger definition (repo-relative or absolute). The laptop reads this path directly; `./deploy.sh` copies it onto the Pi. Example from `.env.example`:
   ```bash
   ROMRAIDER_XML=docs/romraider/logger_v370/logger_STD_EN_v370.xml
   SSM_ECU_ID=5C42504007
   ```
   Keep the XML under `docs/romraider/` (gitignored). If the file or `ROMRAIDER_XML` is missing, the steps below will tell you what to fix.

## SSM collector channels

After `.env` points at a real logger XML, generate the full channel catalog and pick what to poll:

```bash
./ssm_collector_setup.sh
```

That script checks `.env` for `ROMRAIDER_XML`, verifies the XML file exists, then runs `generate_channels_json.py`. Output is `src/ssm-collector/configs/channels.generated.json` (gitignored) — every param for your ECU with `"enabled": false`, plus an `info` block for human reference.

Copy the entries you want into the committed poll list `src/ssm-collector/configs/channels.json`, set `"enabled": true`, and keep `id` as the RomRaider id (`P2`, `E31`, …). The collector only reads `id` and `enabled`; units/labels/gauges come from the XML at runtime. Details: [src/ssm-collector/README.md](src/ssm-collector/README.md).

## Passwordless SSH and sudo

1. Generate an SSH key pair on your laptop (skip if you already have one):
   ```bash
   ssh-keygen -t ed25519 -C "autopi"
   ```

2. Copy your public key to the Pi:
   ```bash
   ssh-copy-id ${PI_USER}@${PI_HOST}
   ```

3. Verify you can SSH without a password:
   ```bash
   ssh ${PI_USER}@${PI_HOST}
   ```

4. Allow passwordless `sudo` on the Pi:
   ```bash
   ssh ${PI_USER}@${PI_HOST} "echo '${PI_USER} ALL=(ALL) NOPASSWD: ALL' | sudo tee /etc/sudoers.d/${PI_USER}"
   ```

## One-time Pi setup

Run the setup script once to configure the Pi from scratch. It streams each step over SSH — no files need to be on the Pi beforehand, so it's safe to run before `deploy.sh`.

```bash
./pi_setup.sh
```

The script handles reboots automatically: if a step triggers a reboot (e.g. adding kernel overlays), it waits for the Pi to come back online before continuing. The last step prints a **live network map** (USB WAN, APs, SSH peers, services, CAN).

Re-print the map anytime:

```bash
ssh ${PI_USER}@${PI_HOST} 'bash -s' < raspberryPiSetup/print_network_map.sh
```

Or use **Tasks: Run Task → “autopi: network map”** / **“autopi: Pi setup”** in Cursor.

To customise the setup sequence, edit the `SETUP_SCRIPTS` array at the top of `pi_setup.sh`.

### What `pi_setup.sh` configures

| Area | Scripts (under `raspberryPiSetup/`) |
|------|--------------------------------------|
| Hostname | `set_hostname.sh` from `PI_HOSTNAME` |
| Packages | `update.sh`, `install_uv.sh`, `install_CAN_utils.sh`, `install_rtc_tools.sh` |
| PiCAN3 / CAN | overlays, `enable_can0_at_startup.sh`, `install_socketcand.sh` |
| RTC | overlays, `disable_fake_hwclock.sh` |
| Guest Wi‑Fi | RaspAP install, guest AP config, nftables, web systemd units |
| Status | `print_network_map.sh` |

## Deploy app code

Sync code, copy the RomRaider XML from your laptop `ROMRAIDER_XML` path onto the Pi at `src/ssm-collector/configs/<same-filename>.xml`, write a Pi-specific `.env` (`CAN_MODE=native`, `SSM_ECU_ID`), and install Python deps with `uv`:

```bash
./deploy.sh
```

## Running the app

Two scripts are provided depending on where you want the code to execute. Both default to the SSM terminal logger. Ensure the Pi is already set up (above) and code is deployed (`./deploy.sh`).

```bash
./run_remote.sh                # SSM terminal logger (default)
./run_remote.sh --collector    # SSM collector only  → ws://localhost:8090/ws
./run_remote.sh --web          # collector + web UI together → http://localhost:8080
./run_remote.sh --obd          # OBD-II poller

./run_local.sh                 # SSM terminal logger on Pi
./run_local.sh --web           # collector + web UI together on Pi
./run_local.sh --obd           # OBD-II poller on Pi
```

`./run_remote.sh --web` and `./run_local.sh --web` both start the collector and dashboard together. Open **http://localhost:8080** (remote) or **http://\<pi-host\>:8080** (local). The browser connects to the collector WebSocket at `ws://\<same-host\>:8090/ws`. On the guest AP, use **`http://autopi.lan:8080/`**.

### VS Code / Cursor

Use **Run and Debug → “SSM Web Dashboard (local)”**, or **Tasks: Run Task → “autopi: SSM web (local)”**. That starts `./run_local.sh --web` and opens `http://$PI_HOST:8080/` when the server is ready.

### `./run_remote.sh` — code runs on your laptop

Connects to the Pi over an SSH tunnel and queries the CAN bus remotely from your machine. Use this during development.

| Step | What happens |
|------|-------------|
| 1 | Deploys latest code to the Pi |
| 2 | Checks that `socketcand` is running on the Pi (starts it if not) |
| 3 | Checks that the SSH tunnel is open on `localhost:29536` (opens it if not) |
| 4 | Runs `src/main.py` locally with `CAN_MODE=socketcand` |

CAN frames travel: `can0` → `socketcand` → SSH tunnel → `python-can` on your machine.

### `./run_local.sh` — code runs on the Pi

Stops the socketcand service, closes any open SSH tunnel, then SSHes into the Pi and runs the app directly there. Use this to test the deployed configuration.

| Step | What happens |
|------|-------------|
| 1 | Deploys latest code to the Pi |
| 2 | Stops `socketcand` on the Pi (if running) |
| 3 | Closes the SSH tunnel on `localhost:29536` (if open) |
| 4 | Ensures `can0` is up on the Pi |
| 5 | Runs `src/main.py` on the Pi via SSH with `CAN_MODE=native` |

CAN frames travel: `can0` → `python-can` directly.

### Entry points

| Script | Protocol | Description |
|--------|----------|-------------|
| `src/main.py` | SSM *(default)* | Dispatches to logger / collector / UI / OBD |
| `src/ssm-collector/ssm_main.py` | Subaru SSM | Terminal batch reads at 50 Hz |
| `src/ssm-collector/ssm_collector.py` | Subaru SSM | Data collector only — WebSocket on port `8090` |
| `src/autopi-app/web_main.py` | — | Dashboard UI only on port `8080` (no CAN) |
| `src/obd-collector/obd_main.py` | OBD-II | Generic OBD-II PIDs at 1 Hz |

The SSM logger automatically reads the ECU ID from the init response and selects the correct address map. Override with `SSM_ECU_ID` in `.env` (e.g. `5C42504007` for a 2011 USDM STI).

## Guest Wi‑Fi AP (after setup)

The Pi hosts a **guest WiFi AP** on the onboard radio. USB gadget remains the Mac uplink for SSH, deploy, and admin access.

| SSID | Role | Access |
|------|------|--------|
| `AUTOPI` (via `AP_SSID`) | Guest (QR in dashboard) | Dashboard `:8080` + collector `:8090` only |

**Guest flow:** join `AP_SSID` → open **`http://autopi.lan:8080/`** (or scan the URL QR). Guest DHCP/DNS maps `AP_HOSTNAME` to the Pi. Prefer a dotted name — phones often fail single-label hosts and may fall back to cellular when the network has no internet.

**Admin access:** USB gadget (or Ethernet). Onboard WiFi allows only **one AP**, so there is no second admin SSID without a USB WiFi dongle.

**USB gadget direction:** `usb0` on the Pi must be a **DHCP client** (Mac → Pi). Shared mode on the Pi makes the Mac route internet into the Pi and breaks Mac uplink. Keep Wi‑Fi above USB in Mac network service order; enable **Internet Sharing → USB** only if the Pi needs upstream internet.

**Re-apply AP config after RaspAP Hotspot UI changes:**
```bash
ssh ${PI_USER}@${PI_HOST} 'bash -s' < raspberryPiSetup/configure_raspap_guest_ap.sh
ssh ${PI_USER}@${PI_HOST} 'bash -s' < raspberryPiSetup/configure_ap_client_firewall.sh
```

Upstream pieces: [RaspAP Quick installer](https://docs.raspap.com/quick/), [RaspAP/raspap-tools](https://github.com/RaspAP/raspap-tools).

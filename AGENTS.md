# AGENTS.md

Guidance for AI agents working on **autopi**.

## What this project is

Raspberry Pi–based **Subaru SSM** telemetry over CAN (PiCAN3). A collector polls the ECU and streams over WebSocket; a small FastAPI app serves a static dashboard. Generic OBD-II is a separate fallback path. Guest Wi‑Fi (RaspAP) and USB gadget admin are configured via `raspberryPiSetup/` scripts.

Product overview: [README.md](README.md). Setup / deploy / run: [SETUP.md](SETUP.md).

## Repository layout

```
src/
  main.py                 CLI dispatcher (--collector / --web / --obd / default SSM logger)
  ssm-collector/          SSM protocol, runtime, collector, raider_reader (RomRaider XML)
  autopi-app/             UI: /dashboard = 2‑DIN glanceable Dash; /detailed = mobile secondary
  obd-collector/          Generic OBD-II terminal poller
raspberryPiSetup/         One-shot Pi setup scripts (invoked by pi_setup.sh over SSH)
dev_scripts/              Offline tools (Teensy header gen, etc.) — gitignored
docs/romraider/           Upstream RomRaider logger XML — gitignored; ROMRAIDER_XML points here on laptop
```

Package directories under `src/` use **hyphens** (`ssm-collector`, `autopi-app`, `obd-collector`). They are not importable as Python packages; `src/main.py` adds them to `sys.path` before importing.

## Commands

```bash
# Runtime deps only (what the Pi should use)
uv sync

# Dev machine: include ruff
uv sync --dev

uv run ruff check src
uv run ruff format src

uv run src/main.py              # SSM terminal logger
uv run src/main.py --collector  # WebSocket collector :8090
uv run src/main.py --web        # Dashboard :8080
uv run src/main.py --obd        # OBD-II poller

./deploy.sh                     # rsync + uv sync --no-dev on the Pi
./pi_setup.sh                   # one-time Pi configuration over SSH
./run_remote.sh                 # laptop + socketcand tunnel
./run_local.sh                  # run on the Pi via SSH
```

Ruff is a **dev-only** dependency (`[dependency-groups] dev`, `[tool.uv] default-groups = []`). Never add it to `[project].dependencies`. Pi install path is `uv sync --no-dev` (see `deploy.sh`).

## Conventions

- Always ask before adding a dependency/library
- Only use open source dependencies
- Prefer small, focused diffs. Do not rewrite unrelated files or add unsolicited docs.
- Match existing style: type hints, module/function docstrings on Python under `src/`, vanilla HTML/CSS/JS in `autopi-app/static` (no frontend framework).
- Config: copy `.env.example` → `.env` locally. Never commit `.env` or credentials. Do not put secrets in guest-reachable APIs.
- SSM addresses/units come only from RomRaider logger XML (`raider_reader.py`). Laptop: `ROMRAIDER_XML` in `.env` (usually `docs/romraider/…`). Pi: `deploy.sh` copies that file into `src/ssm-collector/configs/` keeping the real basename; runtime picks the single `*.xml` there. Do not reintroduce `ssm_configs.json` or commit logger XML under `configs/`.
- Never commit dev_scripts directory
- Never commit docs directory
- Keep `SSM_ECU_ID` / address maps matched to the target ECU (default stock 2011 STI family `5C42504007`).
- When changing package layout or entry points, update `src/main.py`, systemd units in `raspberryPiSetup/install_autopi_web_service.sh`, and the relevant package README.

## Networking / Pi safety

- Guest AP is a **single** BSS (`AUTOPI`); admin access is USB gadget, not a second Wi‑Fi AP.
- Do not `nmcli connection up` USB/shared connections over an active SSH-over-USB session — it can wedge the link.
- Prefer `http://autopi.lan:8080/` on guest Wi‑Fi (not single-label `autopi`).

## Docs map

| Doc | Audience |
|-----|----------|
| [README.md](README.md) | What / why / hardware / tools |
| [SETUP.md](SETUP.md) | Install, deploy, run |
| [src/ssm-collector/README.md](src/ssm-collector/README.md) | SSM stack |
| [src/autopi-app/README.md](src/autopi-app/README.md) | Dashboard |
| [src/obd-collector/README.md](src/obd-collector/README.md) | OBD-II poller |

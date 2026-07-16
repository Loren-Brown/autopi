#!/usr/bin/env bash
set -euo pipefail

SOCKETCAND_BIN="/usr/local/sbin/socketcand"

if command -v socketcand &>/dev/null; then
    echo "socketcand already installed at $(command -v socketcand), skipping build."
elif [[ -x "${SOCKETCAND_BIN}" ]]; then
    echo "socketcand already installed at ${SOCKETCAND_BIN}, skipping build."
else
    echo "Installing socketcand build dependencies..."
    sudo apt-get install -y meson gcc libconfig-dev libsocketcan-dev git

    echo "Cloning and building socketcand..."
    BUILD_DIR=$(mktemp -d)
    git clone https://github.com/linux-can/socketcand.git "$BUILD_DIR/socketcand"
    cd "$BUILD_DIR/socketcand"
    meson setup -Dlibconfig=true --buildtype=release build
    meson compile -C build
    sudo meson install -C build
fi

echo "Installing systemd service..."
sudo tee /etc/systemd/system/socketcand.service > /dev/null <<EOF
[Unit]
Description=socketcand CAN over TCP bridge
After=network.target sys-subsystem-net-devices-can0.device
Requires=sys-subsystem-net-devices-can0.device

[Service]
ExecStart=${SOCKETCAND_BIN} -i can0 -l lo -p 29536
Restart=on-failure

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable socketcand
sudo systemctl start socketcand

echo "Verifying socketcand is running..."
sudo systemctl status socketcand

echo "Stopping socketcand (it will start automatically when needed)..."
sudo systemctl stop socketcand

echo "socketcand installed and enabled. It will start on next boot or when run_remote.sh starts it."

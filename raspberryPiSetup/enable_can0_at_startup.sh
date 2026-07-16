echo "Configuring can0 to come up automatically at boot..."
if ! grep -q "iface can0" /etc/network/interfaces; then
    sudo tee -a /etc/network/interfaces <<'EOF'

auto can0
iface can0 can static
    bitrate 500000
EOF
fi
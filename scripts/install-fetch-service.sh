#!/bin/bash
# Install Astronomical Events fetch+process systemd service + timer
# Runs daily at 11:00 Europe/Madrid

set -e

SERVICE_FILE="/etc/systemd/system/astronomical-events-fetch.service"
TIMER_FILE="/etc/systemd/system/astronomical-events-fetch.timer"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

echo "📦 Installing astronomical-events fetch service..."

sudo cp "$SCRIPT_DIR/astronomical-events-fetch.service" "$SERVICE_FILE"
sudo cp "$SCRIPT_DIR/astronomical-events-fetch.timer" "$TIMER_FILE"

sudo systemctl daemon-reload
sudo systemctl enable --now astronomical-events-fetch.timer

echo ""
echo "✅ Installed & enabled!"
echo ""
echo "Status:"
systemctl status astronomical-events-fetch.timer --no-pager
echo ""
echo "Next trigger:"
systemctl list-timers astronomical-events-fetch.timer --no-pager
echo ""
echo "Manual test: sudo systemctl start astronomical-events-fetch.service"

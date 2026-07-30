#!/bin/bash
set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SERVICE_FILE="$SCRIPT_DIR/nobody-ui.service"

if [ ! -f "$SERVICE_FILE" ]; then
  echo "Error: nobody-ui.service not found in $SCRIPT_DIR"
  exit 1
fi

echo "Installing Nobody UI service..."
echo "Make sure you've edited nobody-ui.service with your username and paths first!"
echo ""

sudo cp "$SERVICE_FILE" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable nobody-ui
sudo systemctl start nobody-ui
sudo systemctl status nobody-ui

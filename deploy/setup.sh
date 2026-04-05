#!/usr/bin/env bash
# Jaded Rose Chatbot — GCP Compute Engine setup script
# Run this on a fresh Debian/Ubuntu VM as your deploy user (e.g. cohiba).
#
# Usage:
#   chmod +x deploy/setup.sh
#   ./deploy/setup.sh

set -euo pipefail

APP_DIR="$HOME/02_jaded-rose-chatbot"
SERVICE_NAME="jaded-rose-chatbot"

echo "=== 1. System packages ==="
sudo apt-get update -y
sudo apt-get install -y python3 python3-venv python3-pip git redis-tools

echo "=== 2. Python venv ==="
cd "$APP_DIR"
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip
pip install -r requirements.txt

echo "=== 3. Check .env ==="
if [ ! -f "$APP_DIR/.env" ]; then
    echo "ERROR: No .env file found at $APP_DIR/.env"
    echo "Copy .env.example and fill in your keys:"
    echo "  cp .env.example .env"
    echo "  nano .env"
    exit 1
fi

echo "=== 4. Install systemd service ==="
sudo cp deploy/jaded-rose-chatbot.service /etc/systemd/system/${SERVICE_NAME}.service
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl start ${SERVICE_NAME}

echo "=== 5. Verify ==="
sleep 2
sudo systemctl status ${SERVICE_NAME} --no-pager

echo ""
echo "Done! The chatbot is running as a systemd service."
echo ""
echo "Useful commands:"
echo "  sudo systemctl status ${SERVICE_NAME}   # check status"
echo "  sudo systemctl restart ${SERVICE_NAME}   # restart"
echo "  sudo journalctl -u ${SERVICE_NAME} -f    # tail logs"
echo "  sudo systemctl stop ${SERVICE_NAME}      # stop"

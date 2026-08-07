#!/usr/bin/env bash
# Pull the current dashboard source from GitHub and deploy it to this server.
set -Eeuo pipefail

REPO_URL="git@github.com:sars87/dashboard.git"
REPO_DIR="/home/saif/deployments/dashboard"
APP_FILE="dashboard.py"

if [[ ! -d "$REPO_DIR/.git" ]]; then
    git clone "$REPO_URL" "$REPO_DIR"
else
    git -C "$REPO_DIR" pull --ff-only
fi

SOURCE_PATH="$REPO_DIR/$APP_FILE"
if [[ ! -f "$SOURCE_PATH" ]]; then
    echo "Missing dashboard source: $SOURCE_PATH" >&2
    exit 1
fi

# Refuse to replace the running app if the downloaded source is invalid.
python3 -B -c "import pathlib; compile(pathlib.Path('$SOURCE_PATH').read_text(), '$APP_FILE', 'exec')"

if [[ -f "/home/saif/dashboard.py" ]]; then
    sudo cp /home/saif/dashboard.py "/home/saif/dashboard.py.backup.$(date +%Y%m%d-%H%M%S)"
fi

sudo install -o saif -g saif -m 0644 "$SOURCE_PATH" /home/saif/dashboard.py
sudo systemctl restart dashboard.service
sudo systemctl is-active --quiet dashboard.service

echo "Deployment complete."

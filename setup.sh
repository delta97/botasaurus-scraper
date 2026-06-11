#!/usr/bin/env bash
# One-shot setup for the AI Web Automation Studio.
# Vendors botasaurus, installs Python + frontend deps, and installs Chrome if missing.
set -euo pipefail
cd "$(dirname "$0")"

# 1. Vendored botasaurus (pinned to commit 7936afad5f8ca78fe0581a9dabd5f7d6964c6b1a)
if [ ! -d vendor/botasaurus ]; then
  git clone --depth 1 https://github.com/omkarcloud/botasaurus vendor/botasaurus
  rm -rf vendor/botasaurus/.git
  # strip ~85MB of README gifs / docs site / JS tooling not used by pip install
  rm -rf vendor/botasaurus/images vendor/botasaurus/docs vendor/botasaurus/js
fi

# 2. Python deps. Legacy setup.py sub-packages need a modern build toolchain.
pip install -U pip setuptools wheel || pip install -U --ignore-installed pip setuptools wheel
pip install -e vendor/botasaurus
pip install -r requirements.txt

# 3. Chrome (botasaurus does NOT auto-download it on Linux)
if ! command -v google-chrome >/dev/null && ! command -v chromium >/dev/null && ! command -v chromium-browser >/dev/null; then
  echo "Installing Google Chrome..."
  wget -q -O /tmp/chrome.deb https://dl.google.com/linux/direct/google-chrome-stable_current_amd64.deb
  apt-get install -y /tmp/chrome.deb || { apt-get update && apt-get install -y /tmp/chrome.deb; }
  rm -f /tmp/chrome.deb
fi

# 4. Frontend
if command -v npm >/dev/null; then
  (cd frontend && npm install && npm run build)
else
  echo "npm not found - skipping frontend build" >&2
fi

echo
echo "Setup complete. Start the app with:"
echo "  uvicorn backend.main:app --host 0.0.0.0 --port 8000"

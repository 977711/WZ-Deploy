#!/usr/bin/env bash
set -euo pipefail

source .venv/bin/activate
python3 update.py
exec python3 -m bot

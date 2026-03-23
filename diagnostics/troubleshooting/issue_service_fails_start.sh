#!/usr/bin/env bash
set -euo pipefail

sudo journalctl -u wi-lab.service -n 50 | grep -i "error" || true
/opt/wilab-venv/bin/python /home/asimov/wi-lab/main.py || true
sudo lsof -ti:8080 || true
python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"
python3 -c "from wilab.config import load_config; load_config('config.yaml')"

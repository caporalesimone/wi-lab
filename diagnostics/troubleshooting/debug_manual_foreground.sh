#!/usr/bin/env bash
set -euo pipefail

sudo systemctl stop wi-lab.service
CONFIG_PATH=/home/asimov/wi-lab/config.yaml /opt/wilab-venv/bin/python /home/asimov/wi-lab/main.py

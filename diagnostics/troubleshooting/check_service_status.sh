#!/usr/bin/env bash
set -euo pipefail

sudo systemctl status wi-lab.service
sudo systemctl is-enabled wi-lab.service
echo "Swagger UI: http://localhost:8080/docs"

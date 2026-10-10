#!/bin/bash
set -euo pipefail
cd /opt/ipsc2-monitor
git pull --ff-only
./.venv/bin/pip install -q -r requirements.txt
systemctl restart ipsc2mon
systemctl --no-pager --full status ipsc2mon | head -20

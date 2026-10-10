# IPSC2-MONITOR

Legacy IPSC2-style dashboard for a HBlink / RYSEN / System X master.

Copyright (C) 2026 Shane Daley, M0VUB <shane@freestar.network>

It copies the live IPSC2 Style (STATUS, MONITOR, MATRIX, REMAP, BRIDGE, DONGLE, SERVICE, SITE-INFO) in a modern static frontend, and reads the same TCP report socket that HBMonitor / RYSEN-MONITOR uses (`:4321`).

## Run

```bash
pip install -r requirements.txt
python ipsc2mon.py
```

Then open `http://127.0.0.1:8088/`.

Edit `ipsc2mon.cfg` for the HBlink / RYSEN host/port, site title, contact, and default theme (`de` or `uk`). Default is German gold/orange; the left-nav button toggles UK navy/red.

## Data

- HBlink / RYSEN report opcodes: `CONFIG_SND`, `BRIDGE_SND`, `BRDG_EVENT`, `SERVER_INFO_SND`
- Optional alias files under `data/` (`peer_ids.json`, `user.csv`, `talkgroup_ids.json`)
- No MariaDB. Last heard is in-memory.

This is a per-master sidecar. It does not replace HBmonitor / RYSEN-MONITOR selfcare and does not scrape IPSC2 HTML.

## Install on a System X master

Clone the repo so updates are `git pull`:

```bash
git clone https://github.com/ShaYmez/IPSC2-MONITOR.git /opt/ipsc2-monitor
python3 -m venv /opt/ipsc2-monitor/.venv
/opt/ipsc2-monitor/.venv/bin/pip install -r /opt/ipsc2-monitor/requirements.txt
cp /opt/ipsc2-monitor/ipsc2mon.cfg /etc/rysen/ipsc2mon.cfg
# edit /etc/rysen/ipsc2mon.cfg — RYSEN 127.0.0.1:4321, WEB 127.0.0.1:8088, site title
install -m 644 /opt/ipsc2-monitor/deploy/ipsc2mon.service /etc/systemd/system/ipsc2mon.service
install -m 644 /opt/ipsc2-monitor/deploy/apache-ipsc2.conf /etc/apache2/conf-available/ipsc2-monitor.conf
# Include that Apache snippet from the System X vhost
systemctl daemon-reload
systemctl enable --now ipsc2mon
systemctl reload apache2
```

Update later with `/opt/ipsc2-monitor/deploy/update.sh` (pull + restart). Site settings stay in `/etc/rysen/ipsc2mon.cfg` so a pull does not overwrite them.

The UI is at `https://<master>/legacy/`. REPORT_CLIENTS on HBlink / RYSEN must allow the host (stock is `*`).

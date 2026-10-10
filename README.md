# IPSC2-MONITOR

Legacy IPSC2-style dashboard for a RYSEN / System X master.

It copies the live IPSC2 chrome (STATUS, MONITOR, MATRIX, REMAP, BRIDGE, DONGLE, SERVICE, SITE-INFO) in a modern static frontend, and reads the same TCP report socket that RYSEN-MONITOR uses (`:4321`).

## Run

```bash
pip install -r requirements.txt
python ipsc2mon.py
```

Then open `http://127.0.0.1:8088/`.

Edit `ipsc2mon.cfg` for the RYSEN host/port, site title, contact, and default theme (`de` or `uk`). Default is German gold/orange; the left-nav button toggles UK navy/red.

## Data

- RYSEN report opcodes: `CONFIG_SND`, `BRIDGE_SND`, `BRDG_EVENT`, `SERVER_INFO_SND`
- Optional alias files under `data/` (`peer_ids.json`, `user.csv`, `talkgroup_ids.json`)
- No MariaDB. Last heard is in-memory.

This is a per-master sidecar. It does not replace RYSEN-MONITOR selfcare and does not scrape IPSC2 HTML.

## Install on a System X master

On the host (Apache already proxies `/dashboard/` to the existing UI):

1. Copy this tree to `/opt/ipsc2-monitor`
2. `python3 -m venv /opt/ipsc2-monitor/.venv && .venv/bin/pip install -r requirements.txt`
3. Point `[RYSEN] HOST` at `127.0.0.1` and bind `[WEB] HOST` to `127.0.0.1`
4. Install `deploy/ipsc2mon.service` and `deploy/apache-ipsc2.conf` (include the Apache snippet from the System X vhost)
5. `systemctl enable --now ipsc2mon` and reload Apache

The UI is then at `https://<master>/legacy/`. REPORT_CLIENTS on RYSEN must allow the host (stock is `*`).

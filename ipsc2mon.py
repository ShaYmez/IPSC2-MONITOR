#!/usr/bin/env python3
"""IPSC2-style dashboard sidecar for RYSEN / System X.

Connects to the RYSEN TCP report socket (default :4321), keeps an in-memory
table of peers / bridges / last heard, and serves a static IPSC2-lookalike
UI plus JSON at /api/*.
"""

from __future__ import annotations

import configparser
import csv
import json
import logging
import os
import sys
from collections import deque
from pathlib import Path
from pickle import loads
from time import localtime, strftime, time

from twisted.internet import reactor, task
from twisted.internet.protocol import ReconnectingClientFactory
from twisted.protocols.basic import NetstringReceiver
from twisted.web.resource import Resource
from twisted.web.server import Site
from twisted.web.static import File

NetstringReceiver.MAX_LENGTH = 5_000_000

OPCODE = {
    "CONFIG_SND": "\x01",
    "BRIDGE_SND": "\x03",
    "LINK_EVENT": "\x06",
    "BRDG_EVENT": "\x07",
    "SERVER_INFO_SND": "\x08",
}

ROUTING_MASTER_MODES = ("MASTER", "IPSC", "HYTERA")
HERE = Path(__file__).resolve().parent
WEB_DIR = HERE / "web"

logger = logging.getLogger("ipsc2mon")

CONFIG = {}
BRIDGES = {}
CTABLE = {"MASTERS": {}, "PEERS": {}, "OPENBRIDGES": {}}
LASTHEARD = deque(maxlen=70)
ACTIVE = {}
RYSEN_VERSION = ""
CONFIG_RX = ""
CONNECTED = False
STARTED = time()
SITE = {}
ALIASES = {"peer": {}, "sub": {}, "tg": {}}


def int_id(value):
    if isinstance(value, int):
        return value
    if isinstance(value, bytes):
        return int.from_bytes(value, "big")
    return int(value)


def bytes_4(value):
    return int(value).to_bytes(4, "big")


def field_str(value):
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace").rstrip("\x00").strip()
    if value is None:
        return ""
    return str(value).rstrip("\x00").strip()


def load_cfg(path):
    parser = configparser.ConfigParser()
    parser.read(path, encoding="utf-8")
    rows = max(10, parser.getint("SITE", "LASTHEARD_ROWS", fallback=70))
    global LASTHEARD
    LASTHEARD = deque(LASTHEARD, maxlen=rows)
    return {
        "rysen_host": parser.get("RYSEN", "HOST", fallback="127.0.0.1"),
        "rysen_port": parser.getint("RYSEN", "PORT", fallback=4321),
        "web_host": parser.get("WEB", "HOST", fallback="0.0.0.0"),
        "web_port": parser.getint("WEB", "PORT", fallback=8088),
        "theme": parser.get("WEB", "THEME", fallback="de").strip().lower() or "de",
        "title": parser.get("SITE", "TITLE", fallback="System X"),
        "contact_name": parser.get("SITE", "CONTACT_NAME", fallback=""),
        "contact_country": parser.get("SITE", "CONTACT_COUNTRY", fallback="United Kingdom"),
        "contact_email": parser.get("SITE", "CONTACT_EMAIL", fallback=""),
        "files_path": parser.get("FILES", "PATH", fallback="./data"),
        "peer_file": parser.get("FILES", "PEER_FILE", fallback="peer_ids.json"),
        "sub_file": parser.get("FILES", "SUBSCRIBER_FILE", fallback="user.csv"),
        "tg_file": parser.get("FILES", "TGID_FILE", fallback="talkgroup_ids.json"),
        "log_level": parser.get("LOGGER", "LEVEL", fallback="INFO"),
    }


def now_stamp():
    return strftime("%Y-%m-%d %H:%M:%S", localtime())


def time_since(ts):
    try:
        elapsed = int(time()) - int(ts)
    except (TypeError, ValueError):
        return ""
    if elapsed < 0:
        elapsed = 0
    minutes, seconds = divmod(elapsed, 60)
    hours, minutes = divmod(minutes, 60)
    days, hours = divmod(hours, 24)
    if days:
        return f"{days}d {hours}h"
    if hours:
        return f"{hours}h {minutes}m"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"


def comma_tg_list(value):
    if not value or value is False:
        return []
    parts = value if isinstance(value, (list, tuple)) else str(value).split(",")
    out, seen = [], set()
    for part in parts:
        part = str(part).strip()
        if part.isdigit() and part not in seen:
            seen.add(part)
            out.append(part)
    return out


def numbered_slots_from_options(options_value):
    """Return TS1/TS2 lists plus 1-9 slot maps from Homebrew OPTIONS."""
    ts1, ts2 = [], []
    numbered1, numbered2 = {}, {}
    extra = {}
    if not options_value:
        return ts1, ts2, numbered1, numbered2, extra
    text = field_str(options_value)
    for part in text.split(";"):
        part = part.strip()
        if not part or "=" not in part:
            continue
        key, value = part.split("=", 1)
        key = key.strip().upper()
        value = value.strip()
        if key in ("TS1", "TS1_STATIC"):
            ts1 = comma_tg_list(value)
        elif key in ("TS2", "TS2_STATIC"):
            ts2 = comma_tg_list(value)
        elif len(key) == 5 and key[3] == "_" and key[4].isdigit():
            idx = int(key[4])
            tgs = comma_tg_list(value)
            if key.startswith("TS1"):
                numbered1[idx] = tgs
            elif key.startswith("TS2"):
                numbered2[idx] = tgs
        elif key in ("REFLECTOR", "START_REF", "REF", "START"):
            extra[key] = value
    if numbered1:
        ts1 = [tg for idx in range(1, 10) for tg in numbered1.get(idx, [])]
    if numbered2:
        ts2 = [tg for idx in range(1, 10) for tg in numbered2.get(idx, [])]
    return comma_tg_list(ts1), comma_tg_list(ts2), numbered1, numbered2, extra


def peer_own_options(syscfg, peer_id):
    if peer_id is not None:
        peer = (syscfg.get("PEERS") or {}).get(peer_id) or {}
        options = peer.get("OPTIONS")
        if options:
            return options
        if syscfg.get("MODE") == "MASTER":
            return ""
    return syscfg.get("OPTIONS") or ""


def alias_call(radio_id, kind="sub"):
    try:
        rid = int(radio_id)
    except (TypeError, ValueError):
        return str(radio_id or "")
    rec = ALIASES[kind].get(rid)
    if not rec:
        return str(rid)
    if isinstance(rec, dict):
        return rec.get("CALLSIGN") or rec.get("NAME") or str(rid)
    return str(rec)


def alias_name(radio_id, kind="sub"):
    try:
        rid = int(radio_id)
    except (TypeError, ValueError):
        return ""
    rec = ALIASES[kind].get(rid)
    if isinstance(rec, dict):
        return rec.get("NAME") or rec.get("CITY") or ""
    return ""


def alias_tg(tgid):
    try:
        tid = int(tgid)
    except (TypeError, ValueError):
        return ""
    rec = ALIASES["tg"].get(tid)
    if isinstance(rec, dict):
        return rec.get("NAME") or rec.get("CALLSIGN") or ""
    if rec:
        return str(rec)
    return ""


def load_alias_files(cfg):
    base = Path(cfg["files_path"])
    if not base.is_absolute():
        base = HERE / base
    _load_json_aliases(base / cfg["peer_file"], "peer")
    _load_json_aliases(base / cfg["tg_file"], "tg")
    _load_subscriber_file(base / cfg["sub_file"])


def _records_from_json(path):
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.info("Alias file %s skipped: %s", path, exc)
        return []
    if isinstance(data, dict):
        for key in ("rptrs", "users", "talkgroups", "results"):
            if key in data and isinstance(data[key], list):
                return data[key]
        if all(str(k).isdigit() for k in list(data)[:5] or [0]):
            return [{"id": k, "callsign": v} for k, v in data.items()]
    if isinstance(data, list):
        return data
    return []


def _load_json_aliases(path, kind):
    if not path.is_file():
        return
    for rec in _records_from_json(path):
        try:
            rid = int(rec.get("id") or rec.get("ID"))
        except (TypeError, ValueError, AttributeError):
            continue
        if not isinstance(rec, dict):
            ALIASES[kind][rid] = {"CALLSIGN": str(rec)}
            continue
        ALIASES[kind][rid] = {
            "CALLSIGN": rec.get("callsign") or rec.get("call_sign") or rec.get("CALLSIGN") or "",
            "NAME": rec.get("name") or rec.get("fname") or rec.get("NAME") or "",
            "CITY": rec.get("city") or "",
            "STATE": rec.get("state") or "",
        }
    logger.info("Loaded %s %s aliases from %s", len(ALIASES[kind]), kind, path.name)


def _load_subscriber_file(path):
    if not path.is_file():
        return
    if path.suffix.lower() == ".json":
        _load_json_aliases(path, "sub")
        return
    try:
        with path.open("r", encoding="utf-8", errors="replace") as handle:
            reader = csv.DictReader(handle)
            for rec in reader:
                try:
                    rid = int(rec.get("RADIO_ID") or rec.get("RADIOID") or rec.get("id") or 0)
                except (TypeError, ValueError):
                    continue
                if rid <= 0:
                    continue
                name = rec.get("FIRST_NAME") or rec.get("fname") or rec.get("NAME") or ""
                ALIASES["sub"][rid] = {
                    "CALLSIGN": rec.get("CALLSIGN") or rec.get("callsign") or "",
                    "NAME": name,
                }
        logger.info("Loaded %s subscriber aliases from %s", len(ALIASES["sub"]), path.name)
    except Exception as exc:
        logger.info("Subscriber file %s skipped: %s", path, exc)


def format_freq(value):
    text = field_str(value)
    if not text or text in ("0", "000000000"):
        return "", ""
    if text[:1] == "0" or text[:3] == "000":
        return "N/A", ""
    if text.isdigit() and len(text) >= 7:
        mhz = f"{text[:3]}.{text[3:7]}"
        return mhz, text
    try:
        hz = int(value)
        return f"{hz / 1_000_000:.4f}", str(hz)
    except (TypeError, ValueError):
        return text, text


def qrg_text(tx, rx, slots):
    tx_mhz, tx_raw = format_freq(tx)
    rx_mhz, rx_raw = format_freq(rx)
    if not tx_mhz or tx_mhz == "N/A":
        return "0.0000"
    offset = ""
    try:
        if tx_raw and rx_raw and tx_raw.isdigit() and rx_raw.isdigit():
            delta = (int(tx_raw) - int(rx_raw)) / 1_000_000
            if abs(delta) >= 0.05:
                offset = f"@{'+' if delta > 0 else ''}{delta:.1f}"
    except (TypeError, ValueError):
        offset = ""
    return f"{tx_mhz}{offset}"


def slots_label(value):
    text = field_str(value)
    if text in ("0",):
        return "NONE", "0", "DMO"
    if text in ("1", "2"):
        return text, text, "OPTIONS"
    if text == "3":
        return "Duplex", "3", "OPTIONS"
    return "Simplex", "4", "DMO"


def classify_peer(peer_id, peer):
    protocol = peer.get("PROTOCOL") or "HOMEBREW"
    pid = str(peer_id)
    rx = peer.get("RX_FREQ") or ""
    tx = peer.get("TX_FREQ") or ""
    if protocol in ("IPSC", "HYTERA"):
        return "repeater"
    if protocol == "OPENBRIDGE":
        return "bridge"
    if rx in ("N/A", "") and tx in ("N/A", ""):
        return "bridge"
    if len(pid) >= 7:
        return "hotspot"
    return "repeater"


def empty_slot():
    return {
        "TS": False,
        "TRX": "",
        "CALL": "",
        "SRC": "",
        "DEST": "",
        "TG": "",
        "SID": "",
        "RSSI": "",
        "TIMEOUT": 0,
        "TYPE": "",
    }


def apply_peer_fields(peer_conf, peer_id):
    tx_mhz, _ = format_freq(peer_conf.get("TX_FREQ"))
    rx_mhz, _ = format_freq(peer_conf.get("RX_FREQ"))
    if peer_conf.get("PROTOCOL") == "HYTERA":
        try:
            tx_mhz = f"{int(peer_conf.get('TX_FREQ') or 0) / 1_000_000:.6f} MHz"
            rx_mhz = f"{int(peer_conf.get('RX_FREQ') or 0) / 1_000_000:.6f} MHz"
        except (TypeError, ValueError):
            tx_mhz = rx_mhz = "N/A"
    slots_name, slots_num, mode = slots_label(peer_conf.get("SLOTS", b"3"))
    radio_id = field_str(peer_conf.get("RADIO_ID")) or str(int_id(peer_id) if not isinstance(peer_id, int) else peer_id)
    callsign = field_str(peer_conf.get("CALLSIGN"))
    if not callsign or callsign == radio_id:
        callsign = alias_call(radio_id, "peer")
        if callsign == str(radio_id):
            callsign = field_str(peer_conf.get("CALLSIGN")) or radio_id
    location = field_str(peer_conf.get("LOCATION")) or alias_name(radio_id, "peer")
    ts1, ts2, n1, n2, extra = numbered_slots_from_options(peer_conf.get("OPTIONS"))
    proto = field_str(peer_conf.get("PROTOCOL")) or "HOMEBREW"
    return {
        "ID": int_id(peer_id) if not isinstance(peer_id, int) else peer_id,
        "RADIO_ID": radio_id,
        "CALLSIGN": callsign,
        "LOCATION": location,
        "PROTOCOL": proto,
        "TX_FREQ": tx_mhz or "N/A",
        "RX_FREQ": rx_mhz or "N/A",
        "QRG": qrg_text(peer_conf.get("TX_FREQ"), peer_conf.get("RX_FREQ"), slots_num),
        "SLOTS": slots_name,
        "SLOTS_NUM": slots_num,
        "CONFIG": mode if (ts1 or ts2) else ("DMO" if slots_num == "4" else "OPTIONS"),
        "PACKAGE_ID": field_str(peer_conf.get("PACKAGE_ID")),
        "SOFTWARE_ID": field_str(peer_conf.get("SOFTWARE_ID")),
        "DESCRIPTION": field_str(peer_conf.get("DESCRIPTION")),
        "CONNECTION": field_str(peer_conf.get("CONNECTION")),
        "CONNECTED": time_since(peer_conf.get("CONNECTED") or 0),
        "CONNECTED_TS": peer_conf.get("CONNECTED") or 0,
        "TS1_STATIC": ts1,
        "TS2_STATIC": ts2,
        "TS1_SLOTS": n1,
        "TS2_SLOTS": n2,
        "REFLECTOR": extra.get("REFLECTOR") or extra.get("REF") or "",
        "START_REF": extra.get("START_REF") or extra.get("START") or "",
        "OPTIONS": field_str(peer_conf.get("OPTIONS")),
        1: empty_slot(),
        2: empty_slot(),
    }


def add_or_refresh_peer(store, peer_id, peer_conf):
    key = int_id(peer_id) if not isinstance(peer_id, int) else peer_id
    existing = store.get(key)
    slots = {}
    if existing:
        slots = {1: existing.get(1) or empty_slot(), 2: existing.get(2) or empty_slot()}
    row = apply_peer_fields(peer_conf, peer_id)
    if slots:
        row[1] = slots[1]
        row[2] = slots[2]
    store[key] = row
    return row


def build_hblink_table(config):
    CTABLE["MASTERS"].clear()
    CTABLE["PEERS"].clear()
    CTABLE["OPENBRIDGES"].clear()
    for name, data in config.items():
        if not data.get("ENABLED"):
            continue
        mode = data.get("MODE")
        if mode in ROUTING_MASTER_MODES:
            CTABLE["MASTERS"][name] = {"MODE": mode, "PEERS": {}}
            for peer_id, peer_conf in (data.get("PEERS") or {}).items():
                if field_str(peer_conf.get("CONNECTION")) != "YES":
                    continue
                add_or_refresh_peer(CTABLE["MASTERS"][name]["PEERS"], peer_id, peer_conf)
        elif mode == "OPENBRIDGE":
            CTABLE["OPENBRIDGES"][name] = {
                "NETWORK_ID": int_id(data.get("NETWORK_ID") or 0),
                "TARGET_IP": field_str(data.get("TARGET_IP")),
                "TARGET_PORT": data.get("TARGET_PORT"),
                "STREAMS": {},
            }
        elif mode in ("PEER", "XLXPEER"):
            CTABLE["PEERS"][name] = {
                "MODE": mode,
                "CALLSIGN": field_str(data.get("CALLSIGN")),
                "RADIO_ID": int_id(data.get("RADIO_ID") or 0),
                "LOCATION": field_str(data.get("LOCATION")),
                1: empty_slot(),
                2: empty_slot(),
            }


def update_hblink_table(config):
    if not CTABLE["MASTERS"] and not CTABLE["OPENBRIDGES"]:
        build_hblink_table(config)
        _apply_options(config)
        return
    seen_masters = set()
    for name, data in config.items():
        if not data.get("ENABLED") or data.get("MODE") not in ROUTING_MASTER_MODES:
            continue
        seen_masters.add(name)
        if name not in CTABLE["MASTERS"]:
            CTABLE["MASTERS"][name] = {"MODE": data.get("MODE"), "PEERS": {}}
        live = set()
        for peer_id, peer_conf in (data.get("PEERS") or {}).items():
            if field_str(peer_conf.get("CONNECTION")) != "YES":
                continue
            key = int_id(peer_id)
            live.add(key)
            add_or_refresh_peer(CTABLE["MASTERS"][name]["PEERS"], peer_id, peer_conf)
        for key in list(CTABLE["MASTERS"][name]["PEERS"]):
            if key not in live:
                del CTABLE["MASTERS"][name]["PEERS"][key]
    for name in list(CTABLE["MASTERS"]):
        if name not in seen_masters:
            del CTABLE["MASTERS"][name]
    _apply_options(config)
    clean_timeouts()


def _apply_options(config):
    for system, master in CTABLE["MASTERS"].items():
        syscfg = config.get(system) or {}
        for peer_id, peer in master["PEERS"].items():
            options = peer_own_options(syscfg, bytes_4(peer_id))
            ts1, ts2, n1, n2, extra = numbered_slots_from_options(options)
            if options:
                peer["OPTIONS"] = field_str(options)
            if ts1:
                peer["TS1_STATIC"] = ts1
            if ts2:
                peer["TS2_STATIC"] = ts2
            if n1:
                peer["TS1_SLOTS"] = n1
            if n2:
                peer["TS2_SLOTS"] = n2
            if extra.get("REFLECTOR") or extra.get("REF"):
                peer["REFLECTOR"] = extra.get("REFLECTOR") or extra.get("REF")
            if extra.get("START_REF") or extra.get("START"):
                peer["START_REF"] = extra.get("START_REF") or extra.get("START")
            if ts1 or ts2:
                peer["CONFIG"] = "OPTIONS"


def clean_timeouts():
    timeout = time()
    for master in CTABLE["MASTERS"].values():
        for peer in master["PEERS"].values():
            for ts in (1, 2):
                slot = peer.get(ts) or {}
                if slot.get("TS") and timeout - float(slot.get("TIMEOUT") or 0) > 180:
                    peer[ts] = empty_slot()
    for system in list(CTABLE["OPENBRIDGES"]):
        streams = CTABLE["OPENBRIDGES"][system].get("STREAMS") or {}
        for sid, stream in list(streams.items()):
            ts = stream.get("TIMEOUT", 0) if isinstance(stream, dict) else (stream[3] if len(stream) > 3 else 0)
            if timeout - float(ts or 0) > 180:
                del streams[sid]


def hw_label(peer):
    proto = (peer.get("PROTOCOL") or "").upper()
    kind = classify_peer(peer.get("ID"), peer)
    if proto == "IPSC":
        return "IPSC"
    if proto == "HYTERA":
        return "HYT"
    if proto == "OPENBRIDGE" or kind == "bridge":
        return "OBP"
    if kind == "hotspot":
        return "MMD"
    return "HB"


def rptr_role(peer):
    kind = classify_peer(peer.get("ID"), peer)
    if kind == "hotspot":
        return "HOTSPOT"
    if kind == "bridge":
        return "REFL"
    return peer.get("CALLSIGN") or ""


def iter_peers():
    for system, master in CTABLE["MASTERS"].items():
        for peer in master["PEERS"].values():
            yield system, peer


def find_peer(peer_id):
    try:
        pid = int(peer_id)
    except (TypeError, ValueError):
        return None
    for _, peer in iter_peers():
        if peer.get("ID") == pid or str(peer.get("RADIO_ID")) == str(pid):
            return peer
    return None


def slot_state(slot):
    trx = (slot or {}).get("TRX") or ""
    if trx in ("RX", "UNIT_TX"):
        return "rx"
    if trx in ("TX", "UNIT_RX"):
        return "tx"
    return ""


def rts_update(parts):
    if len(parts) < 9:
        return
    call_type = parts[0]
    action = parts[1]
    trx = parts[2]
    system = parts[3]
    stream_id = parts[4]
    try:
        source_peer = int(parts[5])
        source_sub = int(parts[6])
        time_slot = int(parts[7])
        destination = int(parts[8])
    except (TypeError, ValueError):
        return
    if time_slot not in (1, 2):
        return
    timeout = time()
    call = alias_call(source_sub, "sub")
    if system in CTABLE["MASTERS"]:
        for peer_id, peer in CTABLE["MASTERS"][system]["PEERS"].items():
            slot = peer[time_slot]
            crx = "RX" if source_peer == peer_id else "TX"
            if action == "START":
                slot.update({
                    "TIMEOUT": timeout,
                    "TS": True,
                    "TYPE": call_type,
                    "CALL": call,
                    "SRC": source_sub,
                    "DEST": destination,
                    "TG": str(destination),
                    "TRX": crx,
                    "SID": stream_id,
                    "RSSI": _event_rssi(parts) if crx == "RX" else slot.get("RSSI", ""),
                })
            elif action == "RSSI" and slot.get("SID") == stream_id:
                slot["RSSI"] = _event_rssi(parts)
            elif action == "END" and (not slot.get("SID") or slot.get("SID") == stream_id):
                peer[time_slot] = empty_slot()
    if system in CTABLE["OPENBRIDGES"]:
        streams = CTABLE["OPENBRIDGES"][system]["STREAMS"]
        if action == "START":
            streams[stream_id] = {
                "TRX": trx,
                "CALL": call,
                "SOURCE_ID": source_sub,
                "DEST": destination,
                "TIMEOUT": timeout,
            }
        elif action == "END":
            streams.pop(stream_id, None)
    key = f"{destination}:{time_slot}"
    if action == "START":
        ACTIVE[key] = {
            "tg": destination,
            "ts": time_slot,
            "call": call,
            "radio_id": source_sub,
            "peer": source_peer,
            "name": alias_tg(destination),
        }
    elif action == "END":
        ACTIVE.pop(key, None)


def _event_rssi(parts):
    if len(parts) < 10:
        return ""
    try:
        value = int(float(parts[9]))
    except (TypeError, ValueError):
        return ""
    if value <= 0:
        return ""
    if value < 200:
        return f"-{value} dBm"
    return ""


def record_lastheard(parts):
    if len(parts) < 10:
        return
    if parts[1] != "END" or parts[2] == "TX":
        return
    try:
        duration = float(parts[9])
        source_peer = int(parts[5])
        source_sub = int(parts[6])
        time_slot = int(parts[7])
        destination = int(parts[8])
        stream_id = parts[4]
    except (TypeError, ValueError):
        return
    peer = find_peer(source_peer)
    hw = hw_label(peer) if peer else "MMD"
    role = rptr_role(peer) if peer else "HOTSPOT"
    try:
        floor = f"{int(stream_id):08X}"
    except (TypeError, ValueError):
        floor = str(stream_id)
    LASTHEARD.appendleft({
        "hw": hw,
        "time": now_stamp(),
        "sec": f"{duration:.1f}",
        "rptr": str(source_peer),
        "rptr_call": role,
        "id": source_sub,
        "call": alias_call(source_sub, "sub"),
        "alias": alias_name(source_sub, "sub"),
        "ts": time_slot,
        "tg": destination,
        "ber": "0.0",
        "rssi": "",
        "floor": floor,
    })


def process_message(raw):
    global CONFIG, BRIDGES, RYSEN_VERSION, CONFIG_RX, CONNECTED
    text = raw.decode("utf-8", "ignore")
    opcode = text[:1]
    if opcode == OPCODE["SERVER_INFO_SND"]:
        try:
            info = json.loads(raw[1:].decode("utf-8"))
            RYSEN_VERSION = info.get("rysen_version") or ""
            logger.info("RYSEN version %s", RYSEN_VERSION)
        except Exception as exc:
            logger.debug("SERVER_INFO_SND parse failed: %s", exc)
    elif opcode == OPCODE["CONFIG_SND"]:
        CONFIG = loads(raw[1:])
        CONFIG_RX = now_stamp()
        CONNECTED = True
        update_hblink_table(CONFIG)
        logger.info("CONFIG_SND: %s masters, %s peers",
                    len(CTABLE["MASTERS"]),
                    sum(len(m["PEERS"]) for m in CTABLE["MASTERS"].values()))
    elif opcode == OPCODE["BRIDGE_SND"]:
        BRIDGES = loads(raw[1:])
        logger.info("BRIDGE_SND: %s bridges", len(BRIDGES))
    elif opcode == OPCODE["BRDG_EVENT"]:
        parts = text[1:].split(",")
        if parts and parts[0] in ("GROUP VOICE", "UNIT VOICE"):
            rts_update(parts)
        if parts and parts[0] == "GROUP VOICE" and len(parts) > 9:
            record_lastheard(parts)
    elif opcode == OPCODE["LINK_EVENT"]:
        logger.debug("LINK_EVENT %s", text[1:])


def sorted_peers(kind=None):
    rows = []
    for system, peer in iter_peers():
        peer_kind = classify_peer(peer.get("ID"), peer)
        if kind and peer_kind != kind:
            continue
        rows.append((system, peer))
    rows.sort(key=lambda item: (item[1].get("CALLSIGN") or "", str(item[1].get("ID"))))
    return rows


def status_payload():
    registered = []
    seen = set()
    for item in ACTIVE.values():
        key = (item["tg"], item["ts"])
        if key in seen:
            continue
        seen.add(key)
        registered.append({
            "reflector": str(item["tg"]),
            "name": item.get("name") or "",
            "call_ts1": item["call"] if item["ts"] == 1 else "",
            "net_ts1": alias_tg(item["tg"]) if item["ts"] == 1 else "",
            "call_ts2": item["call"] if item["ts"] == 2 else "",
            "net_ts2": alias_tg(item["tg"]) if item["ts"] == 2 else "",
            "state": "rx",
        })
    registered.sort(key=lambda row: int(row["reflector"]) if str(row["reflector"]).isdigit() else 0)
    links = []
    for _, peer in sorted_peers():
        s1, s2 = peer.get(1) or {}, peer.get(2) or {}
        ts1 = " ".join(peer.get("TS1_STATIC") or [])
        ts2 = " ".join(peer.get("TS2_STATIC") or [])
        links.append({
            "repeater": peer.get("CALLSIGN") or "",
            "info": peer.get("LOCATION") or "",
            "id": str(peer.get("RADIO_ID") or peer.get("ID") or ""),
            "ts1": ts1,
            "cq": "CQ" if (s1.get("TS") or s2.get("TS")) else "",
            "ts1_info": s1.get("CALL") or "",
            "ts2": ts2,
            "ts2_info": s2.get("CALL") or "",
            "ref": peer.get("REFLECTOR") or "",
            "start": peer.get("START_REF") or "",
            "hardware": peer.get("PACKAGE_ID") or hw_label(peer),
            "kind": classify_peer(peer.get("ID"), peer),
            "ts1_state": slot_state(s1),
            "ts2_state": slot_state(s2),
            "connected": peer.get("CONNECTED") or "",
        })
    return {
        "stamp": now_stamp(),
        "version": RYSEN_VERSION or "System X",
        "ww_cq": sorted({str(item["tg"]) for item in ACTIVE.values()}),
        "registered": registered,
        "links": links,
    }


def monitor_payload():
    rows = []
    for idx, rec in enumerate(LASTHEARD, 1):
        rows.append({"nr": idx, **rec})
    return {"stamp": now_stamp(), "version": RYSEN_VERSION or "System X", "rows": rows}


def matrix_payload():
    def grid(slot_key):
        tgs = []
        seen = set()
        peers = []
        for _, peer in sorted_peers():
            values = peer.get(slot_key) or []
            peers.append({
                "rptr": peer.get("CALLSIGN") or "",
                "id": str(peer.get("RADIO_ID") or peer.get("ID") or ""),
                "info": (peer.get("LOCATION") or "")[:22],
                "marks": values,
            })
            for tg in values:
                if tg not in seen:
                    seen.add(tg)
                    tgs.append(tg)
        tgs.sort(key=lambda item: int(item) if item.isdigit() else 0)
        return {"tgs": tgs, "rows": peers}

    return {"stamp": now_stamp(), "ts1": grid("TS1_STATIC"), "ts2": grid("TS2_STATIC")}


def remap_payload():
    rows = []
    for name, systems in (BRIDGES or {}).items():
        if not isinstance(systems, list):
            continue
        for system in systems:
            try:
                tgid = int_id(system.get("TGID"))
            except Exception:
                continue
            rows.append({
                "name": name,
                "tg": tgid,
                "ts": system.get("TS"),
                "reflector": field_str(system.get("SYSTEM")),
                "on": ", ".join(str(int_id(x)) for x in (system.get("ON") or [])[:3]),
                "off": ", ".join(str(int_id(x)) for x in (system.get("OFF") or [])[:3]),
                "active": "ON" if system.get("ACTIVE") else "OFF",
            })
    return {"stamp": now_stamp(), "rows": rows}


def bridge_payload():
    rows = []
    for name, systems in (BRIDGES or {}).items():
        if not isinstance(systems, list):
            continue
        for system in systems:
            try:
                tgid = int_id(system.get("TGID"))
            except Exception:
                continue
            active = "Connected" if system.get("ACTIVE") else "stand by"
            rows.append({
                "tg": tgid,
                "info": alias_tg(tgid) or name,
                "ts": system.get("TS"),
                "type": field_str(system.get("SYSTEM")) or "bridge",
                "active": active,
            })
    for name, obp in CTABLE["OPENBRIDGES"].items():
        live = "active" if obp.get("STREAMS") else "stand by"
        rows.append({
            "tg": obp.get("NETWORK_ID"),
            "info": name,
            "ts": "",
            "type": "OpenBridge",
            "active": live,
        })
    return {"stamp": now_stamp(), "rows": rows}


def dongle_payload():
    rows = []
    for _, peer in sorted_peers("hotspot"):
        s1, s2 = peer.get(1) or {}, peer.get(2) or {}
        static = (peer.get("TS1_STATIC") or []) + (peer.get("TS2_STATIC") or [])
        rows.append({
            "call": peer.get("CALLSIGN") or "",
            "prot": hw_label(peer),
            "ref": (peer.get("REFLECTOR") or (static[0] if static else "")),
            "id": str(peer.get("RADIO_ID") or peer.get("ID") or ""),
            "sv": "1" if peer.get("CONNECTION") == "YES" else "0",
            "ts1_state": slot_state(s1),
            "ts2_state": slot_state(s2),
        })
    return {"stamp": now_stamp(), "rows": rows}


def service_payload():
    rows = []
    for _, peer in sorted_peers():
        n1 = peer.get("TS1_SLOTS") or {}
        n2 = peer.get("TS2_SLOTS") or {}
        if not n1 and peer.get("TS1_STATIC"):
            n1 = {i + 1: [tg] for i, tg in enumerate(peer["TS1_STATIC"][:9])}
        if not n2 and peer.get("TS2_STATIC"):
            n2 = {i + 1: [tg] for i, tg in enumerate(peer["TS2_STATIC"][:9])}
        rows.append({
            "config": peer.get("CONFIG") or "DMO",
            "hardware": hw_label(peer),
            "rptr": str(peer.get("RADIO_ID") or peer.get("ID") or ""),
            "call": peer.get("CALLSIGN") or "",
            "qrg": peer.get("QRG") or "0.0000",
            "slot": peer.get("SLOTS_NUM") or "4",
            "ts1": [",".join(n1.get(i) or ["0"]) for i in range(1, 10)],
            "ts2": [",".join(n2.get(i) or ["0"]) for i in range(1, 10)],
            "refl": peer.get("REFLECTOR") or "4000",
            "min": peer.get("START_REF") or "15",
            "firm": peer.get("SOFTWARE_ID") or "",
            "ser": peer.get("PACKAGE_ID") or "",
        })
    return {
        "stamp": now_stamp(),
        "version": RYSEN_VERSION or "System X",
        "email": SITE.get("contact_email") or "",
        "rows": rows,
    }


def site_payload():
    return {
        "title": SITE.get("title") or "System X",
        "theme": SITE.get("theme") or "uk",
        "version": RYSEN_VERSION or "",
        "connected": CONNECTED,
        "config_rx": CONFIG_RX,
        "uptime": time_since(STARTED),
        "contact_name": SITE.get("contact_name") or "",
        "contact_country": SITE.get("contact_country") or "",
        "contact_email": SITE.get("contact_email") or "",
        "peer_count": sum(len(m["PEERS"]) for m in CTABLE["MASTERS"].values()),
        "bridge_count": len(BRIDGES or {}),
    }


HANDLERS = {
    "status": status_payload,
    "monitor": monitor_payload,
    "matrix": matrix_payload,
    "remap": remap_payload,
    "bridge": bridge_payload,
    "dongle": dongle_payload,
    "service": service_payload,
    "site": site_payload,
}


class ApiLeaf(Resource):
    isLeaf = True

    def __init__(self, name):
        super().__init__()
        self.name = name

    def render_GET(self, request):
        request.setHeader(b"content-type", b"application/json; charset=utf-8")
        request.setHeader(b"cache-control", b"no-store")
        payload = HANDLERS[self.name]()
        return json.dumps(payload).encode("utf-8")


class ApiRoot(Resource):
    def getChild(self, path, request):
        name = path.decode("utf-8") if isinstance(path, bytes) else path
        if name in HANDLERS:
            return ApiLeaf(name)
        return Resource.getChild(self, path, request)


class Report(NetstringReceiver):
    def stringReceived(self, data):
        try:
            process_message(data)
        except Exception:
            logger.exception("process_message failed")


class ReportFactory(ReconnectingClientFactory):
    def startedConnecting(self, connector):
        logger.info("Connecting to RYSEN report %s", connector.getDestination())

    def buildProtocol(self, addr):
        global CONNECTED
        CONNECTED = True
        self.resetDelay()
        logger.info("Connected to RYSEN report %s", addr)
        return Report()

    def clientConnectionLost(self, connector, reason):
        global CONNECTED
        CONNECTED = False
        CTABLE["MASTERS"].clear()
        CTABLE["PEERS"].clear()
        CTABLE["OPENBRIDGES"].clear()
        ACTIVE.clear()
        logger.info("Lost RYSEN report: %s", reason)
        ReconnectingClientFactory.clientConnectionLost(self, connector, reason)

    def clientConnectionFailed(self, connector, reason):
        global CONNECTED
        CONNECTED = False
        logger.info("RYSEN report failed: %s", reason)
        ReconnectingClientFactory.clientConnectionFailed(self, connector, reason)


def main(argv=None):
    argv = list(argv or sys.argv[1:])
    cfg_path = HERE / "ipsc2mon.cfg"
    if argv and not argv[0].startswith("-"):
        cfg_path = Path(argv[0])
    if not cfg_path.is_file():
        print(f"Config not found: {cfg_path}", file=sys.stderr)
        return 1
    cfg = load_cfg(cfg_path)
    SITE.update(cfg)
    logging.basicConfig(
        level=getattr(logging, cfg["log_level"].upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    load_alias_files(cfg)

    root = File(str(WEB_DIR))
    root.putChild(b"api", ApiRoot())
    site = Site(root)
    reactor.listenTCP(cfg["web_port"], site, interface=cfg["web_host"])
    reactor.connectTCP(cfg["rysen_host"], cfg["rysen_port"], ReportFactory())
    task.LoopingCall(clean_timeouts).start(30, now=False)
    logger.info(
        "IPSC2-MONITOR serving http://%s:%s  (RYSEN %s:%s)",
        cfg["web_host"], cfg["web_port"], cfg["rysen_host"], cfg["rysen_port"],
    )
    reactor.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())

#!/usr/bin/env python3
"""Private-call and DATA last-heard follow RYSEN / RYSEN-MONITOR telemetry."""
import unittest

import ipsc2mon as mon


def _peer(peer_id, radio_id=None):
    return {
        "ID": peer_id,
        "RADIO_ID": str(radio_id or peer_id),
        "CALLSIGN": f"MB{peer_id}",
        "LOCATION": "UK",
        "PROTOCOL": "HOMEBREW",
        "TX_FREQ": "430.0000",
        "RX_FREQ": "430.0000",
        "CONNECTION": "YES",
        1: mon.empty_slot(),
        2: mon.empty_slot(),
    }


def _event(kind, action, system, peer, slot="1", trx="RX", stream="900", dest="2345875"):
    parts = [
        kind, action, trx, system, stream,
        str(peer), "2348831", slot, dest,
    ]
    if action in ("END", "TO END") or kind == "GROUP VOICE":
        parts.append("4.20")
    return parts


class TestUnitAndData(unittest.TestCase):
    def setUp(self):
        mon.CTABLE["MASTERS"].clear()
        mon.CTABLE["PEERS"].clear()
        mon.CTABLE["OPENBRIDGES"].clear()
        mon.ACTIVE.clear()
        mon.HANG.clear()
        mon.LASTHEARD.clear()
        mon.UNIT_SMS_RECENT.clear()
        mon.ALIASES["sub"].clear()
        mon.ALIASES["sub"].update({
            2348831: "M0CALL",
            2345875: "G0DEST",
        })
        mon.CTABLE["MASTERS"]["MASTER-A"] = {
            "PEERS": {111: _peer(111, 234111), 112: _peer(112, 234112)}}
        mon.CTABLE["MASTERS"]["MASTER-B"] = {
            "PEERS": {222: _peer(222, 234222)}}
        mon.CTABLE["OPENBRIDGES"]["OBP-EU"] = {"STREAMS": {}}

    def test_origin_and_delivery_paint_only_reported_peers(self):
        mon.rts_update(_event("UNIT VOICE", "START", "MASTER-A", 111))
        origin = mon.CTABLE["MASTERS"]["MASTER-A"]["PEERS"][111][1]
        other = mon.CTABLE["MASTERS"]["MASTER-A"]["PEERS"][112][1]
        self.assertEqual(origin["TRX"], "UNIT_TX")
        self.assertEqual(origin["CALL"], "M0CALL")
        self.assertEqual(origin["TG"], "PC G0DEST")
        self.assertFalse(other["TS"])

        mon.rts_update(_event("UNIT VOICE", "TO START", "MASTER-B", 222, slot="2", trx="TX"))
        delivery = mon.CTABLE["MASTERS"]["MASTER-B"]["PEERS"][222][2]
        self.assertEqual(delivery["TRX"], "UNIT_RX")
        self.assertEqual(delivery["CALL"], "G0DEST")
        self.assertEqual(delivery["TG"], "PC M0CALL")

        status = mon.status_payload()
        self.assertEqual(status["registered"], [])
        info = [row["ts1_info"] for row in status["links"] if row["id"] == "234111"][0]
        self.assertIn("PC G0DEST", info)
        self.assertIn("M0CALL", info)
        self.assertEqual(
            [row["ts1_state"] for row in status["links"] if row["id"] == "234111"][0],
            "tx",
        )

    def test_unit_call_does_not_bracket_a_dynamic_tg(self):
        mon.rts_update(_event("UNIT VOICE", "START", "MASTER-A", 111))
        peer = mon.CTABLE["MASTERS"]["MASTER-A"]["PEERS"][111]
        self.assertEqual(mon.peer_dynamic_tg(peer, 1), "")

    def test_lastheard_unit_shows_pc_destination(self):
        mon.record_lastheard(_event("UNIT VOICE", "END", "MASTER-A", 111))
        row = mon.LASTHEARD[0]
        self.assertEqual(row["kind"], "unit")
        self.assertEqual(row["tg"], "PC G0DEST")
        self.assertEqual(row["call"], "M0CALL")
        self.assertEqual(row["dest_call"], "G0DEST")

    def test_lastheard_sms_is_data_and_deduped(self):
        sms = [
            "UNIT DATA HEADER", "DATA", "RX", "MASTER-A", "2452713010",
            "111", "2348831", "1", "2345875",
        ]
        mon.record_unit_data_lastheard(sms)
        mon.record_unit_data_lastheard(
            ["UNIT CSBK", "DATA", "RX", "MASTER-A", "2452713010",
             "111", "2348831", "1", "2345875"])
        self.assertEqual(len(mon.LASTHEARD), 1)
        row = mon.LASTHEARD[0]
        self.assertEqual(row["kind"], "data")
        self.assertEqual(row["tg"], "DATA")
        self.assertEqual(row["call"], "M0CALL")
        self.assertEqual(row["dest_call"], "G0DEST")

    def test_bridge_data_blocks_are_silent(self):
        mon.record_unit_data_lastheard(
            ["UNIT DATA", "DATA", "TX", "OBP-EU", "1", "2040", "2348831", "1", "2345875"])
        mon.record_unit_data_lastheard(
            ["UNIT VCSBK 1/2 DATA BLOCK", "DATA", "RX", "MASTER-A",
             "2", "111", "2348831", "1", "2345875"])
        self.assertEqual(len(mon.LASTHEARD), 0)


if __name__ == "__main__":
    unittest.main()

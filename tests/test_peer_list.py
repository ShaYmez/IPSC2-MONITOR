#!/usr/bin/env python3
"""LINK-STATUS sort: 6-digit repeaters first, D-APRS last."""
import unittest

import ipsc2mon as mon


def _peer(call, radio_id, **extra):
    row = {
        "ID": radio_id,
        "RADIO_ID": str(radio_id),
        "CALLSIGN": call,
        "PROTOCOL": extra.get("protocol", "HOMEBREW"),
        "TX_FREQ": extra.get("tx", "430.0000"),
        "RX_FREQ": extra.get("rx", "430.0000"),
    }
    return row


class TestPeerList(unittest.TestCase):
    def test_daprs_is_last(self):
        repeater = _peer("GB7HA", 234101)
        hotspot = _peer("M0HOT", 2341011)
        service = _peer("INFO", 9058)
        bridge = _peer("MX0SXC", 2356427, protocol="OPENBRIDGE", tx="", rx="")
        daprs = _peer("D-APRS", 9059)
        ranked = sorted(
            [hotspot, daprs, repeater, bridge, service],
            key=lambda peer: mon.peer_sort_key((None, peer)),
        )
        self.assertEqual(
            [peer["CALLSIGN"] for peer in ranked],
            ["GB7HA", "M0HOT", "INFO", "MX0SXC", "D-APRS"],
        )

    def test_daprs_compact_callsign(self):
        self.assertTrue(mon.is_daprs_peer({"CALLSIGN": "D APRS"}))
        self.assertFalse(mon.is_daprs_peer({"CALLSIGN": "GB7APRS"}))


if __name__ == "__main__":
    unittest.main()

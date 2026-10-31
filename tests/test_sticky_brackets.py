#!/usr/bin/env python3
"""Sticky last-TG keeps IPSC2 dynamic brackets after RelinkTime."""
import unittest

import ipsc2mon as mon


def _peer(peer_id, radio_id=None, options="", sticky=False, statics=None):
    row = {
        "ID": peer_id,
        "RADIO_ID": str(radio_id or peer_id),
        "CALLSIGN": f"MB{peer_id}",
        "LOCATION": "UK",
        "PROTOCOL": "HOMEBREW",
        "TX_FREQ": "430.0000",
        "RX_FREQ": "430.0000",
        "CONNECTION": "YES",
        "OPTIONS": options,
        "STICKY": sticky,
        "UA_TIMER": 10,
        "TS1_STATIC": list((statics or {}).get(1, [])),
        "TS2_STATIC": list((statics or {}).get(2, [])),
        1: mon.empty_slot(),
        2: mon.empty_slot(),
    }
    return row


class TestStickyBrackets(unittest.TestCase):
    def setUp(self):
        mon.CTABLE["MASTERS"].clear()
        mon.CTABLE["PEERS"].clear()
        mon.CTABLE["OPENBRIDGES"].clear()
        mon.DYNAMIC.clear()
        mon.ACTIVE.clear()
        mon.HANG.clear()

    def test_sticky_flag_and_statics(self):
        self.assertTrue(mon.sticky_flag_from_options("STICKY=1;"))
        self.assertFalse(mon.sticky_flag_from_options(b"STICKY=0;"))
        self.assertIsNone(mon.sticky_flag_from_options("TS2=2350;"))
        self.assertFalse(mon.peer_sticky_enabled(
            {"STICKY_TG": True}, {"STICKY": True}, ["91"], []))
        self.assertFalse(mon.peer_sticky_enabled(
            {"STICKY_TG": True}, {"OPTIONS": "STICKY=0;"}, [], []))
        self.assertTrue(mon.peer_sticky_enabled(
            {"STICKY_TG": True}, {"OPTIONS": "TS1=;TS2=;"}, [], []))

    def test_dynamic_brackets_expire_when_not_sticky(self):
        peer = _peer(111, 234111)
        mon.remember_dynamic(peer, 2, 23516)
        self.assertEqual(mon.mark_keyed_tg("", mon.peer_dynamic_tg(peer, 2)), "(23516)")
        mon.DYNAMIC[mon.dynamic_key(peer, 2)]["until"] = mon.time() - 1
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "")
        self.assertEqual(mon.mark_keyed_tg("", ""), "")

    def test_sticky_dynamic_brackets_survive_after_timer(self):
        peer = _peer(111, 234111, options="TS1=;TS2=;STICKY=1;", sticky=True)
        mon.remember_dynamic(peer, 2, 91)
        key = mon.dynamic_key(peer, 2)
        self.assertIsNone(mon.DYNAMIC[key]["until"])
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "91")
        self.assertEqual(mon.mark_keyed_tg("", "91"), "(91)")

    def test_static_tg_is_never_bracketed(self):
        peer = _peer(111, 234111, statics={2: ["2350"]})
        mon.remember_dynamic(peer, 2, 2350)
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "")
        self.assertEqual(mon.mark_keyed_tg("2350", "2350"), "2350")

    def test_config_ua_sticky_keeps_brackets(self):
        peer = _peer(111, 234111)
        mon.CTABLE["MASTERS"]["MASTER-A"] = {"PEERS": {111: peer}}
        config = {
            "MASTER-A": {
                "ENABLED": True,
                "MODE": "MASTER",
                "STICKY_TG": True,
                "PEERS": {
                    mon.bytes_4(111): {
                        "OPTIONS": "TS1=;TS2=;STICKY=1;",
                        "STICKY": True,
                        "UA": {2: {"TGID": 91, "EXPIRES": None}},
                    }
                },
            }
        }
        mon._apply_options(config)
        self.assertTrue(peer["STICKY"])
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "91")
        self.assertEqual(
            mon.mark_keyed_tg(" ".join(peer.get("TS2_STATIC") or []), "91"),
            "(91)",
        )

    def test_config_ua_empty_clears_brackets(self):
        peer = _peer(111, 234111, sticky=True)
        mon.remember_dynamic(peer, 2, 91)
        mon.CTABLE["MASTERS"]["MASTER-A"] = {"PEERS": {111: peer}}
        mon._apply_options({
            "MASTER-A": {
                "ENABLED": True,
                "MODE": "MASTER",
                "PEERS": {
                    mon.bytes_4(111): {
                        "OPTIONS": "TS1=;TS2=;STICKY=1;",
                        "STICKY": True,
                        "UA": {},
                    }
                },
            }
        })
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "")

    def test_missing_ua_keeps_event_sticky_dynamic(self):
        peer = _peer(111, 234111, sticky=True)
        mon.remember_dynamic(peer, 2, 91)
        mon.CTABLE["MASTERS"]["MASTER-A"] = {"PEERS": {111: peer}}
        mon._apply_options({
            "MASTER-A": {
                "ENABLED": True,
                "MODE": "MASTER",
                "STICKY_TG": True,
                "PEERS": {
                    mon.bytes_4(111): {
                        "OPTIONS": "TS1=;TS2=;STICKY=1;",
                        "STICKY": True,
                    }
                },
            }
        })
        self.assertEqual(mon.peer_dynamic_tg(peer, 2), "91")


if __name__ == "__main__":
    unittest.main()

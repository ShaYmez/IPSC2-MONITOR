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
    def setUp(self):
        mon.ACTIVE.clear()
        mon.HANG.clear()
        mon.DYNAMIC.clear()

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

    def test_index_cache_busts_css_and_js(self):
        html = mon.versioned_index_html()
        ver = mon.asset_version()
        self.assertIn(f"css/ipsc2.css?v={ver}", html)
        self.assertIn(f"js/app.js?v={ver}", html)
        self.assertIn(f'name="ipsc2-assets" content="{ver}"', html)
        self.assertEqual(mon.site_payload()["assets"], ver)

    def test_dash_version_on_sidebar(self):
        self.assertEqual(mon.dash_version(), "v0.01rc.1")
        html = mon.versioned_index_html()
        self.assertIn(">v0.01rc.1<", html)
        self.assertEqual(mon.site_payload()["dash_version"], "v0.01rc.1")

    def test_z3dmr_hardware_is_tracked_on_app(self):
        peer = _peer("M0VUB", 234587550, protocol="HOMEBREW")
        peer["PACKAGE_ID"] = "Z3DMR"
        peer["SOFTWARE_ID"] = "20261105"
        self.assertEqual(mon.hw_label(peer), "Z3DMR")
        self.assertEqual(mon.app_label(peer), "Z3DMR")
        self.assertTrue(mon.is_app_peer(peer))

    def test_mmdvm_hotspot_stays_off_app(self):
        peer = _peer("M0HOT", 2341011)
        peer["PACKAGE_ID"] = "MMDVM_HS_Hat"
        self.assertEqual(mon.hw_label(peer), "MMDVM")
        self.assertFalse(mon.is_app_peer(peer))

    def test_voxdmr_from_firmware_and_static_tg(self):
        peer = _peer("M0VUB", 234587565)
        peer["PACKAGE_ID"] = "VoxDMR 0.16.1-dirty (android)"
        peer["SOFTWARE_ID"] = "VoxDMR"
        peer["LOCATION"] = "Internet"
        peer["REFLECTOR"] = "4000"
        peer["TS1_STATIC"] = []
        peer["TS2_STATIC"] = ["235"]
        peer[1] = mon.empty_slot()
        peer[2] = mon.empty_slot()
        self.assertEqual(mon.hw_label(peer), "VoxDMR")
        self.assertEqual(mon.app_label(peer), "VoxDMR")
        self.assertTrue(mon.is_app_peer(peer))
        self.assertEqual(mon.app_tg_view(peer), ("235", ""))

    def test_qso_one_still_from_description(self):
        peer = _peer("M7OXP", 2357362)
        peer["DESCRIPTION"] = "qsoone android"
        self.assertEqual(mon.app_label(peer), "QSO One")

    def test_qso_one_from_firmware_and_dynamic_tg(self):
        peer = _peer("M7OXP", 2357362)
        peer["PACKAGE_ID"] = "20250101"
        peer["SOFTWARE_ID"] = "QSOOne"
        peer["LOCATION"] = "QSO One"
        peer["REFLECTOR"] = "4000"
        peer["TS1_STATIC"] = []
        peer["TS2_STATIC"] = []
        peer[1] = mon.empty_slot()
        peer[2] = mon.empty_slot()
        self.assertEqual(mon.hw_label(peer), "QSO One")
        self.assertEqual(mon.app_label(peer), "QSO One")
        self.assertEqual(mon.app_tg_view(peer), ("", ""))
        mon.remember_dynamic(peer, 2, 23426)
        self.assertEqual(mon.app_tg_view(peer), ("23426", ""))

    def test_app_tg_uses_parked_static_not_dial(self):
        peer = _peer("M0VUB", 234587550)
        peer["PACKAGE_ID"] = "Z3DMR"
        peer["REFLECTOR"] = "4000"
        peer["TS2_STATIC"] = ["31320"]
        peer[1] = mon.empty_slot()
        peer[2] = mon.empty_slot()
        self.assertEqual(mon.app_tg_view(peer), ("31320", ""))

    def test_app_tg_lights_live_and_hang(self):
        peer = _peer("M0VUB", 234587550)
        peer["PACKAGE_ID"] = "Z3DMR"
        peer["TS2_STATIC"] = ["31320"]
        peer[1] = mon.empty_slot()
        live = mon.empty_slot()
        live["TS"] = True
        live["TRX"] = "TX"
        live["TG"] = "91"
        live["DEST"] = "91"
        peer[2] = live
        self.assertEqual(mon.app_tg_view(peer), ("91", "tx"))
        peer[2] = mon.empty_slot()
        mon.HANG[("app", 2)] = {
            "ts": 2,
            "peer": 234587550,
            "tg": "91",
            "name": "",
            "call": "M0VUB",
            "radio_id": "234587550",
            "until": mon.time() + 10,
        }
        self.assertEqual(mon.app_tg_view(peer), ("91", "rx-hang"))


if __name__ == "__main__":
    unittest.main()

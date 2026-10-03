import base64
import datetime as dt
import hashlib
import io
import json
import os
import re
import sqlite3
import tempfile
import threading
import unittest
import urllib.error
import urllib.parse
import urllib.request
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import app


ROOM_PAGE = """<div class='divTable'><div class='divTableHead'>DMR Status</div>
<div class='divTableCell'>Link</div><div class='divTableCell'>Wrong room</div></div>
<div class='divTable'><div class='divTableHead'>YSF Status [In Room]</div>
<div class='divTableHeadCell'>Public</div><div class='divTableCell'>On</div>
<div class='divTableHeadCell'>Link</div><div class='divTableCell'><a>US-LZARC</a></div></div>
<div class='divTableHead'>P25 Status</div><div class='divTableCell'>9999</div>"""


class Response:
    def __init__(self, body):
        self.body = body.encode() if isinstance(body, str) else body
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, length): return self.body[:length]


class FeatureTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        old_db = app.DB_PATH
        app.DB_PATH = os.path.join(self.folder.name, "logger.sqlite")
        self.addCleanup(setattr, app, "DB_PATH", old_db)
        for target in (app.SOURCE_STATUS, app.THEME_CACHES, app.STATUS, app.EXCHANGE_REBUILDS):
            mock = patch.dict(target, {}, clear=True)
            mock.start()
            self.addCleanup(mock.stop)
        app.STATUS.update(last_ok=None, error="Setup required")
        mock = patch.object(app.Handler, "log_message", return_value=None)
        mock.start()
        self.addCleanup(mock.stop)
        app.init_db()
        self.settings = app.save_configuration({
            "station_callsign": "N0CALL", "wpsd_url": "http://ysf.test/api/", "rf_freq_mhz": "441.425",
            "password": "testpass", "password_confirm": "testpass", "qrz_api_key": "TEST-KEY",
            "display_timezone": "America/Chicago", "display_time_mode": "local",
        }, initial=True)

    def sources(self):
        form = dict(station_callsign="N0CALL", hotspots_form="yes",
                    hotspot_id_0="primary", hotspot_label_0="YSF desk", hotspot_url_0="http://ysf.test/api/", hotspot_freq_0="441.425",
                    hotspot_id_1="", hotspot_label_1="DMR travel", hotspot_url_1="http://dmr.test/api/", hotspot_freq_1="439.550")
        self.settings = app.save_configuration(form)
        return app.configured_hotspots(self.settings)

    def transmission(self, call, seconds=0, mode="YSF", direction="Net", target="DG-ID 0", duration="8"):
        when = dt.datetime.now(app.UTC).replace(microsecond=0) - dt.timedelta(seconds=seconds)
        return dict(callsign=call, mode=mode, src=direction, target=target, duration=duration, time_utc=when.isoformat())

    def poll(self, source, rows, room=ROOM_PAGE):
        def fetch(request, **kwargs):
            return Response(json.dumps(rows) if "/api/" in request.full_url else room)
        with patch.object(app.urllib.request, "urlopen", side_effect=fetch):
            app.poll_once(app.source_settings(self.settings, source))

    def server(self):
        server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f"http://127.0.0.1:{server.server_port}"

    def request(self, host, path, form=None):
        auth = "Basic " + base64.b64encode(b"N0CALL:testpass").decode()
        request = urllib.request.Request(host + path, headers={"Authorization": auth},
            data=None if form is None else urllib.parse.urlencode(form).encode())
        with urllib.request.urlopen(request) as response:
            return response.read().decode(), response.headers

    def test_voice_modes_use_only_adif_enumerations(self):
        aliases = {"DMR Slot 2": ("DMR", "DMR"), "YSF2DMR": ("YSF", "C4FM"),
                   "D-STAR": ("D-Star", "DSTAR"), "APCO25": ("P25", ""),
                   "NXDN": ("NXDN", ""), "M17": ("M17", "M17"), "Analog FM": ("FM", "")}
        for alias, (mode, submode) in aliases.items():
            with self.subTest(mode=alias):
                parsed = app.parse_row(self.transmission("W1ABC", mode=alias))
                self.assertEqual(parsed[2], mode)
                adif = app.make_adif("W1ABC", mode, dt.datetime.now(app.UTC), "70cm", "441.425", "", "A real chat")
                self.assertIn("<PROP_MODE:8>INTERNET", adif)
                self.assertIn("<BAND:4>70cm", adif)
                if submode:
                    self.assertIn(app.adif_field("SUBMODE", submode), adif)
                else:
                    self.assertNotIn("<SUBMODE", adif)
                if mode in ("P25", "NXDN"):
                    self.assertIn(mode + " | A real chat", adif)
                self.assertIn("<MODE:2>FM" if mode == "FM" else "<MODE:12>DIGITALVOICE", adif)
        self.assertIsNone(app.parse_row(self.transmission("W1ABC", mode="POCSAG")))
        with self.assertRaises(ValueError):
            app.make_adif("W1ABC", "unknown", dt.datetime.now(app.UTC), "70cm", "441.425", "", "")

    def test_eight_character_password_and_source_settings(self):
        self.assertTrue(app.password_matches("testpass", self.settings["password_hash"]))
        with self.assertRaisesRegex(ValueError, "at least 8"):
            app.save_configuration(dict(station_callsign="N0CALL", wpsd_url="http://ysf.test/api/", rf_freq_mhz="441.425",
                                        password="seven77", password_confirm="seven77"))
        sources = self.sources()
        self.assertEqual(sources[0]["id"], "primary")
        self.assertNotEqual(sources[0]["id"], sources[1]["id"])
        self.assertEqual([item["freq"] for item in sources], ["441.425", "439.550"])
        # Older single-source forms cannot silently discard other hotspots.
        updated = app.save_configuration(dict(station_callsign="N0CALL", wpsd_url="http://ysf.test/api/", rf_freq_mhz="441.450"))
        self.assertEqual(len(app.configured_hotspots(updated)), 2)
        self.assertEqual(app.configured_hotspots(updated)[1]["id"], sources[1]["id"])
        before = app.get_settings()
        with self.assertRaisesRegex(ValueError, "different WPSD"):
            app.save_configuration(dict(station_callsign="N0CALL", hotspots_form="yes",
                hotspot_id_0="primary", hotspot_label_0="One", hotspot_url_0="http://ysf.test/api/", hotspot_freq_0="441.425",
                hotspot_id_1="", hotspot_label_1="Two", hotspot_url_1="http://ysf.test/api", hotspot_freq_1="439.550"))
        self.assertEqual(app.get_settings(), before)

    def test_first_run_gui_multisource_fields_and_invalid_draft(self):
        with app.db() as cx:
            cx.execute("DELETE FROM settings")
        host = self.server()
        page, _ = self.request(host, "/setup")
        self.assertIn("name='hotspot_url_0'", page)
        token = re.search(r"name='csrf' value='([^']+)'", page).group(1)
        form = dict(csrf=token, station_callsign="N0CALL", hotspots_form="yes",
                    hotspot_id_0="primary", hotspot_label_0="YSF desk", hotspot_url_0="http://ysf.test/api/", hotspot_freq_0="441.425",
                    hotspot_id_1="", hotspot_label_1="DMR travel", hotspot_url_1="http://dmr.test/api/", hotspot_freq_1="439.550",
                    password="seven77", password_confirm="seven77")
        with self.assertRaises(urllib.error.HTTPError) as error:
            self.request(host, "/setup", form)
        invalid = error.exception.read().decode()
        self.assertIn("at least 8", invalid)
        self.assertIn("DMR travel", invalid)
        self.assertIn("439.550", invalid)
        self.assertFalse(app.settings_ready())
        page, _ = self.request(host, "/setup", dict(form, password="testpass", password_confirm="testpass"))
        self.assertIn("Hotspot Logger", page)
        self.assertTrue(app.settings_ready())
        sources = app.configured_hotspots(app.get_settings())
        self.assertEqual([item["label"] for item in sources], ["YSF desk", "DMR travel"])
        self.assertEqual([item["freq"] for item in sources], ["441.425", "439.550"])

    def test_room_panels_and_historical_room_honesty(self):
        self.assertEqual(app.parse_ysf_room(ROOM_PAGE), "US-LZARC")
        legacy = "<div class='divTableHead'>YSF Net [Linked]</div><div class='divTableCell'><div title='In Room: America Link'>America Li...<br>(YSF21080)</div></div>"
        self.assertEqual(app.parse_ysf_room(legacy), "America Link")
        self.assertEqual(app.parse_ysf_room(ROOM_PAGE.replace("US-LZARC", "Not Linked")), "")
        current = self.transmission("W0WC", seconds=10)
        parsed = app.parse_row(current)
        self.assertEqual(app.observed_ysf_room(current, parsed, self.settings, "US-LZARC"), "US-LZARC")
        old = self.transmission("W0WC", seconds=3600)
        self.assertEqual(app.observed_ysf_room(old, app.parse_row(old), self.settings, "US-LZARC"), "")
        old["room"] = "Yesterday room"
        self.assertEqual(app.observed_ysf_room(old, app.parse_row(old), self.settings, "US-LZARC"), "Yesterday room")

    def test_exchange_evidence_survives_polls_and_is_scoped_to_hotspot(self):
        first, second = self.sources()
        rows = [self.transmission("N0CALL", seconds=45, direction="RF"), self.transmission("W0WC", seconds=25)]
        self.poll(first, rows)
        with app.db() as cx:
            self.assertEqual(cx.execute("SELECT COUNT(*) FROM heard WHERE call='N0CALL'").fetchone()[0], 0)
            self.assertEqual(cx.execute("SELECT exchange_pattern FROM heard").fetchone()[0], "")
        # The same transmission on another source is a different record and
        # cannot use this hotspot's RF transmissions as exchange evidence.
        self.poll(second, [rows[1]])
        self.poll(first, [*rows, self.transmission("N0CALL", seconds=5, direction="RF")])
        with app.db() as cx:
            records = cx.execute("SELECT * FROM heard ORDER BY hotspot_id").fetchall()
            self.assertEqual(len(records), 2)
            self.assertNotEqual(records[0]["id"], records[1]["id"])
            a = next(row for row in records if row["hotspot_id"] == first["id"])
            b = next(row for row in records if row["hotspot_id"] == second["id"])
            self.assertEqual(a["exchange_pattern"], "N0CALL → W0WC → N0CALL")
            self.assertEqual(b["exchange_pattern"], "")
            self.assertEqual(a["ysf_room"], "US-LZARC")
            self.assertIn("YSF room US-LZARC", app.contact_comment(a, self.settings))
        # A later room change cannot rewrite the room captured for a contact.
        self.poll(first, rows, ROOM_PAGE.replace("US-LZARC", "Different room"))
        with app.db() as cx:
            a = cx.execute("SELECT * FROM heard WHERE hotspot_id=?", (first["id"],)).fetchone()
            self.assertEqual(a["ysf_room"], "US-LZARC")

    def test_exchange_rejects_listening_echoes_kerchunks_third_parties_and_long_gaps(self):
        base = dt.datetime.now(app.UTC).replace(microsecond=0)
        def row(call, index, **changes):
            result = dict(id=str(index), hotspot_id="primary", source_url="http://ysf.test/api/", call=call,
                          channel="YSF/US-LZARC/0", direction="RF" if call == "N0CALL" else "Net",
                          duration="8", heard_utc=(base + dt.timedelta(seconds=index * 30)).isoformat())
            result.update(changes)
            return result
        valid = [row("N0CALL", 0), row("W0WC", 1), row("N0CALL", 2)]
        self.assertEqual(app.possible_exchanges(valid, "N0CALL")["1"], "N0CALL → W0WC → N0CALL")
        reverse = [row("W0WC", 0), row("N0CALL", 1), row("W0WC", 2)]
        self.assertEqual(set(app.possible_exchanges(reverse, "N0CALL")), {"0"})
        conversation = [row("W0WC", 0), row("W0WC", 1), row("N0CALL", 2),
                        row("W0WC", 3), row("N0CALL", 4), row("W0WC", 5), row("N0CALL", 6)]
        self.assertEqual(set(app.possible_exchanges(conversation, "N0CALL")), {"0"})
        rejected = [
            [row("W0WC", 0), row("W1ABC", 1), row("W0WC", 2)],
            [row("N0CALL", 0, direction="Net"), row("W0WC", 1), row("N0CALL", 2)],
            [row("N0CALL", 0, duration="0.6"), row("W0WC", 1), row("N0CALL", 2)],
            [row("N0CALL", 0), row("W0WC", 1, channel="YSF/Other room/0"), row("N0CALL", 2)],
            [row("N0CALL", 0), row("W0WC", 1, hotspot_id="other"), row("N0CALL", 2)],
            [row("N0CALL", 0), row("W0WC", 1), row("W1ABC", 2), row("N0CALL", 3)],
            [row("N0CALL", 0), row("W0WC", 1), row("N0CALL", 30)],
            [row("N0CALL", 0), row("W0WC", 1, heard_utc=base.isoformat()), row("N0CALL", 2)],
        ]
        for sample in rejected:
            with self.subTest(sample=sample):
                self.assertEqual(app.possible_exchanges(sample, "N0CALL"), {})

    def test_exchange_accepts_wpsd_format_variations_without_counting_echoes(self):
        base = dt.datetime.now(app.UTC).replace(microsecond=0)
        def row(identity, call, seconds, direction, duration, target):
            raw = self.transmission(call, seconds=seconds, mode="DMR", direction=direction,
                                    duration=duration, target=target)
            entry = app.parse_row(raw)
            return dict(id=identity, hotspot_id="primary", source_url="http://dmr.test/api/",
                        call=call, channel=app.activity_channel(raw, entry, ""), direction=direction,
                        duration=duration, heard_utc=(base - dt.timedelta(seconds=seconds)).isoformat())
        sample = [
            row("a", "N0CALL", 40, "Local RF", "00:08", "TG 91"),
            row("echo", "N0CALL", 39, "Network", "", "TG91"),
            row("b", "W0WC", 20, "Net", "8.4 s", "Talkgroup: 91"),
            row("c", "N0CALL", 5, "RF", "", "91"),
        ]
        self.assertEqual({item["channel"] for item in sample}, {'["DMR", "91", "", ""]'})
        self.assertEqual(app.possible_exchanges(sample, "N0CALL")["b"], "N0CALL → W0WC → N0CALL")
        self.assertEqual(app.duration_seconds("1:02"), 62)
        self.assertEqual(app.duration_seconds("1:02:03"), 3723)
        self.assertEqual(app.duration_seconds("garbage"), -1)

    def test_ysf_exchange_can_use_dg_id_when_room_is_unavailable(self):
        own = self.transmission("N0CALL", seconds=20, direction="RF", target="DG-ID 0")
        other = self.transmission("W0WC", seconds=10, target="DG ID: 0")
        own_entry, other_entry = app.parse_row(own), app.parse_row(other)
        self.assertEqual(app.activity_channel(own, own_entry, ""), '["YSF", "DG-ID 0", "", ""]')
        self.assertEqual(app.activity_channel(other, other_entry, ""), '["YSF", "DG-ID 0", "", ""]')

    def test_poll_marks_exchange_with_realistic_dmr_variations(self):
        _, source = self.sources()
        rows = [
            self.transmission("N0CALL", seconds=40, mode="DMR", direction="Local RF", duration="00:08", target="TG 91"),
            self.transmission("N0CALL", seconds=39, mode="DMR", direction="Network", duration="", target="TG91"),
            self.transmission("W0WC", seconds=20, mode="DMR", direction="Net", duration="8.4 s", target="Talkgroup: 91"),
            self.transmission("N0CALL", seconds=5, mode="DMR", direction="RF", duration="", target="91"),
        ]
        self.poll(source, rows)
        with app.db() as cx:
            contact = cx.execute("SELECT * FROM heard WHERE hotspot_id=? AND call='W0WC'", (source["id"],)).fetchone()
        self.assertEqual(contact["exchange_pattern"], "N0CALL → W0WC → N0CALL")
        page, _ = self.request(self.server(), "/")
        self.assertIn("class='active' href='/?view=exchanges", page)
        self.assertIn("W0WC", page)

    def test_queue_retention_keeps_saved_contacts(self):
        source = app.configured_hotspots(self.settings)[0]
        self.assertEqual(self.settings["queue_retention_days"], "1")
        old = (dt.datetime.now(app.UTC) - dt.timedelta(days=2)).isoformat()
        rows = [app.parse_row(self.transmission(call, seconds=60 + index))
                for index, call in enumerate(("W1ABC", "W2ABC"))]
        with app.db() as cx:
            cx.executemany("INSERT INTO heard (id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES (?,?,?,?,?,?,?,?,?)", rows)
            cx.execute("UPDATE heard SET first_seen=?", (old,))
            cx.execute("UPDATE heard SET logged_at=?,log_status='save',log_adif='<CALL:5>W2ABC<EOR>' WHERE id=?",
                       (old, rows[1][0]))
            cx.execute("INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)",
                       ("old-activity", source["id"], source["url"], "W1ABC", "YSF", "Net", old, "8"))
        self.poll(source, [self.transmission("W3ABC", seconds=5)])
        with app.db() as cx:
            self.assertIsNone(cx.execute("SELECT id FROM heard WHERE id=?", (rows[0][0],)).fetchone())
            self.assertIsNotNone(cx.execute("SELECT id FROM heard WHERE id=?", (rows[1][0],)).fetchone())
            self.assertIsNone(cx.execute("SELECT id FROM activity WHERE id='old-activity'").fetchone())

    def test_busy_hotspot_storage_is_capped(self):
        source = app.configured_hotspots(self.settings)[0]
        now = dt.datetime.now(app.UTC).isoformat()
        with app.db() as cx:
            cx.executemany("""INSERT INTO heard
                (id,call,mode,target,direction,heard_utc,duration,raw,first_seen,hotspot_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)""",
                ((f"heard-{index:05d}", "W1ABC", "YSF", "DG-ID 0", "Net", now, "8", "{}", now, source["id"])
                 for index in range(app.MAX_UNLOGGED_PER_HOTSPOT + 2)))
            cx.executemany("INSERT INTO activity VALUES(?,?,?,?,?,?,?,?)",
                ((f"activity-{index:05d}", source["id"], source["url"], "W1ABC", "YSF", "Net", now, "8")
                 for index in range(app.MAX_ACTIVITY_PER_HOTSPOT + 2)))
        self.poll(source, [self.transmission("W3ABC", seconds=5)])
        with app.db() as cx:
            heard_count = cx.execute("SELECT COUNT(*) FROM heard WHERE hotspot_id=? AND logged_at IS NULL", (source["id"],)).fetchone()[0]
            activity_count = cx.execute("SELECT COUNT(*) FROM activity WHERE hotspot_id=?", (source["id"],)).fetchone()[0]
        self.assertLessEqual(heard_count, app.MAX_UNLOGGED_PER_HOTSPOT)
        self.assertLessEqual(activity_count, app.MAX_ACTIVITY_PER_HOTSPOT)

    def test_gui_filters_review_frequency_protocol_and_scoped_clear(self):
        first, second = self.sources()
        self.poll(first, [self.transmission("W0WC", seconds=10)])
        self.poll(second, [self.transmission("K9XYZ", seconds=10, mode="NXDN", target="65000")])
        host = self.server()
        with app.db() as cx:
            ysfr = cx.execute("SELECT * FROM heard WHERE hotspot_id=?", (first["id"],)).fetchone()
            nx = cx.execute("SELECT * FROM heard WHERE hotspot_id=?", (second["id"],)).fetchone()
        page, _ = self.request(host, "/?view=queue&hotspot=" + second["id"])
        self.assertIn("K9XYZ", page)
        self.assertNotIn("W0WC", page)
        self.assertIn("<th>Local time</th>", page)
        self.assertIn("Times America/Chicago", page)
        utc_page, _ = self.request(host, "/?view=queue&clock=utc&hotspot=" + second["id"])
        self.assertIn("<th>UTC time</th>", utc_page)
        review, _ = self.request(host, "/review?id=" + nx["id"])
        self.assertIn("439.550", review)
        self.assertNotIn("441.425", review)
        self.assertIn("NXDN 65000", review)
        self.assertIn("Heard only", review)
        self.assertIn("Local:", review)
        self.assertIn("America/Chicago", review)
        settings_page, headers = self.request(host, "/settings")
        self.assertIn("Add hotspot", settings_page)
        self.assertIn("YSF desk", settings_page)
        self.assertIn("DMR travel", settings_page)
        self.assertIn("script-src 'sha256-", headers["Content-Security-Policy"])
        script = re.search(r"<script>(.*?)</script>", settings_page, re.S).group(1)
        digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
        self.assertIn("'sha256-" + digest + "'", headers["Content-Security-Policy"])
        token = app.form_token(self.settings)
        form = dict(csrf=token, id=nx["id"], call="K9XYZ", when=nx["heard_utc"][:19], freq="439.550", band="70cm",
                    mode="NXDN", prop_mode="INTERNET", action="qrz", comment="A chat on TG 65000")
        with patch.object(app, "qrz_insert", return_value="321") as upload:
            self.request(host, "/log", form)
        sent = upload.call_args.args[0]
        self.assertIn("<MODE:12>DIGITALVOICE", sent)
        self.assertNotIn("<SUBMODE", sent)
        self.assertIn("NXDN | A chat", sent)
        self.assertIn("<PROP_MODE:8>INTERNET", sent)
        # Clear the YSF source while retaining the other source's saved QSO.
        self.request(host, "/clear", dict(csrf=token, confirm="yes", hotspot=first["id"]))
        self.poll(first, [self.transmission("W0WC", seconds=10)])
        with app.db() as cx:
            self.assertIsNone(cx.execute("SELECT id FROM heard WHERE id=?", (ysfr["id"],)).fetchone())
            self.assertEqual(cx.execute("SELECT log_status FROM heard WHERE id=?", (nx["id"],)).fetchone()[0], "qrz")

    def test_v05_database_upgrade_preserves_records_password_and_removed_ids(self):
        old_adif = "<CALL:4>W0WC<EOR>"
        with app.db() as cx:
            cx.execute("DROP TABLE heard")
            cx.execute("""CREATE TABLE heard(id TEXT PRIMARY KEY,call TEXT NOT NULL,mode TEXT NOT NULL,target TEXT NOT NULL,
                direction TEXT NOT NULL,heard_utc TEXT NOT NULL,duration TEXT NOT NULL,raw TEXT NOT NULL,first_seen TEXT NOT NULL,
                logged_at TEXT,qrz_logid TEXT,log_adif TEXT,log_status TEXT)""")
            cx.execute("INSERT INTO heard VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", ("existing", "W0WC", "YSF", "DG-ID 0", "Net", "2026-10-01T00:00:00+00:00", "8", "{}", "2026-10-01", "2026-10-01", "123", old_adif, "qrz"))
            cx.execute("INSERT INTO removed VALUES('gone')")
            cx.execute("DELETE FROM settings WHERE key='hotspots'")
        password = app.get_settings()["password_hash"]
        app.init_db()
        app.init_db()
        with app.db() as cx:
            migrated = cx.execute("SELECT * FROM heard").fetchone()
            self.assertEqual(migrated["hotspot_id"], "primary")
            self.assertEqual(migrated["log_adif"], old_adif)
            self.assertEqual(migrated["qrz_logid"], "123")
            self.assertEqual(migrated["ysf_room"], "")
            self.assertEqual(cx.execute("SELECT id FROM removed").fetchone()[0], "gone")
        self.assertEqual(app.get_settings()["password_hash"], password)
        self.assertEqual(app.configured_hotspots(app.get_settings())[0]["url"], "http://ysf.test/api/")

    def test_one_offline_hotspot_does_not_stop_other_sources(self):
        first, second = self.sources()
        calls = []
        def poll(settings):
            calls.append(settings["hotspot_id"])
            if settings["hotspot_id"] == first["id"]:
                raise urllib.error.URLError("offline")
            app.SOURCE_STATUS[second["id"]] = dict(url=second["url"], last_ok="now", error="")
            app.STATUS["last_ok"] = "now"
        with patch.object(app, "poll_once", side_effect=poll), patch.object(app, "refresh_theme"), \
             patch.object(app.CONFIG_CHANGED, "wait", side_effect=StopIteration):
            with self.assertRaises(StopIteration):
                app.poll_loop()
        self.assertEqual(calls, [first["id"], second["id"]])
        self.assertIn("YSF desk", app.STATUS["error"])
        self.assertFalse(app.SOURCE_STATUS[second["id"]]["error"])

    def test_qrz_ambiguous_wire_responses_require_reconciliation(self):
        for body in ("<html>Server error</html>", "RESULT=OK&COUNT=0&LOGID=123",
                     "RESULT=OK&COUNT=1", "RESULT=OK&COUNT=1&LOGID=unknown",
                     "RESULT=REPLACE&COUNT=1&LOGID=123"):
            with self.subTest(body=body), patch.object(app.urllib.request, "urlopen", return_value=Response(body)):
                with self.assertRaises(app.QRZUncertainError):
                    app.qrz_insert("<EOR>", "TEST-KEY", "N0CALL")
        for body, expected in ((b"<html>Server error</html>", app.QRZUncertainError),
                               (b"RESULT=FAIL&COUNT=0&REASON=bad+key", ValueError)):
            error = urllib.error.HTTPError("https://logbook.qrz.com/api", 500, "Server error", {}, io.BytesIO(body))
            with patch.object(app.urllib.request, "urlopen", side_effect=error):
                with self.assertRaises(expected):
                    app.qrz_insert("<EOR>", "TEST-KEY", "N0CALL")

    def test_rejected_and_uncertain_qrz_records_are_excluded_from_export(self):
        source = app.configured_hotspots(self.settings)[0]
        host = self.server()
        for index, error in enumerate((ValueError("QRZ rejected the request"), app.QRZUncertainError("Check QRZ"))):
            transmission = self.transmission("W1ABC", seconds=30 + index, mode="DMR", target="91")
            self.poll(source, [transmission])
            identity = app.parse_row(transmission)[0]
            form = dict(csrf=app.form_token(self.settings), id=identity, call="W1ABC",
                        when=transmission["time_utc"][:19], freq="441.425", band="70cm", action="qrz")
            with patch.object(app, "qrz_insert", side_effect=error):
                with self.assertRaises(urllib.error.HTTPError) as rejected:
                    self.request(host, "/log", form)
                self.assertEqual(rejected.exception.code, 400)
            export, _ = self.request(host, "/export.adi")
            self.assertNotIn("<CALL:5>W1ABC", export)
            with app.db() as cx:
                row = cx.execute("SELECT * FROM heard WHERE id=?", (identity,)).fetchone()
            if isinstance(error, ValueError):
                self.assertIsNone(row["logged_at"])
                self.assertIsNone(row["log_adif"])
            else:
                self.assertEqual(row["log_status"], "pending")
                with patch.object(app, "qrz_insert") as upload:
                    with self.assertRaises(urllib.error.HTTPError):
                        self.request(host, "/log", form)
                    upload.assert_not_called()
                self.request(host, "/resolve", dict(csrf=app.form_token(self.settings), id=identity, resolution="found"))
                export, _ = self.request(host, "/export.adi")
                self.assertEqual(export.count("<CALL:5>W1ABC"), 1)

    def test_saved_rows_keep_reviewed_callsign_time_and_mode(self):
        source = app.configured_hotspots(self.settings)[0]
        transmission = self.transmission("W1ABC", seconds=30, mode="DMR", target="91")
        self.poll(source, [transmission])
        identity = app.parse_row(transmission)[0]
        when = dt.datetime.now(app.UTC).replace(microsecond=0).isoformat()[:19]
        host = self.server()
        self.request(host, "/log", dict(csrf=app.form_token(self.settings), id=identity, call="K9XYZ",
                     when=when, mode="P25", freq="441.425", band="70cm", action="save", comment="A radio contact"))
        self.poll(source, [transmission])
        with app.db() as cx:
            row = cx.execute("SELECT * FROM heard WHERE id=?", (identity,)).fetchone()
        self.assertEqual((row["call"], row["mode"], row["heard_utc"]), ("K9XYZ", "P25", when + "+00:00"))
        page, _ = self.request(host, "/?view=saved&mode=P25")
        self.assertIn("K9XYZ", page)
        self.assertNotIn("W1ABC", page)
        queue, _ = self.request(host, "/?view=queue")
        self.assertNotIn("K9XYZ", queue)
        export, _ = self.request(host, "/export.adi")
        self.assertIn("<CALL:5>K9XYZ", export)
        self.assertIn("P25 | A radio contact", export)

    def test_settings_validate_ports_and_preserve_password_spaces(self):
        for url in ("http://ysf.test:bad/api/", "http://ysf.test:0/api/", "http://ysf.test/api/#fragment", "http://ysf .test/api/"):
            with self.subTest(url=url), self.assertRaises(ValueError):
                app.save_configuration(dict(station_callsign="N0CALL", wpsd_url=url, rf_freq_mhz="441.425"))
        self.assertEqual(app.band_for("4.41425e2"), "")
        self.assertEqual(app.band_for("+441.425"), "")
        host = self.server()
        password = " pass word "
        # Redirects still carry the old browser credentials after a password change.
        with self.assertRaises(urllib.error.HTTPError) as old_login:
            self.request(host, "/settings", dict(csrf=app.form_token(self.settings), station_callsign="N0CALL",
                         wpsd_url="http://ysf.test/api/", rf_freq_mhz="441.425", password=password, password_confirm=password))
        self.assertEqual(old_login.exception.code, 401)
        self.assertTrue(app.password_matches(password, app.get_settings()["password_hash"]))
        self.assertFalse(app.password_matches(password.strip(), app.get_settings()["password_hash"]))
        auth = "Basic " + base64.b64encode(("N0CALL:" + password).encode()).decode()
        with urllib.request.urlopen(urllib.request.Request(host + "/", headers={"Authorization": auth})) as response:
            self.assertEqual(response.status, 200)
        malformed = "Basic " + base64.b64encode("é:testpass".encode()).decode()
        with self.assertRaises(urllib.error.HTTPError) as invalid:
            urllib.request.urlopen(urllib.request.Request(host + "/", headers={"Authorization": malformed}))
        self.assertEqual(invalid.exception.code, 401)


if __name__ == "__main__":
    unittest.main()

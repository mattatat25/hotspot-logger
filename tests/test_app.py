import datetime as dt
import json
import os
import tempfile
import unittest
import threading
import urllib.parse
import urllib.request
import urllib.error
import base64
import re
import sqlite3
from http.server import ThreadingHTTPServer
from unittest.mock import patch

import app


class LoggerTests(unittest.TestCase):
    def configure(self, qrz_key=""):
        return app.save_configuration({
            "station_callsign": "N0CALL",
            "wpsd_url": "http://localhost/api/",
            "rf_freq_mhz": "446.425",
            "wpsd_timezone": "UTC",
            "qrz_api_key": qrz_key,
            "poll_seconds": "10",
            "poll_limit": "40",
            "password": "testing-password-123456",
            "password_confirm": "testing-password-123456",
        }, initial=True)

    def test_parse_and_ignore_own_call(self):
        # Field names match WPSD's Last Heard implementation.
        row = {"mode": "DMR", "callsign": "W1ABC", "target": "91",
               "src": "Net", "duration": "22", "time_utc": "2026-09-25 01:43:00"}
        parsed = app.parse_row(row, "N0CALL")
        self.assertEqual((parsed[1], parsed[2], parsed[3]), ("W1ABC", "DMR", "91"))
        self.assertEqual(parsed[5], "2026-09-25T01:43:00+00:00")
        self.assertEqual(parsed[4], "Net")
        self.assertEqual(parsed[0], app.parse_row(row, "N0CALL")[0])
        row["Callsign"] = "N0CALL"
        self.assertIsNone(app.parse_row(row, "N0CALL"))

    def test_ysf_and_adif_lengths(self):
        parsed = app.parse_row({"mode": "YSF", "callsign": "K9XYZ", "timestamp": 1790300580,
                                "room": "America Link"})
        self.assertEqual(parsed[2:4], ("YSF", "America Link"))
        adif = app.make_adif("K9XYZ", "YSF", dt.datetime(2026, 9, 25, 1, 43, tzinfo=dt.timezone.utc),
                             "70cm", "446.425", "America Link", "Cafe", "N0CALL")
        self.assertIn("<MODE:12>DIGITALVOICE<SUBMODE:4>C4FM", adif)
        self.assertIn("<COMMENT:4>Cafe", adif)
        with self.assertRaisesRegex(ValueError, "ASCII"):
            app.adif_field("COMMENT", "Café")
        self.assertIn("<QSO_DATE:8>20260925<TIME_ON:6>014300", adif)

    def test_bad_schema_and_band(self):
        with self.assertRaises(ValueError):
            app.extract_rows({"unexpected": "object"})
        self.assertEqual(app.band_for("446.425"), "70cm")
        self.assertEqual(app.band_for("146.685"), "2m")
        self.assertEqual(app.band_for("91"), "")
        self.assertEqual(app.display_timestamp("2026-10-03T00:25:49+00:00", "America/Chicago", "local"),
                         ("19:25:49", "2026-10-02", "CDT"))
        self.assertEqual(app.display_timestamp("2026-10-03T00:25:49+00:00", "America/Chicago", "utc"),
                         ("00:25:49", "2026-10-03", "UTC"))

    def test_first_run_gui_setup_and_how_to(self):
        with tempfile.TemporaryDirectory() as folder:
            old_db = app.DB_PATH
            app.DB_PATH = os.path.join(folder, "logger.sqlite")
            try:
                app.init_db()
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                host = f"127.0.0.1:{server.server_port}"
                try:
                    with urllib.request.urlopen(f"http://{host}/") as response:
                        page = response.read().decode()
                    self.assertEqual(response.url, f"http://{host}/setup")
                    self.assertIn("Admin → Configuration", page)
                    self.assertIn("My Logbook → Settings → API", page)
                    self.assertIn("manual.wpsd.radio/advanced/api", page)
                    self.assertIn("Local time zone", page)
                    self.assertIn("<select required id='display-timezone'", page)
                    self.assertIn("value='America/Chicago'", page)
                    self.assertNotIn("timezone-list", page)
                    self.assertEqual(app.DEFAULTS["queue_retention_days"], "1")
                    token = re.search(r"name='csrf' value='([^']+)'", page).group(1)
                    form = {
                        "csrf": token, "station_callsign": "N0CALL",
                        "wpsd_url": "http://192.168.1.50/api/", "rf_freq_mhz": "446.425",
                        "wpsd_timezone": "UTC", "poll_seconds": "10", "poll_limit": "40",
                        "display_timezone": "America/Chicago", "display_time_mode": "local",
                        "qrz_api_key": "TEST-KEY", "password": "testing-password-123456",
                        "password_confirm": "testing-password-123456",
                    }
                    # Missing, forged and expired tokens still cannot save
                    # credentials, even without the optional origin headers.
                    for bad_token in ("", "forged", app.form_token(app.DEFAULTS)):
                        bad_form = dict(form, csrf=bad_token)
                        bad_request = urllib.request.Request(f"http://{host}/setup",
                            data=urllib.parse.urlencode(bad_form).encode(),
                            headers={"Host": "192.168.1.78:8787", "Origin": "null"})
                        with self.assertRaises(urllib.error.HTTPError) as rejected:
                            urllib.request.urlopen(bad_request)
                        self.assertEqual(rejected.exception.code, 403)
                        self.assertFalse(app.settings_ready())
                    # Some browsers suppress Origin and Referer on private-LAN
                    # HTTP pages. The per-process CSRF token must still allow
                    # the first-run form to be submitted.
                    request = urllib.request.Request(f"http://{host}/setup",
                        data=urllib.parse.urlencode(form).encode())
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code, 401)
                    settings = app.get_settings()
                    self.assertTrue(app.settings_ready(settings))
                    self.assertTrue(settings["password_hash"].startswith("pbkdf2_sha256$"))
                    self.assertNotIn("testing-password", settings["password_hash"])
                    auth = "Basic " + base64.b64encode(b"N0CALL:testing-password-123456").decode()
                    settings_request = urllib.request.Request(f"http://{host}/settings", headers={"Authorization": auth})
                    with urllib.request.urlopen(settings_request) as response:
                        settings_page = response.read().decode()
                    self.assertIn("Update the logger here", settings_page)
                    self.assertIn("<select required id='display-timezone'", settings_page)
                    self.assertIn("value='America/Chicago' selected", settings_page)
                    settings_token = re.search(r"name='csrf' value='([^']+)'", settings_page).group(1)
                    update = {
                        "csrf": settings_token, "station_callsign": "N0CALL",
                        "wpsd_url": "http://192.168.1.50/api/", "rf_freq_mhz": "446.450",
                        "wpsd_timezone": "UTC", "poll_seconds": "15", "poll_limit": "75",
                        "display_timezone": "America/Chicago", "display_time_mode": "local",
                        "qrz_api_key": "", "password": "", "password_confirm": "",
                    }
                    update_request = urllib.request.Request(f"http://{host}/settings",
                        data=urllib.parse.urlencode(update).encode(),
                        headers={"Authorization": auth, "Host": "192.168.1.78:8787", "Origin": "null"})
                    invalid_update = urllib.request.Request(f"http://{host}/settings",
                        data=urllib.parse.urlencode(dict(update, csrf="forged")).encode(),
                        headers={"Authorization": auth})
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        urllib.request.urlopen(invalid_update)
                    self.assertEqual(rejected.exception.code, 403)
                    self.assertEqual(app.get_settings()["rf_freq_mhz"], "446.425")
                    with urllib.request.urlopen(update_request) as response:
                        self.assertIn("Settings saved", response.read().decode())
                    updated = app.get_settings()
                    self.assertEqual(updated["rf_freq_mhz"], "446.450")
                    self.assertEqual(updated["qrz_api_key"], "TEST-KEY")
                    self.assertEqual(updated["display_timezone"], "America/Chicago")
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                app.DB_PATH = old_db

    def test_qrz_reply_validation(self):
        class FakeResponse:
            def __init__(self, body): self.body = body
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, length): return self.body
        with patch.object(app.urllib.request, "urlopen", return_value=FakeResponse(b"RESULT=OK&LOGID=123&COUNT=1")) as send:
            self.assertEqual(app.qrz_insert("<EOR>", "TEST-KEY", "N0CALL"), "123")
            request = send.call_args.args[0]
            self.assertEqual(request.full_url, "https://logbook.qrz.com/api")
            self.assertNotIn(b"OPTION=REPLACE", request.data)
        with patch.object(app.urllib.request, "urlopen", return_value=FakeResponse(b"RESULT=FAIL&REASON=bad+band")):
            with self.assertRaisesRegex(ValueError, "bad band"):
                app.qrz_insert("<EOR>", "TEST-KEY", "N0CALL")

    def test_delete_and_clear_preserve_qrz_and_stay_removed_on_poll(self):
        with tempfile.TemporaryDirectory() as folder:
            old_db = app.DB_PATH
            app.DB_PATH = os.path.join(folder, "logger.sqlite")
            server = None
            try:
                app.init_db()
                self.configure("TEST-KEY")
                settings = app.get_settings()
                base = dt.datetime(2026, 9, 25, 1, 43, tzinfo=dt.timezone.utc)
                feed = [{"callsign": "W1ABC", "mode": "DMR TS2", "target": "91", "src": "Net",
                         "time_utc": (base + dt.timedelta(seconds=i)).isoformat()} for i in range(103)]
                rows = [app.parse_row(row, "N0CALL") for row in feed]
                with app.db() as cx:
                    cx.executemany("INSERT INTO heard (id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES (?,?,?,?,?,?,?,?,?)", rows)
                    cx.execute("UPDATE heard SET logged_at=?,log_status='qrz',qrz_logid='123',log_adif='QRZ-SAVED-ADIF' WHERE id=?", (base.isoformat(), rows[-1][0]))
                    cx.execute("UPDATE heard SET logged_at=?,log_status='pending',log_adif='PENDING-ADIF' WHERE id=?", (base.isoformat(), rows[-2][0]))
                    cx.execute("UPDATE heard SET logged_at=?,log_status='save',log_adif='LOCAL-SAVED-ADIF' WHERE id=?", (base.isoformat(), rows[-3][0]))
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                threading.Thread(target=server.serve_forever, daemon=True).start()
                url = f"http://127.0.0.1:{server.server_port}"
                auth = "Basic " + base64.b64encode(b"N0CALL:testing-password-123456").decode()
                token = app.form_token(settings)

                def get(path):
                    request = urllib.request.Request(url + path, headers={"Authorization": auth})
                    with urllib.request.urlopen(request) as response:
                        return response.read().decode()

                def post(path, form, authenticated=True):
                    headers = {"Authorization": auth} if authenticated else {}
                    request = urllib.request.Request(url + path, data=urllib.parse.urlencode(form).encode(), headers=headers)
                    with urllib.request.urlopen(request) as response:
                        return response.read().decode()

                dashboard = get("/?view=queue")
                self.assertIn("Clear queue", dashboard)
                self.assertIn("Delete", dashboard)
                self.assertIn("Latest 50 entries in this view", dashboard)
                self.assertEqual(dashboard.count("data-label='Station'"), 50)
                self.assertIn("does not delete a contact from QRZ", get("/delete?id=" + rows[-1][0]))
                with app.db() as cx:
                    self.assertEqual(cx.execute("SELECT COUNT(*) FROM heard").fetchone()[0], 103)
                for path in ("/delete", "/clear"):
                    form = {"csrf": token, "id": rows[-1][0], "confirm": "yes"}
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        post(path, form, authenticated=False)
                    self.assertEqual(rejected.exception.code, 401)
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        post(path, dict(form, csrf="forged"))
                    self.assertEqual(rejected.exception.code, 403)
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        post(path, dict(form, confirm=""))
                    self.assertEqual(rejected.exception.code, 400)
                with patch.object(app, "qrz_insert") as qrz:
                    post("/delete", {"csrf": token, "id": rows[-1][0], "confirm": "yes"})
                    self.assertNotIn("QRZ-SAVED-ADIF", get("/export.adi"))
                    self.assertIn("LOCAL-SAVED-ADIF", get("/export.adi"))
                    self.assertIn("Clear 100 queued contacts", get("/clear"))
                    post("/clear", {"csrf": token, "confirm": "yes"})
                    qrz.assert_not_called()
                with app.db() as cx:
                    kept = cx.execute("SELECT log_status FROM heard").fetchall()
                    self.assertEqual({row[0] for row in kept}, {"pending", "save"})
                    self.assertEqual(len(kept), 2)

                # Poll the same feed after a simulated restart. Deleted rows
                # stay absent while a genuinely new contact enters the queue.
                app.init_db()
                feed.append(dict(feed[0], time_utc=(base + dt.timedelta(minutes=5)).isoformat()))
                class FeedResponse:
                    def __enter__(self): return self
                    def __exit__(self, *args): pass
                    def read(self, length): return json.dumps(feed).encode()
                with patch.object(app.urllib.request, "urlopen", return_value=FeedResponse()):
                    app.poll_once(settings)
                with app.db() as cx:
                    self.assertEqual(cx.execute("SELECT COUNT(*) FROM heard").fetchone()[0], 3)
                    self.assertIsNone(cx.execute("SELECT id FROM heard WHERE id=?", (rows[-1][0],)).fetchone())
                self.assertEqual(app.get_settings(), settings)
            finally:
                if server:
                    server.shutdown()
                    server.server_close()
                app.DB_PATH = old_db

    def test_wpsd_theme_reads_colors_caches_and_ignores_external_stylesheets(self):
        old_cache = dict(app.THEME_CACHES)
        settings = dict(app.DEFAULTS, wpsd_url="http://192.168.1.96/api/", station_callsign="N0CALL")
        css = """body {background: #222;} .container {background: #282828;}
        table td {color: #fff; border: .5px solid #444444;}
        table tr:nth-child(even) {background: #333333;}
        .navbar {background-color: #00ffff;} .navbar a {color: #000;} a {color: #00ffff;}"""
        page = '<link rel="stylesheet" href="https://external.example/theme.css"><link rel="stylesheet" href="/css/pistar-css.php?version=test">'
        fetched = []
        class ThemeResponse:
            def __init__(self, body): self.body = body.encode()
            def __enter__(self): return self
            def __exit__(self, *args): pass
            def read(self, length): return self.body[:length]
        def fetch(request, **kwargs):
            fetched.append(request.full_url)
            return ThemeResponse(css if "/css/" in request.full_url else page)
        try:
            app.THEME_CACHES.clear()
            with patch.object(app.urllib.request, "urlopen", side_effect=fetch):
                app.refresh_theme(settings)
                app.refresh_theme(settings)
            self.assertEqual(fetched, ["http://192.168.1.96/", "http://192.168.1.96/css/pistar-css.php?version=test"])
            self.assertEqual(app.THEME_CACHES[settings["wpsd_url"]]["colors"]["bg"], "#222222")
            self.assertIn("--accent:#00ffff", app.page_styles(settings))
            self.assertIn("Colors matched to WPSD", app.setup_page(settings))
            self.assertEqual(app.page_styles(dict(settings, theme_mode="logger")), app.CSS)
            # A different hotspot cannot inherit the old hotspot's palette.
            with patch.object(app.urllib.request, "urlopen", side_effect=urllib.error.URLError("offline")):
                changed = dict(settings, wpsd_url="http://192.168.1.97/api/")
                app.refresh_theme(changed)
            self.assertEqual(app.page_styles(changed), app.CSS)
            with self.assertRaises(ValueError):
                app.parse_theme_colors("body {background:url(https://bad.example);}")
            palette = app.parse_theme_colors(css + "a {color: url(https://bad.example);}")
            self.assertTrue(all(re.fullmatch(r"#[0-9a-f]{6}", value) for value in palette.values()))
        finally:
            app.THEME_CACHES.clear()
            app.THEME_CACHES.update(old_cache)

    def test_review_save_and_duplicate_guard(self):
        with tempfile.TemporaryDirectory() as folder:
            old_db = app.DB_PATH
            app.DB_PATH = os.path.join(folder, "logger.sqlite")
            try:
                app.init_db()
                self.configure()
                row = app.parse_row({"Mode": "DMR", "Callsign": "W1ABC", "Talk Group": "91",
                    "Heard-At": "2026-09-25T01:43:00Z"}, "N0CALL")
                with app.db() as cx:
                    cx.execute("INSERT INTO heard (id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES (?,?,?,?,?,?,?,?,?)", row)
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                host = f"127.0.0.1:{server.server_port}"
                auth = "Basic " + base64.b64encode(b"N0CALL:testing-password-123456").decode()
                try:
                    health = urllib.request.urlopen(f"http://{host}/healthz")
                    self.assertEqual(json.loads(health.read())["version"], app.VERSION)
                    get = urllib.request.Request(f"http://{host}/?view=queue", headers={"Authorization": auth})
                    with urllib.request.urlopen(get) as response:
                        page = response.read().decode()
                    self.assertIn("W1ABC", page)
                    review = urllib.request.Request(f"http://{host}/review?id={row[0]}", headers={"Authorization": auth})
                    with urllib.request.urlopen(review) as response:
                        page = response.read().decode()
                    token = re.search(r"name='csrf' value='([^']+)'", page).group(1)
                    form = {"csrf": token, "id": row[0], "call": "W1ABC", "when": "2026-09-25T01:43:00",
                            "freq": "446.425", "band": "70cm", "action": "save", "comment": "DMR TG 91"}
                    request = urllib.request.Request(f"http://{host}/log", data=urllib.parse.urlencode(form).encode(),
                        headers={"Authorization": auth})
                    invalid_log = urllib.request.Request(f"http://{host}/log",
                        data=urllib.parse.urlencode(dict(form, csrf="forged")).encode(),
                        headers={"Authorization": auth})
                    with self.assertRaises(urllib.error.HTTPError) as rejected:
                        urllib.request.urlopen(invalid_log)
                    self.assertEqual(rejected.exception.code, 403)
                    with app.db() as cx:
                        self.assertIsNone(cx.execute("SELECT logged_at FROM heard WHERE id=?", (row[0],)).fetchone()[0])
                    with urllib.request.urlopen(request) as response:
                        self.assertIn("Possible exchanges", response.read().decode())
                    saved = urllib.request.Request(f"http://{host}/?view=saved", headers={"Authorization": auth})
                    with urllib.request.urlopen(saved) as response:
                        self.assertIn("Saved for ADIF", response.read().decode())
                    with app.db() as cx:
                        stored = cx.execute("SELECT log_status,log_adif FROM heard WHERE id=?", (row[0],)).fetchone()
                        self.assertEqual(stored[0], "save")
                        self.assertIn("<SUBMODE:3>DMR", stored[1])
                    with self.assertRaises(urllib.error.HTTPError) as error:
                        urllib.request.urlopen(request)
                    self.assertEqual(error.exception.code, 400)
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                app.DB_PATH = old_db

    def test_qrz_timeout_requires_reconciliation(self):
        with tempfile.TemporaryDirectory() as folder:
            old_db = app.DB_PATH
            app.DB_PATH = os.path.join(folder, "logger.sqlite")
            try:
                app.init_db()
                self.configure("TEST-KEY")
                row = app.parse_row({"mode": "YSF", "callsign": "K9XYZ", "target": "America Link",
                                     "time_utc": "2026-09-25 01:43:00"}, "N0CALL")
                with app.db() as cx:
                    cx.execute("INSERT INTO heard (id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES (?,?,?,?,?,?,?,?,?)", row)
                server = ThreadingHTTPServer(("127.0.0.1", 0), app.Handler)
                thread = threading.Thread(target=server.serve_forever, daemon=True)
                thread.start()
                host = f"127.0.0.1:{server.server_port}"
                auth = "Basic " + base64.b64encode(b"N0CALL:testing-password-123456").decode()
                token = app.form_token(app.get_settings())
                form = {"csrf": token, "id": row[0], "call": "K9XYZ", "when": "2026-09-25T01:43:00",
                        "freq": "446.425", "band": "70cm", "action": "qrz", "comment": "YSF America Link"}
                request = urllib.request.Request(f"http://{host}/log", data=urllib.parse.urlencode(form).encode(),
                    headers={"Authorization": auth, "Origin": "null"})
                try:
                    with patch.object(app, "qrz_insert", side_effect=urllib.error.URLError("timeout")):
                        with self.assertRaises(urllib.error.HTTPError) as error:
                            urllib.request.urlopen(request)
                        self.assertEqual(error.exception.code, 400)
                    with app.db() as cx:
                        pending = cx.execute("SELECT log_status,log_adif FROM heard WHERE id=?", (row[0],)).fetchone()
                        self.assertEqual(pending[0], "pending")
                        self.assertIn("<SUBMODE:4>C4FM", pending[1])
                    resolve = urllib.request.Request(f"http://{host}/resolve", data=urllib.parse.urlencode({
                        "csrf": token, "id": row[0], "resolution": "retry"}).encode(),
                        headers={"Authorization": auth})
                    with urllib.request.urlopen(resolve):
                        pass
                    with app.db() as cx:
                        reopened = cx.execute("SELECT log_status,logged_at FROM heard WHERE id=?", (row[0],)).fetchone()
                        self.assertEqual(tuple(reopened), (None, None))
                finally:
                    server.shutdown()
                    server.server_close()
            finally:
                app.DB_PATH = old_db


if __name__ == "__main__":
    unittest.main()

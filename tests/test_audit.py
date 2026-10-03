import base64
from concurrent.futures import ThreadPoolExecutor
import datetime as dt
import hashlib
import io
import http.client
import json
import os
from pathlib import Path
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
import maintenance


class Response:
    def __init__(self, content):
        self.content = content.encode()
    def __enter__(self): return self
    def __exit__(self, *args): pass
    def read(self, limit): return self.content[:limit]


class AuditTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        old = app.DB_PATH
        app.DB_PATH = os.path.join(self.folder.name, 'logger.sqlite')
        self.addCleanup(setattr, app, 'DB_PATH', old)
        app.init_db()
        self.form = dict(station_callsign='N0CALL', wpsd_url='http://hotspot.test/api/',
                         rf_freq_mhz='441.425', password='testpass', password_confirm='testpass')
        self.log_patch = patch.object(app.Handler, 'log_message', return_value=None)
        self.log_patch.start()
        self.addCleanup(self.log_patch.stop)

    def server(self):
        server = ThreadingHTTPServer(('127.0.0.1', 0), app.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        return f'http://127.0.0.1:{server.server_port}'

    def request(self, host, path, form=None):
        headers = {'Authorization': 'Basic ' + base64.b64encode(b'N0CALL:testpass').decode()}
        req = urllib.request.Request(host + path, headers=headers,
                data=None if form is None else urllib.parse.urlencode(form).encode())
        return urllib.request.urlopen(req)

    def test_simultaneous_initial_setup_has_one_winner(self):
        rendezvous = threading.Barrier(2)
        original = app.hash_password
        def delayed(password):
            rendezvous.wait(timeout=5)
            return original(password)
        def save(call):
            try:
                app.save_configuration(dict(self.form, station_callsign=call), initial=True)
                return call
            except ValueError:
                return None
        with patch.object(app, 'hash_password', side_effect=delayed), ThreadPoolExecutor(2) as pool:
            results = list(pool.map(save, ['N0CALL', 'W1ABC']))
        winners = [call for call in results if call]
        self.assertEqual(len(winners), 1)
        self.assertEqual(app.get_settings()['station_callsign'], winners[0])

    def test_database_permissions_protect_credentials_and_existing_files(self):
        app.save_configuration(self.form, initial=True)
        self.assertEqual(Path(app.DB_PATH).stat().st_mode & 0o777, 0o600)
        with app.db() as connection:
            connection.execute('SELECT * FROM settings').fetchall()
            for suffix in ('-wal', '-shm'):
                p = Path(app.DB_PATH + suffix)
                if p.exists():
                    self.assertEqual(p.stat().st_mode & 0o777, 0o600)
        os.chmod(app.DB_PATH, 0o644)
        app.init_db()
        self.assertEqual(Path(app.DB_PATH).stat().st_mode & 0o777, 0o600)
        self.assertTrue(app.settings_ready())

    def test_qrz_auth_is_definite_rejection_for_success_and_error_http_status(self):
        for as_http_error in (False, True):
            body = 'RESULT=AUTH&COUNT=0'
            args = ({'side_effect': urllib.error.HTTPError('https://logbook.qrz.com/api', 403,
                         'Forbidden', {}, io.BytesIO(body.encode()))} if as_http_error else
                    {'return_value': Response(body)})
            with patch.object(app.urllib.request, 'urlopen', **args):
                with self.assertRaisesRegex(ValueError, 'QRZ rejected'):
                    app.qrz_insert('<EOR>', 'TEST-KEY', 'N0CALL')

    def test_oversized_and_conflicting_qrz_replies_stay_uncertain(self):
        for body in ('RESULT=FAIL&REASON=' + 'x' * 5000,
                     'RESULT=FAIL&RESULT=OK&COUNT=1&LOGID=123',
                     'RESULT=OK&RESULT=FAIL&COUNT=1&LOGID=123'):
            for as_http_error in (False, True):
                args = ({'side_effect': urllib.error.HTTPError('https://logbook.qrz.com/api', 500,
                             'Error', {}, io.BytesIO(body.encode()))} if as_http_error else
                        {'return_value': Response(body)})
                with patch.object(app.urllib.request, 'urlopen', **args):
                    with self.assertRaises(app.QRZUncertainError):
                        app.qrz_insert('<EOR>', 'TEST-KEY', 'N0CALL')

    def test_broken_http_error_body_stays_uncertain(self):
        error = urllib.error.HTTPError('https://logbook.qrz.com/api', 500, 'Error', {}, io.BytesIO())
        with patch.object(error, 'read', side_effect=http.client.IncompleteRead(b'RESULT=')), \
                patch.object(app.urllib.request, 'urlopen', side_effect=error):
            with self.assertRaises(app.QRZUncertainError):
                app.qrz_insert('<EOR>', 'TEST-KEY', 'N0CALL')

    def test_invalid_timestamp_does_not_discard_valid_poll_rows(self):
        settings = app.save_configuration(self.form, initial=True)
        row = dict(callsign='W1ABC', mode='DMR', src='Net', target='91', duration='8',
                   time_utc=dt.datetime.now(app.UTC).isoformat())
        bad = dict(row, callsign='K9XYZ', time_utc='9999-12-31T23:59:59-23:59')
        edge = dict(row, callsign='K1ABC', time_utc='9999-12-31T23:59:59+00:00')
        with patch.object(app.urllib.request, 'urlopen', return_value=Response(json.dumps([bad, edge, row]))):
            self.assertEqual(app.poll_once(settings), 1)
        with app.db() as cx:
            self.assertEqual(cx.execute('SELECT call FROM heard').fetchall()[0][0], 'W1ABC')
        self.assertIsNone(app.timestamp(float('inf')))

    def test_unicode_csrf_is_rejected_before_and_after_setup(self):
        host = self.server()
        for path in ('/setup', '/settings'):
            with self.assertRaises(urllib.error.HTTPError) as error:
                self.request(host, path, dict(self.form, csrf='é'))
            self.assertEqual(error.exception.code, 403)
            if path == '/setup':
                app.save_configuration(self.form, initial=True)

    def test_brand_asset_beta_and_csp_work_on_setup_and_authenticated_pages(self):
        host = self.server()
        with self.request(host, '/setup') as response:
            page = response.read().decode()
            self.assertIn('Hotspot Logger', page)
            self.assertIn("class='beta'>Beta", page)
            self.assertIn('KF0WSS', page)
            self.assertIn("href='https://www.qrz.com/db/KF0WSS'", page)
            self.assertIn("class='brand-home' href='/'", page)
            self.assertIn("img-src 'self'", response.headers['Content-Security-Policy'])
        with self.request(host, '/assets/hotspot-logger.png') as response:
            self.assertEqual(response.headers['Content-Type'], 'image/png')
            self.assertTrue(response.read().startswith(b'\x89PNG\r\n\x1a\n'))
        app.save_configuration(self.form, initial=True)
        for path in ('/', '/settings', '/clear'):
            with self.request(host, path) as response:
                page = response.read().decode()
                self.assertIn("class='beta'>Beta", page)
                if path in ('/', '/settings'):
                    self.assertIn("class='brand-home' href='/'", page)
                if path == '/':
                    policy = response.headers['Content-Security-Policy']
                    self.assertIn("connect-src 'self'", policy)
                    self.assertIn("data-refresh-ms='5000'", page)
                    self.assertIn('refreshDashboard', page)
                    script = re.search(r"<script>(.*?)</script>", page, re.S).group(1)
                    digest = base64.b64encode(hashlib.sha256(script.encode()).digest()).decode()
                    self.assertIn("'sha256-" + digest + "'", policy)
        with self.assertRaises(urllib.error.HTTPError) as denied:
            self.request(host, '/assets/../app.py')
        self.assertEqual(denied.exception.code, 404)

    def test_offset_contact_time_is_converted_to_utc(self):
        settings = app.save_configuration(self.form, initial=True)
        now = dt.datetime.now(app.UTC).replace(microsecond=0)
        row = app.parse_row(dict(callsign='W1ABC', mode='DMR', target='91', src='Net',
                                time_utc=now.isoformat(), duration='8'))
        with app.db() as cx:
            cx.execute('INSERT INTO heard(id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES(?,?,?,?,?,?,?,?,?)', row)
        form = dict(csrf=app.form_token(settings), id=row[0], call='W1ABC', mode='DMR',
                    when=now.astimezone(dt.timezone(dt.timedelta(hours=-5))).isoformat(),
                    freq='441.425', band='70cm', action='save')
        with self.request(self.server(), '/log', form): pass
        with app.db() as cx:
            saved = cx.execute('SELECT heard_utc,log_adif FROM heard').fetchone()
        self.assertEqual(saved[0], now.isoformat())
        self.assertIn(now.strftime('%H%M%S'), saved[1])

    def test_restore_rejects_matching_table_names_with_incomplete_schema(self):
        other = Path(self.folder.name) / 'incomplete.sqlite'
        with sqlite3.connect(other) as cx:
            cx.executescript('CREATE TABLE settings(key TEXT,value TEXT); CREATE TABLE heard(id TEXT);')
        with self.assertRaisesRegex(ValueError, 'missing required heard columns'):
            maintenance.check_database(other)
        self.assertTrue(Path(app.DB_PATH).exists())


if __name__ == '__main__':
    unittest.main()

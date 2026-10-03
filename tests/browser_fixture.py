"""Disposable browser-test server. It never polls WPSD or calls QRZ."""
import datetime as dt
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import urllib.parse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app


class FixtureHandler(app.Handler):
    def do_GET(self):
        if urllib.parse.urlsplit(self.path).path == '/__test/add-live-contact':
            settings = app.get_settings()
            source = app.configured_hotspots(settings)[0]
            entry = app.parse_row(dict(callsign='W9LIVE', mode='YSF', target='DG-ID 0 at W9LIVE', src='Net',
                                       time_utc=dt.datetime.now(app.UTC).isoformat(), duration='12'))
            with app.db() as cx:
                cx.execute('''INSERT OR REPLACE INTO heard
                    (id,call,mode,target,direction,heard_utc,duration,raw,first_seen,hotspot_id,hotspot_label,ysf_room)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)''', (*entry, source['id'], source['label'], 'US-KCWide'))
            return self.send_page(204, b'', 'text/plain')
        return super().do_GET()

with tempfile.TemporaryDirectory() as folder:
    app.DB_PATH = str(Path(folder) / 'logger.sqlite')
    app.init_db()
    now = dt.datetime.now(app.UTC)
    with app.db() as cx:
        for index, mode in enumerate(app.MODE_SPECS):
            entry = app.parse_row(dict(callsign=f'W{index + 1}ABC', mode=mode, target='91', src='Net',
                                      time_utc=(now - dt.timedelta(minutes=index)).isoformat(), duration='12'))
            cx.execute('INSERT INTO heard(id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES(?,?,?,?,?,?,?,?,?)', entry)
    FixtureHandler.log_message = lambda *args: None
    ThreadingHTTPServer(('127.0.0.1', 8788), FixtureHandler).serve_forever()

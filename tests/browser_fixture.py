"""Disposable browser-test server. It never polls WPSD or calls QRZ."""
import datetime as dt
from http.server import ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import app

with tempfile.TemporaryDirectory() as folder:
    app.DB_PATH = str(Path(folder) / 'logger.sqlite')
    app.init_db()
    now = dt.datetime.now(app.UTC)
    with app.db() as cx:
        for index, mode in enumerate(app.MODE_SPECS):
            entry = app.parse_row(dict(callsign=f'W{index + 1}ABC', mode=mode, target='91', src='Net',
                                      time_utc=(now - dt.timedelta(minutes=index)).isoformat(), duration='12'))
            cx.execute('INSERT INTO heard(id,call,mode,target,direction,heard_utc,duration,raw,first_seen) VALUES(?,?,?,?,?,?,?,?,?)', entry)
    app.Handler.log_message = lambda *args: None
    ThreadingHTTPServer(('127.0.0.1', 8788), app.Handler).serve_forever()

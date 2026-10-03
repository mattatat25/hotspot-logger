"""Run against the temporary Compose instance created by GitHub Actions."""
import base64
import json
from pathlib import Path
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request


BASE = "http://127.0.0.1:8787"
AUTH = "Basic " + base64.b64encode(b"N0CALL:smokepass").decode()


def request(path, form=None):
    data = None if form is None else urllib.parse.urlencode(form).encode()
    req = urllib.request.Request(BASE + path, data=data, headers={"Authorization": AUTH})
    with urllib.request.urlopen(req, timeout=5) as response:
        return response.read().decode()


def wait_for_server():
    for attempt in range(30):
        try:
            return json.loads(request("/healthz"))
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise RuntimeError("Container did not start within 30 seconds")


def docker_python(code):
    return subprocess.run(["docker", "compose", "exec", "-T", "logger", "python", "-c", code],
                          check=True, capture_output=True, text=True).stdout.strip()


def main():
    assert wait_for_server()["configured"] is False
    setup = request("/setup")
    assert "class='beta'>Beta" in setup
    with urllib.request.urlopen(BASE + '/assets/hotspot-logger.png', timeout=5) as response:
        assert response.headers['Content-Type'] == 'image/png'
        assert response.read() == Path('assets/hotspot-logger.png').read_bytes()
    token = re.search(r"name='csrf' value='([^']+)'", setup).group(1)
    form = dict(csrf=token, hotspots_form="yes", hotspot_id_0="primary", hotspot_label_0="Test hotspot",
                hotspot_url_0="http://127.0.0.1:9/api/", hotspot_freq_0="441.425", station_callsign="N0CALL",
                password="smokepass", password_confirm="smokepass", qrz_api_key="TEST-KEY", theme_mode="logger")
    assert "Hotspot Logger" in request("/setup", form)
    assert wait_for_server()["configured"] is True
    assert "Created by" in request("/")
    assert "KF0WSS" in request("/")
    assert docker_python("import os; print(oct(os.stat('/data/logger.sqlite').st_mode & 0o777))") == '0o600'
    docker_python("""import sqlite3
with sqlite3.connect('/data/logger.sqlite') as cx:
    cx.execute(\"INSERT INTO heard(id,call,mode,target,direction,heard_utc,duration,raw,first_seen,logged_at,log_status,log_adif) VALUES('smoke','W1ABC','DMR','91','Net','2026-10-01T00:00:00+00:00','8','{}','2026-10-01','2026-10-01','save','<CALL:5>W1ABC<EOR>')\")
    cx.execute(\"INSERT INTO removed VALUES('removed-before-backup')\")
""")
    assert docker_python("from zoneinfo import ZoneInfo; print(ZoneInfo('America/Chicago'))") == 'America/Chicago'
    settings = request("/settings")
    token = re.search(r"name='csrf' value='([^']+)'", settings).group(1)
    result = subprocess.run(["bash", "scripts/backup.sh"], check=True, capture_output=True, text=True)
    archive = Path(re.search(r"^Created (.+)$", result.stdout, re.M).group(1))
    assert archive.stat().st_mode & 0o777 == 0o600
    update = dict(form, csrf=token, hotspot_label_0="Changed hotspot", qrz_api_key="CHANGED-TEST-KEY", password="", password_confirm="")
    request("/settings", update)
    request("/delete", dict(csrf=token, id="smoke", confirm="yes"))
    assert "<CALL:5>W1ABC" not in request("/export.adi")
    subprocess.run(["bash", "scripts/restore.sh", str(archive)], check=True)
    assert wait_for_server()["configured"] is True
    assert "Test hotspot" in request("/settings")
    assert "Changed hotspot" not in request("/settings")
    assert "<CALL:5>W1ABC" in request("/export.adi")
    assert docker_python("""import sqlite3
with sqlite3.connect('/data/logger.sqlite') as cx:
    assert cx.execute("SELECT value FROM settings WHERE key='qrz_api_key'").fetchone()[0] == 'TEST-KEY'
    assert cx.execute("SELECT COUNT(*) FROM removed WHERE id='removed-before-backup'").fetchone()[0] == 1
print('restored')
""") == "restored"
    with tempfile.TemporaryDirectory() as folder:
        invalid = Path(folder) / "invalid.tar.gz"
        invalid.write_bytes(b"not a backup")
        failure = subprocess.run(["bash", "scripts/restore.sh", str(invalid)], capture_output=True)
        assert failure.returncode != 0
        assert wait_for_server()["configured"] is True
        assert "<CALL:5>W1ABC" in request("/export.adi")
    print("Container GUI setup, authentication, backup, restore, and invalid-archive checks passed.")


if __name__ == "__main__":
    main()

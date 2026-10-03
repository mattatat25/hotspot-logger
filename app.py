"""WPSD Last Heard companion. Python standard library only; no WPSD modifications."""
import base64
import datetime as dt
import hashlib
import hmac
import html
import http.client
import json
import os
import re
import secrets
import sqlite3
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from html.parser import HTMLParser
from pathlib import Path
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError, available_timezones

VERSION = "0.8.0-beta.7"
ACTIVITY_LIMIT = 50
MAX_UNLOGGED_PER_HOTSPOT = 2500
MAX_ACTIVITY_PER_HOTSPOT = 5000
UTC = dt.timezone.utc
CALL = re.compile(r"^[A-Z0-9]{1,4}[0-9][A-Z0-9]{1,5}(?:/[A-Z0-9]{1,8})?$")
DB_PATH = os.getenv("DB_PATH", "/data/logger.sqlite")
PORT = int(os.getenv("PORT", "8787"))
STATUS = {"last_ok": None, "error": "Setup required"}
WRITE_LOCK = threading.Lock()
CONFIG_CHANGED = threading.Event()
BOOTSTRAP_SECRET = secrets.token_urlsafe(32)
THEME_CACHES = {}
SOURCE_STATUS = {}
EXCHANGE_REBUILDS = {}
MODE_SPECS = {
    "YSF": ("DIGITALVOICE", "C4FM"), "DMR": ("DIGITALVOICE", "DMR"),
    "D-Star": ("DIGITALVOICE", "DSTAR"), "P25": ("DIGITALVOICE", ""),
    "NXDN": ("DIGITALVOICE", ""), "M17": ("DIGITALVOICE", "M17"),
    "FM": ("FM", ""),
}
DEFAULTS = {
    "station_callsign": "",
    "wpsd_url": "http://wpsd.local/api/",
    "rf_freq_mhz": "",
    "wpsd_timezone": "UTC",
    "display_timezone": "UTC",
    "display_time_mode": "local",
    "qrz_api_key": "",
    "poll_seconds": "10",
    "poll_limit": "40",
    "queue_retention_days": "1",
    "theme_mode": "wpsd",
    "hotspots": "[]",
    "password_hash": "",
    "csrf_secret": "",
}
CREATOR_CREDIT = ("<span class='creator-credit'>Created by "
                  "<a href='https://www.qrz.com/db/KF0WSS' target='_blank' rel='noopener noreferrer'><strong>KF0WSS</strong></a></span>")


def page_footer(note=""):
    return (f"<footer><span>{html.escape(note)}</span>{CREATOR_CREDIT}"
            f"<span>Hotspot Logger {VERSION} <strong class='beta'>Beta</strong></span>"
            "<span class='independence'>Independent project; not affiliated with or endorsed by WPSD or QRZ.</span></footer>")


BRAND = "<img class='brand-logo' src='/assets/hotspot-logger.png' alt='Hotspot Logger — Created by KF0WSS' width='2172' height='724'>"


def db():
    connection = sqlite3.connect(DB_PATH, timeout=15)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA busy_timeout=15000")
    return connection


def init_db():
    os.makedirs(os.path.dirname(os.path.abspath(DB_PATH)), exist_ok=True)
    # Create privately before SQLite writes credentials or WAL sidecars.
    descriptor = os.open(DB_PATH, os.O_CREAT | os.O_WRONLY, 0o600)
    os.close(descriptor)
    for path in (DB_PATH, DB_PATH + "-wal", DB_PATH + "-shm"):
        if os.path.exists(path):
            os.chmod(path, 0o600)
    with db() as cx:
        cx.execute("PRAGMA journal_mode=WAL")
        cx.execute("""CREATE TABLE IF NOT EXISTS heard (
            id TEXT PRIMARY KEY, call TEXT NOT NULL, mode TEXT NOT NULL,
            target TEXT NOT NULL, direction TEXT NOT NULL, heard_utc TEXT NOT NULL,
            duration TEXT NOT NULL, raw TEXT NOT NULL, first_seen TEXT NOT NULL,
            logged_at TEXT, qrz_logid TEXT, log_adif TEXT, log_status TEXT)""")
        cx.execute("CREATE INDEX IF NOT EXISTS heard_time ON heard(heard_utc DESC)")
        cx.execute("CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL)")
        cx.execute("CREATE TABLE IF NOT EXISTS removed (id TEXT PRIMARY KEY)")
        columns = {row["name"] for row in cx.execute("PRAGMA table_info(heard)")}
        for name, default in (("hotspot_id", "primary"), ("hotspot_label", "Hotspot 1"),
                              ("ysf_room", ""), ("exchange_pattern", "")):
            if name not in columns:
                cx.execute(f"ALTER TABLE heard ADD COLUMN {name} TEXT NOT NULL DEFAULT '{default}'")
        cx.execute("CREATE INDEX IF NOT EXISTS heard_hotspot_first_seen ON heard(hotspot_id,first_seen DESC)")
        cx.execute("""CREATE TABLE IF NOT EXISTS activity (
            id TEXT PRIMARY KEY, hotspot_id TEXT NOT NULL, source_url TEXT NOT NULL,
            call TEXT NOT NULL, channel TEXT NOT NULL, direction TEXT NOT NULL,
            heard_utc TEXT NOT NULL, duration TEXT NOT NULL)""")
        cx.execute("CREATE INDEX IF NOT EXISTS activity_source_time ON activity(hotspot_id,source_url,heard_utc)")


def get_settings():
    settings = dict(DEFAULTS)
    try:
        with db() as cx:
            settings.update({row["key"]: row["value"] for row in cx.execute("SELECT key,value FROM settings")})
    except sqlite3.OperationalError:
        pass
    return settings


def settings_ready(settings=None):
    settings = settings or get_settings()
    return bool(CALL.fullmatch(settings["station_callsign"]) and settings["wpsd_url"]
                and settings["password_hash"] and settings["csrf_secret"])


def configured_hotspots(settings):
    hotspots = json.loads(settings.get("hotspots", "[]"))
    return hotspots or [{"id": "primary", "label": "Hotspot 1",
                         "url": settings["wpsd_url"], "freq": settings["rf_freq_mhz"]}]


def hotspot_form_values(form, current):
    if form.get("hotspots_form") != "yes":
        hotspots = configured_hotspots(current)
        hotspots[0] = dict(hotspots[0], url=form.get("wpsd_url", "").strip(),
                           freq=form.get("rf_freq_mhz", "").strip())
        return hotspots
    indices = sorted(int(key.rsplit("_", 1)[1]) for key in form
                     if re.fullmatch(r"hotspot_url_\d+", key))
    if not 1 <= len(indices) <= 16:
        raise ValueError("Add between one and sixteen hotspots")
    known = {item["id"] for item in configured_hotspots(current)}
    hotspots = []
    for index in indices:
        identity = form.get(f"hotspot_id_{index}", "")
        if identity not in known:
            identity = secrets.token_hex(8)
        hotspots.append({"id": identity, "label": form.get(f"hotspot_label_{index}", "").strip(),
                         "url": form.get(f"hotspot_url_{index}", "").strip(),
                         "freq": form.get(f"hotspot_freq_{index}", "").strip()})
    return hotspots


def source_settings(settings, hotspot):
    return dict(settings, wpsd_url=hotspot["url"], rf_freq_mhz=hotspot["freq"],
                hotspot_id=hotspot["id"], hotspot_label=hotspot["label"])


def hash_password(password, salt=None, rounds=300_000):
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, rounds)
    return f"pbkdf2_sha256${rounds}${salt.hex()}${digest.hex()}"


def password_matches(password, encoded):
    try:
        algorithm, rounds, salt, expected = encoded.split("$", 3)
        if algorithm != "pbkdf2_sha256":
            return False
        actual = hashlib.pbkdf2_hmac("sha256", password.encode(), bytes.fromhex(salt), int(rounds)).hex()
        return hmac.compare_digest(actual, expected)
    except (ValueError, TypeError):
        return False


def form_token(settings=None, bootstrap=False):
    secret = BOOTSTRAP_SECRET if bootstrap else (settings or get_settings())["csrf_secret"]
    return hmac.new(secret.encode(), b"form", hashlib.sha256).hexdigest()


def save_configuration(form, initial=False):
    current = get_settings()
    station = form.get("station_callsign", "").upper().strip()
    if not CALL.fullmatch(station):
        raise ValueError("Enter a valid station callsign")

    hotspots = hotspot_form_values(form, current)
    urls, identities = set(), set()
    for hotspot in hotspots:
        parts = urllib.parse.urlsplit(hotspot["url"])
        try:
            port = parts.port
        except ValueError:
            raise ValueError("Check the port in the WPSD API URL") from None
        if (parts.scheme not in ("http", "https") or not parts.hostname or parts.username
                or parts.password or parts.fragment or port == 0 or any(char.isspace() for char in hotspot["url"])):
            raise ValueError("Enter a valid HTTP(S) WPSD API URL for each hotspot")
        if not band_for(hotspot["freq"]):
            raise ValueError("Enter a radio transmit frequency in a supported amateur band for each hotspot")
        if not hotspot["label"] or len(hotspot["label"]) > 40:
            raise ValueError("Give each hotspot a name of up to 40 characters")
        if hotspot["url"].rstrip("/") in urls or hotspot["id"] in identities:
            raise ValueError("Each hotspot must have a different WPSD address")
        urls.add(hotspot["url"].rstrip("/"))
        identities.add(hotspot["id"])
    wpsd_url, frequency = hotspots[0]["url"], hotspots[0]["freq"]

    timezone = form.get("wpsd_timezone", current["wpsd_timezone"]).strip()
    try:
        ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Enter an IANA time zone such as UTC or America/Chicago") from None

    display_timezone = form.get("display_timezone", current["display_timezone"]).strip()
    try:
        ZoneInfo(display_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        raise ValueError("Enter a valid local time zone such as America/Chicago") from None
    display_time_mode = form.get("display_time_mode", current["display_time_mode"])
    if display_time_mode not in ("local", "utc"):
        raise ValueError("Choose Local or UTC as the default clock")

    try:
        poll_seconds = int(form.get("poll_seconds", "10"))
        poll_limit = int(form.get("poll_limit", "40"))
        queue_retention_days = int(form.get("queue_retention_days", current["queue_retention_days"]))
    except ValueError:
        raise ValueError("Polling values must be numbers") from None
    if not 5 <= poll_seconds <= 300 or not 10 <= poll_limit <= 200:
        raise ValueError("Choose a poll interval from 5–300 seconds and a row limit from 10–200")
    if queue_retention_days not in (1, 3, 7, 14, 30):
        raise ValueError("Choose a queue retention period from the list")
    theme_mode = form.get("theme_mode", current["theme_mode"])
    if theme_mode not in ("wpsd", "logger"):
        raise ValueError("Choose Match WPSD or Logger default for the theme")

    qrz_key = form.get("qrz_api_key", "").strip()
    if initial:
        selected_qrz_key = qrz_key
    elif form.get("remove_qrz_key") == "yes":
        selected_qrz_key = ""
    else:
        selected_qrz_key = qrz_key or current["qrz_api_key"]
    if len(selected_qrz_key) > 300 or any(char.isspace() for char in selected_qrz_key):
        raise ValueError("The QRZ API key cannot contain spaces")

    password = form.get("password", "")
    confirmation = form.get("password_confirm", "")
    if password or initial:
        if len(password) < 8:
            raise ValueError("Choose a password with at least 8 characters")
        if password != confirmation:
            raise ValueError("The passwords do not match")
        encoded_password = hash_password(password)
    else:
        encoded_password = current["password_hash"]

    values = {
        "station_callsign": station,
        "wpsd_url": wpsd_url,
        "rf_freq_mhz": frequency,
        "wpsd_timezone": timezone,
        "display_timezone": display_timezone,
        "display_time_mode": display_time_mode,
        "qrz_api_key": selected_qrz_key,
        "poll_seconds": str(poll_seconds),
        "poll_limit": str(poll_limit),
        "queue_retention_days": str(queue_retention_days),
        "theme_mode": theme_mode,
        "hotspots": json.dumps(hotspots),
        "password_hash": encoded_password,
        "csrf_secret": current["csrf_secret"] or secrets.token_urlsafe(32),
    }
    with WRITE_LOCK, db() as cx:
        if initial and cx.execute("SELECT 1 FROM settings WHERE key='password_hash' AND value!=''").fetchone():
            raise ValueError("Setup is already complete. Sign in to change settings.")
        cx.executemany("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", values.items())
    STATUS.update({"last_ok": None, "error": "Settings saved; waiting for WPSD"})
    CONFIG_CHANGED.set()
    for cache in tuple(THEME_CACHES.values()):
        cache["checked"] = 0
    return values


def value(row, *keys):
    # WPSD manual does not specify its JSON schema. Normalize labels without
    # collapsing similarly named fields such as CALL and CALLSIGN in output.
    norm = {re.sub(r"[^a-z0-9]", "", str(k).lower()): v for k, v in row.items()}
    for key in keys:
        item = norm.get(re.sub(r"[^a-z0-9]", "", key.lower()))
        if item is not None and str(item).strip():
            return str(item).strip()
    return ""


def timestamp(raw, timezone="UTC"):
    if isinstance(raw, (int, float)) or (isinstance(raw, str) and raw.isdigit() and len(raw) in (10, 13)):
        number = float(raw)
        if number > 1e11:
            number /= 1000
        try:
            return dt.datetime.fromtimestamp(number, UTC)
        except (ValueError, OverflowError, OSError):
            return None
    s = str(raw).strip()
    if not s:
        return None
    s = s.replace("Z", "+00:00")
    try:
        result = dt.datetime.fromisoformat(s)
    except ValueError:
        result = None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                result = dt.datetime.strptime(s, fmt)
                break
            except ValueError:
                pass
        if result is None:
            return None
    if result.tzinfo is None:
        result = result.replace(tzinfo=ZoneInfo(timezone))
    try:
        return result.astimezone(UTC)
    except (ValueError, OverflowError):
        return None


def display_timestamp(raw, timezone="UTC", clock="utc"):
    instant = dt.datetime.fromisoformat(raw)
    if instant.tzinfo is None:
        instant = instant.replace(tzinfo=UTC)
    shown = instant.astimezone(ZoneInfo(timezone) if clock == "local" else UTC)
    return shown.strftime("%H:%M:%S"), shown.strftime("%Y-%m-%d"), shown.tzname() or "UTC"


def extract_rows(payload):
    if isinstance(payload, list):
        return payload
    if isinstance(payload, dict):
        for key in ("lastheard", "last_heard", "heard", "entries", "records", "data", "results"):
            item = payload.get(key)
            if isinstance(item, list):
                return item
        if len(payload) == 1 and isinstance(next(iter(payload.values())), list):
            return next(iter(payload.values()))
    raise ValueError("Unknown WPSD JSON shape; save a redacted sample for adapter support")


def parse_row(row, station="", timezone="UTC"):
    if not isinstance(row, dict):
        return None
    mode_raw = re.sub(r"[^A-Z0-9]", "", value(row, "mode", "protocol", "type").upper())
    if mode_raw.startswith("DMR"):
        mode = "DMR"
    elif mode_raw.startswith(("YSF", "C4FM", "FUSION")):
        mode = "YSF"
    elif mode_raw.startswith("DSTAR"):
        mode = "D-Star"
    elif mode_raw.startswith(("P25", "APCO25")):
        mode = "P25"
    elif mode_raw.startswith("NXDN"):
        mode = "NXDN"
    elif mode_raw == "M17":
        mode = "M17"
    elif mode_raw in ("FM", "ANALOGFM"):
        mode = "FM"
    else:
        return None
    call = value(row, "callsign", "call sign", "call", "source callsign").upper().split(" ")[0]
    if not CALL.fullmatch(call) or (station and call.split("/")[0] == station.split("/")[0]):
        return None
    # Current and older WPSD builds have both used time_utc. Keep the aliases
    # because the official API documentation does not publish a response schema.
    raw_time = value(row, "time_utc", "time utc", "heard at", "heard_at", "timestamp", "datetime", "start", "time")
    heard = timestamp(raw_time, timezone)
    if heard is None or not dt.datetime(1970, 1, 2, tzinfo=UTC) <= heard < dt.datetime(9999, 12, 30, tzinfo=UTC):
        return None
    target = value(row, "talk group", "talkgroup", "target", "destination", "reflector", "room")[:100]
    direction = value(row, "src", "source", "direction", "origin", "via")[:30]
    duration = value(row, "duration", "seconds")[:30]
    # Stable across repeated polls; distinct transmissions remain distinct.
    identity = "\0".join((call, mode, target, direction, heard.isoformat(), duration))
    return (hashlib.sha256(identity.encode()).hexdigest()[:32], call, mode, target,
            direction, heard.isoformat(), duration, json.dumps(row, ensure_ascii=False)[:2000],
            dt.datetime.now(UTC).isoformat())


def dashboard_url(api_url):
    parts = urllib.parse.urlsplit(api_url)
    prefix = re.split(r"/api(?:/|$)", parts.path, maxsplit=1)[0]
    return urllib.parse.urlunsplit(parts._replace(path=prefix.rstrip("/") + "/", query="", fragment=""))


def read_wpsd_page(url):
    request = urllib.request.Request(url, headers={"User-Agent": f"HotspotLogger/{VERSION}", "Cache-Control": "no-cache"})
    with urllib.request.urlopen(request, timeout=3) as response:
        raw = response.read(300_001)
    if len(raw) > 300_000:
        raise ValueError("WPSD page response was too large")
    return raw.decode("utf-8", "replace")


class DashboardCells(HTMLParser):
    """Read the public status panel without executing dashboard scripts."""
    def __init__(self):
        super().__init__()
        self.cells, self.capture = [], None
        self.depth = 0

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        classes = attrs.get("class", "").split()
        if tag in ("br", "img", "input", "meta", "link", "hr", "wbr"):
            if self.capture and tag == "br":
                self.capture[1].append(" ")
            return
        self.depth += 1
        if self.capture:
            if attrs.get("title"):
                self.capture[2].append(attrs["title"])
            return
        legacy_cell = any(c in classes for c in ("divTableHead", "divTableHeadCell", "divTableCell"))
        current_head = "sidebar-section-title" in classes
        current_cell = "status-pill" in classes
        if tag in ("td", "th") or legacy_cell or current_head or current_cell:
            kind = "head" if "divTableHead" in classes or current_head else "cell"
            self.capture = [kind, [], [attrs.get("title", "")], self.depth]

    def handle_endtag(self, tag):
        if tag in ("br", "img", "input", "meta", "link", "hr", "wbr"):
            return
        if self.capture and self.depth == self.capture[3]:
            kind, pieces, titles, _ = self.capture
            self.cells.append((kind, " ".join("".join(pieces).split()), " ".join(titles).strip()))
            self.capture = None
        self.depth = max(0, self.depth - 1)

    def handle_data(self, data):
        if self.capture:
            self.capture[1].append(data)


def clean_room(room):
    room = " ".join(str(room).split())[:100]
    if not room or re.search(r"(?:not linked|unlinked|service not started|mode paused|^null$|^off$|^on$|^DG[- ]?ID)", room, re.I):
        return ""
    return room


def parse_ysf_room(page):
    parser = DashboardCells()
    parser.feed(page)
    section = []
    active = False
    for kind, text, title in parser.cells:
        if kind == "head":
            if active:
                break
            active = bool(re.match(r"^YSF\s*(?:Status|Net|Network)\b", text, re.I))
        elif active:
            section.append((text, title))
    for index, (text, title) in enumerate(section):
        if re.fullmatch(r"Link(?:ed to)?|Room|Reflector", text, re.I) and index + 1 < len(section):
            return clean_room(section[index + 1][0])
        combined = re.fullmatch(r"(?:Linked\s*to|Link|Room|Reflector)\s*:?\s*(.+)", text, re.I)
        if combined:
            return clean_room(combined.group(1))
    for text, title in section:
        linked = re.search(r"(?:In Room:|Linked to:?)[ ]*(.+)", title, re.I)
        if linked:
            return clean_room(linked.group(1))
    return clean_room(section[0][0]) if len(section) == 1 else ""


def observed_ysf_room(row, entry, settings, current_room):
    if entry[2] != "YSF":
        return ""
    explicit = clean_room(value(row, "room", "reflector", "linked_room", "ysf_room"))
    if explicit:
        return explicit
    if not re.match(r"^DG[- ]?ID\b", entry[3], re.I):
        return clean_room(entry[3])
    # A current link cannot establish the room used by historical Last Heard rows.
    age = (dt.datetime.now(UTC) - dt.datetime.fromisoformat(entry[5])).total_seconds()
    return current_room if -5 <= age <= max(60, 2 * int(settings["poll_seconds"])) else ""


def canonical_target(mode, target):
    target = re.sub(r"\s+at\s+.*$", "", target, flags=re.I).strip().upper()
    if mode == "DMR":
        match = re.fullmatch(r"(?:TG|TALKGROUP)?\s*[-:]?\s*(\d+)", target)
        if match:
            return match.group(1)
    if mode == "YSF":
        match = re.fullmatch(r"DG\s*[- ]?\s*ID\s*[-:]?\s*(\d+)", target)
        if match:
            return "DG-ID " + match.group(1)
    return " ".join(target.split())


def activity_channel(row, entry, room):
    target = canonical_target(entry[2], entry[3])
    slot = value(row, "slot", "timeslot", "time_slot")
    slot_number = re.search(r"\d+", slot)
    slot = slot_number.group() if slot_number else slot.upper()
    if not target and not room:
        return ""
    return json.dumps([entry[2], target, room.upper(), slot])


def direction_kind(raw):
    direction = re.sub(r"[^A-Z0-9]", "", str(raw).upper())
    if direction in ("RF", "LOCAL", "LOCALRF", "RADIO") or direction.startswith("RF") or direction.endswith("RF"):
        return "rf"
    if direction in ("NET", "NETWORK", "INTERNET") or "NETWORK" in direction or direction.startswith("NET"):
        return "net"
    return ""


def duration_seconds(raw):
    text = str(raw).strip()
    if not text:
        return None
    numeric = re.fullmatch(r"([0-9]+(?:\.[0-9]+)?)\s*(?:s|sec|secs|second|seconds)?", text, re.I)
    if numeric:
        return float(numeric.group(1))
    if re.fullmatch(r"\d{1,2}:\d{2}(?::\d{2})?", text):
        parts = [int(part) for part in text.split(":")]
        return float(sum(part * 60 ** index for index, part in enumerate(reversed(parts))))
    return -1


def possible_exchanges(activity, station):
    """Return one candidate per continuous A/B/A or B/A/B conversation."""
    groups, matches, session_ends = {}, {}, {}
    for row in activity:
        channel = row["channel"]
        if not channel:
            continue
        key = (row["hotspot_id"], row["source_url"], channel)
        turns = groups.setdefault(key, [])
        own = row["call"].split("/")[0] == station.split("/")[0]
        duration = duration_seconds(row["duration"])
        if duration == -1 or (duration is not None and not 2 <= duration <= 3600):
            continue
        if own and direction_kind(row["direction"]) != "rf":
            # WPSD can show a network echo of the local callsign. Ignore it;
            # it must not erase otherwise valid RF evidence.
            continue
        actor = station if own else row["call"]
        when = dt.datetime.fromisoformat(row["heard_utc"])
        if turns and when < turns[-1]["when"]:
            turns.clear()
        if turns and when == turns[-1]["when"]:
            if turns[-1]["actor"] == actor:
                turns[-1]["ids"].append(row["id"])
            else:
                turns.clear()
            continue
        if turns and (when - turns[-1]["when"]).total_seconds() > 300:
            turns.clear()
        if turns and turns[-1]["actor"] == actor:
            turns[-1]["when"] = when
            turns[-1]["ids"].append(row["id"])
        else:
            turns.append({"actor": actor, "when": when, "ids": [row["id"]]})
            turns[:] = turns[-3:]
        if len(turns) == 3 and turns[0]["actor"] == turns[2]["actor"] and station in (turns[0]["actor"], turns[1]["actor"]):
            if (turns[2]["when"] - turns[0]["when"]).total_seconds() <= 300:
                pattern = " → ".join(turn["actor"] for turn in turns)
                other_turn = next(turn for turn in turns if turn["actor"] != station)
                session_key = (key, other_turn["actor"])
                previous_end = session_ends.get(session_key)
                if previous_end is None or (turns[0]["when"] - previous_end).total_seconds() > 300:
                    # Use the first transmission from the other station as the
                    # review row and QSO start-time suggestion. The remaining
                    # bursts stay visible in Activity queue without becoming
                    # duplicate possible contacts.
                    matches[other_turn["ids"][0]] = pattern
                session_ends[session_key] = turns[2]["when"]
    return matches


def poll_once(settings=None):
    settings = settings or get_settings()
    if "hotspot_id" not in settings:
        settings = source_settings(settings, configured_hotspots(settings)[0])
    url = settings["wpsd_url"]
    parts = urllib.parse.urlsplit(url)
    if parts.scheme not in ("http", "https") or not parts.hostname:
        raise ValueError("WPSD URL must be an HTTP(S) URL")
    poll_limit = max(10, min(200, int(settings["poll_limit"])))
    query = urllib.parse.parse_qs(parts.query)
    if parts.path.rstrip("/").endswith("last_heard.php"):
        query.update({"num_transmissions": [str(poll_limit)]})
    else:
        query.update({"limit": [str(poll_limit)], "names": ["false"], "country": ["false"]})
    target = urllib.parse.urlunsplit(parts._replace(query=urllib.parse.urlencode(query, doseq=True)))
    request = urllib.request.Request(target, headers={"User-Agent": f"HotspotLogger/{VERSION} ({settings['station_callsign']})", "Accept": "application/json"})
    with urllib.request.urlopen(request, timeout=7) as response:
        raw = response.read(2_000_001)
    if len(raw) > 2_000_000:
        raise ValueError("WPSD API response exceeded 2 MB")
    payload = json.loads(raw)
    rows = extract_rows(payload)
    parsed_rows = [(row, entry) for row in rows if (entry := parse_row(row, timezone=settings["wpsd_timezone"]))]
    status = SOURCE_STATUS.setdefault(settings["hotspot_id"], {})
    current_room = ""
    if any(entry[2] == "YSF" for _, entry in parsed_rows):
        try:
            current_room = parse_ysf_room(read_wpsd_page(dashboard_url(url)))
            status["room_error"] = "" if current_room else "YSF room not available from the public dashboard"
        except Exception:
            status["room_error"] = "YSF room unavailable; Last Heard polling continues"
    status.update(url=url, ysf_room=current_room)
    if rows and not parsed_rows:
        status["error"] = "WPSD replied, but no timestamped voice calls were recognized; inspect a redacted JSON sample"
    else:
        status["error"] = ""
    parsed, activity = [], []
    for row, entry in parsed_rows:
        if settings["hotspot_id"] != "primary":
            identity = hashlib.sha256((settings["hotspot_id"] + "\0" + entry[0]).encode()).hexdigest()[:32]
            entry = (identity, *entry[1:])
        room = observed_ysf_room(row, entry, settings, current_room)
        activity.append((entry[0], settings["hotspot_id"], url, entry[1], activity_channel(row, entry, room), entry[4], entry[5], entry[6]))
        if entry[1].split("/")[0] != settings["station_callsign"].split("/")[0]:
            parsed.append((*entry, settings["hotspot_id"], settings["hotspot_label"], room))
    with db() as cx:
        cx.executemany("""INSERT OR IGNORE INTO heard
            (id,call,mode,target,direction,heard_utc,duration,raw,first_seen,hotspot_id,hotspot_label,ysf_room)
            SELECT ?,?,?,?,?,?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM removed WHERE id=?)""",
            [(*entry, entry[0]) for entry in parsed])
        cx.executemany("""INSERT OR IGNORE INTO activity
            SELECT ?,?,?,?,?,?,?,? WHERE NOT EXISTS (SELECT 1 FROM removed WHERE id=?)""",
            [(*entry, entry[0]) for entry in activity])
        cx.executemany("UPDATE heard SET ysf_room=? WHERE id=? AND ysf_room='' AND logged_at IS NULL",
                       [(entry[-1], entry[0]) for entry in parsed if entry[-1]])
        cx.executemany("UPDATE activity SET channel=? WHERE id=? AND channel=''",
                       [(entry[4], entry[0]) for entry in activity if entry[4]])
        if activity:
            rebuild_key = (settings["hotspot_id"], url)
            if rebuild_key not in EXCHANGE_REBUILDS:
                # Rebuild retained evidence once per process so upgrading also
                # clears duplicate flags created by earlier beta versions.
                evidence = cx.execute("SELECT * FROM activity WHERE hotspot_id=? AND source_url=? ORDER BY heard_utc,id",
                                      rebuild_key).fetchall()
                cx.execute("UPDATE heard SET exchange_pattern='' WHERE hotspot_id=? AND logged_at IS NULL",
                           (settings["hotspot_id"],))
                EXCHANGE_REBUILDS[rebuild_key] = True
            else:
                lower = (min(dt.datetime.fromisoformat(entry[6]) for entry in activity) - dt.timedelta(seconds=300)).isoformat()
                upper = (max(dt.datetime.fromisoformat(entry[6]) for entry in activity) + dt.timedelta(seconds=300)).isoformat()
                evidence = cx.execute("SELECT * FROM activity WHERE hotspot_id=? AND source_url=? AND heard_utc BETWEEN ? AND ? ORDER BY heard_utc,id",
                                      (*rebuild_key, lower, upper)).fetchall()
                cx.execute("""UPDATE heard SET exchange_pattern='' WHERE logged_at IS NULL AND id IN
                    (SELECT id FROM activity WHERE hotspot_id=? AND source_url=? AND heard_utc BETWEEN ? AND ?)""",
                           (*rebuild_key, lower, upper))
            matches = possible_exchanges(evidence, settings["station_callsign"])
            cx.executemany("UPDATE heard SET exchange_pattern=? WHERE id=? AND logged_at IS NULL",
                           [(pattern, identity) for identity, pattern in matches.items()])
        retention_cutoff = (dt.datetime.now(UTC)-dt.timedelta(days=int(settings["queue_retention_days"]))).isoformat()
        cx.execute("DELETE FROM activity WHERE heard_utc < ?", (retention_cutoff,))
        cx.execute("DELETE FROM heard WHERE logged_at IS NULL AND first_seen < ?", (retention_cutoff,))
        cx.execute("""DELETE FROM activity WHERE id IN (
            SELECT id FROM activity WHERE hotspot_id=? AND source_url=?
            ORDER BY heard_utc DESC,id DESC LIMIT -1 OFFSET ?)""",
                   (settings["hotspot_id"], url, MAX_ACTIVITY_PER_HOTSPOT))
        cx.execute("""DELETE FROM heard WHERE logged_at IS NULL AND id IN (
            SELECT id FROM heard WHERE hotspot_id=? AND logged_at IS NULL
            ORDER BY first_seen DESC,id DESC LIMIT -1 OFFSET ?)""",
                   (settings["hotspot_id"], MAX_UNLOGGED_PER_HOTSPOT))
    status["last_ok"] = dt.datetime.now(UTC).isoformat()
    STATUS.update(last_ok=status["last_ok"], error=status["error"])
    return len(parsed)


def poll_loop():
    while True:
        settings = get_settings()
        if settings_ready(settings):
            errors = []
            for hotspot in configured_hotspots(settings):
                source = source_settings(settings, hotspot)
                try:
                    poll_once(source)
                except Exception as exc:
                    error = f"{type(exc).__name__}: {exc}"
                    SOURCE_STATUS.setdefault(hotspot["id"], {}).update(url=hotspot["url"], error=error, ysf_room="")
                    errors.append(f"{hotspot['label']}: {error}")
                refresh_theme(source)
            STATUS["error"] = "; ".join(errors) or "; ".join(
                f"{hotspot['label']}: {SOURCE_STATUS.get(hotspot['id'], {}).get('error', '')}"
                for hotspot in configured_hotspots(settings) if SOURCE_STATUS.get(hotspot['id'], {}).get("error"))
            timeout = max(5, min(300, int(settings["poll_seconds"])))
        else:
            STATUS.update({"last_ok": None, "error": "Setup required"})
            timeout = 2
        if CONFIG_CHANGED.wait(timeout):
            CONFIG_CHANGED.clear()


def band_for(freq):
    if not re.fullmatch(r"[0-9]+(?:\.[0-9]+)?", str(freq)):
        return ""
    try:
        n = float(freq)
    except (ValueError, TypeError):
        return ""
    for lo, hi, name in ((28, 29.7, "10m"), (50, 54, "6m"), (144, 148, "2m"), (420, 450, "70cm"), (902, 928, "33cm"), (1240, 1300, "23cm")):
        if lo <= n <= hi:
            return name
    return ""


def adif_field(name, contents):
    contents = str(contents)
    if not contents:
        return ""
    if any(not 32 <= ord(char) <= 126 for char in contents):
        raise ValueError("ADIF fields use plain ASCII. Replace accented letters or symbols in the comment before saving.")
    return f"<{name}:{len(contents)}>{contents}"


def make_adif(call, mode, when, band, freq, target, comment, station="", propagation="INTERNET"):
    when = when.astimezone(UTC)
    if mode not in MODE_SPECS or propagation not in ("INTERNET", "RPT", "LOS"):
        raise ValueError("Choose a supported voice mode and propagation")
    adif_mode, submode = MODE_SPECS[mode]
    comment = comment or (f"{mode} {target} via WPSD" if target else f"{mode} via WPSD")
    if mode in ("P25", "NXDN") and mode.lower() not in comment.lower():
        comment = f"{mode} | {comment}"
    fields = {"CALL": call, "STATION_CALLSIGN": station,
              "QSO_DATE": when.strftime("%Y%m%d"), "TIME_ON": when.strftime("%H%M%S"),
              "BAND": band, "MODE": adif_mode, "SUBMODE": submode,
              "PROP_MODE": propagation, "FREQ": freq, "COMMENT": comment}
    return "".join(adif_field(k, v) for k, v in fields.items()) + "<EOR>"


class QRZUncertainError(Exception):
    """The response does not establish whether QRZ inserted the contact."""


def qrz_insert(adif, key, station):
    payload = urllib.parse.urlencode({"KEY": key, "ACTION": "INSERT", "ADIF": adif}).encode()
    request = urllib.request.Request("https://logbook.qrz.com/api", data=payload,
        headers={"User-Agent": f"HotspotLogger/{VERSION} ({station})", "Content-Type": "application/x-www-form-urlencoded"})
    try:
        with urllib.request.urlopen(request, timeout=12) as response:
            answer = response.read(4097).decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        try:
            answer = exc.read(4097).decode("utf-8", "replace")
        except (OSError, http.client.HTTPException) as read_error:
            raise QRZUncertainError("QRZ's error response was incomplete. Check your QRZ logbook.") from read_error
        parsed_error = urllib.parse.parse_qs(answer, keep_blank_values=True)
        if len(answer.encode("utf-8")) <= 4096 and parsed_error.get("RESULT") in (["FAIL"], ["AUTH"]):
            reason = parsed_error.get("REASON", [f"HTTP {exc.code}"])[0]
            raise ValueError(f"QRZ rejected the request: {reason[:200]}") from exc
        raise QRZUncertainError(f"QRZ returned HTTP {exc.code} without a confirmed result. Check your QRZ logbook.") from exc
    except (OSError, http.client.HTTPException) as exc:
        raise QRZUncertainError("The QRZ connection failed before a complete confirmation arrived. Check your QRZ logbook.") from exc
    parsed = urllib.parse.parse_qs(answer, keep_blank_values=True)
    result = parsed.get("RESULT", [""])[0]
    if len(answer.encode("utf-8")) <= 4096 and parsed.get("RESULT") in (["FAIL"], ["AUTH"]):
        fallback = "API access lacks sufficient privileges. Check the key and subscription." if result == "AUTH" else "no reason given"
        raise ValueError(f"QRZ rejected the request: {parsed.get('REASON', [fallback])[0][:200]}")
    logid = parsed.get("LOGID", parsed.get("LOGIDS", [""]))[0]
    if len(answer.encode("utf-8")) > 4096 or parsed.get("RESULT") != ["OK"] or parsed.get("COUNT") != ["1"] or not logid.isdigit():
        raise QRZUncertainError("QRZ did not return a complete insert confirmation. Check your QRZ logbook.")
    return logid


CSS = """<style>
:root{color-scheme:dark;--bg:#111418;--card:#191e24;--card2:#20262d;--line:#343d47;--text:#eef1f4;--muted:#a2aab4;--accent:#64b5c4;--accentText:#101418;--field:#14191f;--blue:#9cc9d4;--warn:#e6bd73;--warnBg:#332b1f}
*{box-sizing:border-box}body{margin:0;background:var(--bg);color:var(--text);font:14px/1.5 system-ui,-apple-system,sans-serif}a{color:var(--blue)}button,input,select{font:inherit}button,.linkbtn{display:inline-block;padding:7px 12px;border:1px solid var(--accent);border-radius:4px;background:var(--accent);color:var(--accentText);font-weight:600;text-decoration:none;cursor:pointer}.secondary{background:transparent;border-color:var(--line);color:var(--text)}.danger{background:transparent!important;border-color:#a65460!important;color:#ecadb5!important}button:disabled{opacity:.45;cursor:not-allowed}.shell{max-width:1480px;margin:auto;padding:24px 32px}.site-header{display:flex;align-items:center;justify-content:space-between;gap:20px;padding-bottom:20px;border-bottom:1px solid var(--line)}h1{font-size:23px;font-weight:650;letter-spacing:-.4px;margin:0}h2{font-size:17px;font-weight:600;margin:0 0 12px}p{margin:8px 0}.brand-kicker{font-size:12px;color:var(--muted)}.header-actions,.actions{display:flex;align-items:center;gap:8px;flex-wrap:wrap}.muted,time,.field-help{color:var(--muted);font-size:12px}.source-strip{display:flex;gap:18px;flex-wrap:wrap;border-bottom:1px solid var(--line);padding:12px 0;color:var(--muted);font-size:12px}.source-strip strong{color:var(--text);font-weight:600}.source-strip .error{color:var(--warn)}.summary-line{display:flex;gap:28px;flex-wrap:wrap;padding:20px 0;font-size:13px}.summary-line strong{font-size:17px;font-variant-numeric:tabular-nums;margin-right:6px}.toolbar{display:flex;align-items:center;justify-content:space-between;gap:16px;flex-wrap:wrap;margin-bottom:14px}.tabs{display:flex;gap:18px;align-items:center}.tabs a{color:var(--muted);text-decoration:none;padding:7px 0;border-bottom:2px solid transparent}.tabs a.active{color:var(--text);border-color:var(--accent)}.toolbar-controls,.filters,.clock-toggle{display:flex;gap:7px;align-items:center}.toolbar-controls,.filters{margin:0}.clock-toggle{border:1px solid var(--line);border-radius:4px;padding:2px}.clock-toggle a{color:var(--muted);padding:4px 8px;text-decoration:none;border-radius:2px;font-size:12px}.clock-toggle a.active{background:var(--card2);color:var(--text)}.filters select{width:auto;max-width:230px;padding:6px 9px}.table-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:4px}table{border-collapse:collapse;width:100%;text-align:left;background:var(--card)}th{background:var(--card2);color:var(--muted);font-weight:500;font-size:11px;text-transform:uppercase;letter-spacing:.4px;white-space:nowrap}th,td{padding:12px 14px;border-bottom:1px solid var(--line);vertical-align:middle}tr:last-child td{border-bottom:0}tbody tr:hover{background:var(--card2)}td .small{display:block;color:var(--muted);font-size:11px;line-height:1.6}.call{font-size:15px;font-weight:650;white-space:nowrap}.mode{font-size:12px;white-space:nowrap}.row-actions{display:flex;gap:12px;align-items:center;white-space:nowrap}.row-actions a{text-decoration:none;font-size:12px}.row-actions .delete{color:#ecadb5}.state{font-size:12px}.state.possible,.state.saved{color:var(--blue)}.state.pending{color:var(--warn)}.empty{padding:34px 18px;text-align:center;color:var(--muted)}.context{margin:13px 0;color:var(--muted);font-size:12px}footer{margin-top:26px;color:var(--muted);font-size:11px;display:flex;justify-content:space-between;gap:12px;flex-wrap:wrap}.notice{padding:11px 13px;border:1px solid var(--line);background:var(--card2);border-radius:4px;margin:16px 0}.notice.ok{border-left:3px solid var(--accent)}.setup-shell{max-width:1000px;margin:auto;padding:30px 24px}.setup-header{display:flex;align-items:center;justify-content:space-between;border-bottom:1px solid var(--line);padding-bottom:18px;margin-bottom:24px;gap:16px}.setup-card{padding:22px 0;margin:0}.setup-grid,.grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:16px;margin:18px 0}.setup-grid label,.grid label,.hotspot-fields label{display:flex;flex-direction:column;gap:5px;font-size:12px}.wide{grid-column:1/-1}input,select{width:100%;min-width:0;padding:8px 10px;border:1px solid var(--line);border-radius:4px;background:var(--field);color:var(--text)}input:focus,select:focus{outline:2px solid var(--accent);outline-offset:1px}.help-box{font-size:12px;color:var(--muted);line-height:1.6;margin:8px 0 15px}.field-help{font-size:11px}.checkbox{display:flex!important;flex-direction:row!important;align-items:center;gap:8px!important}.checkbox input{width:auto}.hotspot-row{border:1px solid var(--line);border-radius:4px;padding:16px;margin:12px 0;background:var(--card)}.hotspot-row legend{padding:0 6px;font-size:12px;color:var(--muted)}.hotspot-fields{display:grid;grid-template-columns:1fr 2fr 1fr;gap:12px}.hotspot-row .remove-hotspot{margin-top:12px;font-size:11px;padding:4px 8px}.setup-actions{display:flex;justify-content:space-between;align-items:center;gap:12px;border-top:1px solid var(--line);margin-top:24px;padding-top:18px}.section-rule{border:0;border-top:1px solid var(--line);margin:26px 0}.review-meta{display:flex;gap:22px;flex-wrap:wrap;font-size:13px;color:var(--muted);padding:16px 0;border-bottom:1px solid var(--line)}.review-meta strong{color:var(--text)}.review-note{font-size:12px;color:var(--muted);margin:16px 0}code{font-size:12px;overflow-wrap:anywhere}.setup-shell .actions{margin-top:20px}
.brand-logo{display:block;width:300px;max-width:100%;height:auto;background:#fff;border-radius:4px;padding:8px;margin-bottom:8px}.beta{display:inline-block;border:1px solid var(--line);border-radius:3px;padding:1px 5px;margin-left:5px;color:var(--text)}.independence{flex-basis:100%}.creator-credit{display:inline-flex;align-items:center;gap:5px;white-space:nowrap}.creator-credit a{color:inherit;text-decoration:none}
@media(max-width:850px){.shell{padding:16px}.hotspot-fields{grid-template-columns:1fr 1fr}.hotspot-fields .hotspot-url{grid-column:1/-1;grid-row:2}.table-wrap{border:0;overflow:visible}thead{display:none}table,tbody,tr,td{display:block}tbody tr{border:1px solid var(--line);border-radius:4px;padding:9px 13px;margin-bottom:10px;background:var(--card)}td{border:0;padding:4px 0;display:grid;grid-template-columns:92px 1fr;gap:8px}td:before{content:attr(data-label);font-size:11px;color:var(--muted);font-weight:400}.row-actions{margin:2px 0}.toolbar{align-items:flex-start}.source-strip{gap:9px}.summary-line{gap:18px;padding:16px 0}}
@media(max-width:560px){.site-header{align-items:flex-start;flex-direction:column;gap:12px;padding-bottom:15px}h1{font-size:21px}.header-actions{gap:6px}.header-actions .linkbtn{font-size:12px;padding:6px 9px}.setup-shell{padding:18px 15px}.setup-grid,.grid,.hotspot-fields{grid-template-columns:1fr}.hotspot-fields .hotspot-url{grid-column:auto;grid-row:auto}.wide{grid-column:auto}.toolbar-controls,.filters{flex-wrap:wrap}.toolbar-controls{width:100%}.filters select{max-width:170px}.tabs{gap:15px;font-size:12px}.setup-actions{align-items:stretch;flex-direction:column-reverse}.setup-header{align-items:flex-start}.hotspot-row{padding:12px}.summary-line strong{font-size:15px}.review-meta{gap:12px}}
@media(prefers-color-scheme:light){:root{color-scheme:light;--bg:#f6f7f8;--card:#fff;--card2:#f0f2f4;--line:#d7dce1;--text:#242b32;--muted:#626c77;--accent:#286b78;--accentText:#fff;--field:#fff;--blue:#286b78;--warn:#8c600e;--warnBg:#fff5df}.danger,.row-actions .delete{color:#963340!important}}
</style>"""


class ThemeLinks(HTMLParser):
    def __init__(self):
        super().__init__()
        self.stylesheets = []

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "link" and "stylesheet" in attrs.get("rel", "").lower().split():
            self.stylesheets.append(attrs.get("href", ""))


def parse_theme_colors(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    rules = {}
    for selectors, body in re.findall(r"([^{}]+)\{([^{}]*)\}", css):
        declarations = dict(re.findall(r"([\w-]+)\s*:\s*([^;{}]+)", body))
        for selector in selectors.split(","):
            rules.setdefault(selector.strip().lower(), {}).update(declarations)

    def color(selectors, properties):
        for selector in selectors:
            for prop in properties:
                raw = rules.get(selector, {}).get(prop, "").strip().lower()
                if prop == "border":
                    found = re.search(r"(#[0-9a-f]{6}|#[0-9a-f]{3})\s*$", raw)
                    raw = found.group(1) if found else ""
                if re.fullmatch(r"#[0-9a-f]{6}|#[0-9a-f]{3}", raw):
                    return "#" + "".join(c * 2 for c in raw[1:]) if len(raw) == 4 else raw
        return ""

    roles = {
        "bg": (("body", "html", ".container"), ("background-color", "background")),
        "card": ((".container", ".content", "table tr:nth-child(odd)"), ("background-color", "background")),
        "card2": (("table tr:nth-child(even)", ".content", ".container"), ("background-color", "background")),
        "text": (("table td", ".content", "body"), ("color",)),
        "accent": ((".navbar", ".header", "button"), ("background-color", "background")),
        "accentText": ((".navbar a", ".header", "button"), ("color",)),
        "blue": (("a", "a:link"), ("color",)),
        "line": (("table td", "table", ".container"), ("border-color", "border")),
    }
    colors = {key: found for key, (selectors, properties) in roles.items()
              if (found := color(selectors, properties))}
    if not all(key in colors for key in ("bg", "card", "text", "accent")):
        raise ValueError("WPSD stylesheet did not expose the expected theme colors")
    colors.setdefault("card2", colors["card"])
    colors.setdefault("blue", colors["accent"])
    rgb = tuple(int(colors["accent"][i:i + 2], 16) for i in (1, 3, 5))
    colors.setdefault("accentText", "#000000" if sum(rgb) > 382 else "#ffffff")
    return colors


def refresh_theme(settings):
    if settings["theme_mode"] != "wpsd":
        return
    url = settings["wpsd_url"]
    cache = THEME_CACHES.setdefault(url, {"checked": 0, "colors": {}, "status": "Waiting for WPSD colors"})
    if cache["checked"] and time.monotonic() - cache["checked"] < 300:
        return
    cache["checked"] = time.monotonic()
    parts = urllib.parse.urlsplit(url)
    dashboard = dashboard_url(url)

    try:
        links = ThemeLinks()
        links.feed(read_wpsd_page(dashboard))
        candidates = []
        for href in links.stylesheets:
            stylesheet = urllib.parse.urljoin(dashboard, href)
            style_parts = urllib.parse.urlsplit(stylesheet)
            if style_parts.scheme == parts.scheme and style_parts.netloc == parts.netloc:
                if re.search(r"(?:wpsd|pistar|theme|style)", style_parts.path, re.I) and "font" not in style_parts.path:
                    if stylesheet not in candidates:
                        candidates.append(stylesheet)
        if not candidates:
            raise ValueError("WPSD dashboard did not expose a theme stylesheet")
        for stylesheet in candidates[:3]:
            try:
                colors = parse_theme_colors(read_wpsd_page(stylesheet))
                cache.update({"colors": colors, "status": "Colors matched to WPSD"})
                return
            except (ValueError, urllib.error.URLError, TimeoutError):
                continue
        raise ValueError("WPSD theme colors could not be read")
    except Exception:
        cache["status"] = "Could not refresh WPSD colors; using the last matched colors or logger default"


def page_styles(settings):
    if settings["theme_mode"] != "wpsd":
        return CSS
    colors = THEME_CACHES.get(settings["wpsd_url"], {}).get("colors", {})
    if not colors:
        return CSS
    scheme = "dark" if sum(int(colors["bg"][i:i + 2], 16) for i in (1, 3, 5)) < 382 else "light"
    variables = ";".join(f"--{key}:{value}" for key, value in colors.items())
    return CSS + f"""<style>:root{{color-scheme:{scheme};{variables};--field:var(--card);--muted:var(--text)}}
.secondary{{background:transparent;color:var(--text)}}.notice.ok{{background:var(--card);color:var(--text);border-color:var(--line);border-left-color:var(--accent)}}
.state.saved,.state.possible{{color:var(--blue)}}.site-header{{border-bottom-color:var(--accent)}}
</style>"""


def option(value, current, label=None):
    selected = " selected" if str(value) == str(current) else ""
    return f"<option value='{html.escape(str(value))}'{selected}>{html.escape(label or str(value))}</option>"


COMMON_TIMEZONES = (
    ("UTC", "UTC"),
    ("America/New_York", "Eastern — America/New_York"),
    ("America/Chicago", "Central — America/Chicago"),
    ("America/Denver", "Mountain — America/Denver"),
    ("America/Phoenix", "Arizona — America/Phoenix"),
    ("America/Los_Angeles", "Pacific — America/Los_Angeles"),
    ("America/Anchorage", "Alaska — America/Anchorage"),
    ("Pacific/Honolulu", "Hawaii — Pacific/Honolulu"),
)
TIMEZONE_NAMES = frozenset(available_timezones()) | {"UTC"}


def timezone_options(current):
    common_names = {name for name, _ in COMMON_TIMEZONES}
    result = ["<optgroup label='Common'>"]
    result.extend(option(name, current, label) for name, label in COMMON_TIMEZONES)
    result.append("</optgroup>")
    groups = {}
    for name in sorted(TIMEZONE_NAMES - common_names):
        groups.setdefault(name.split("/", 1)[0] if "/" in name else "Other", []).append(name)
    if current not in TIMEZONE_NAMES:
        groups.setdefault("Current", []).insert(0, current)
    for group, names in sorted(groups.items()):
        result.append(f"<optgroup label='{html.escape(group.replace('_', ' '))}'>")
        result.extend(option(name, current) for name in names)
        result.append("</optgroup>")
    return "".join(result)


def hotspot_fields(hotspot, index):
    e = html.escape
    return f"""<fieldset class='hotspot-row'><legend>Hotspot</legend>
<input type='hidden' name='hotspot_id_{index}' value='{e(hotspot["id"])}'>
<div class='hotspot-fields'><label>Name<input required maxlength='40' name='hotspot_label_{index}' value='{e(hotspot["label"])}' placeholder='YSF desk'></label>
<label class='hotspot-url'>WPSD API URL<input required type='url' name='hotspot_url_{index}' value='{e(hotspot["url"])}' placeholder='http://192.168.1.50/api/'></label>
<label>Radio TX frequency · MHz<input required name='hotspot_freq_{index}' value='{e(hotspot["freq"])}' inputmode='decimal' placeholder='441.425'></label></div>
<button type='button' class='secondary remove-hotspot' data-remove-hotspot>Remove hotspot</button></fieldset>"""


def setup_page(settings, edit=False, error="", saved=False):
    e = html.escape
    action = "/settings" if edit else "/setup"
    title = "Logger settings" if edit else "Set up Hotspot Logger"
    intro = "Update the logger here without editing files or restarting Docker." if edit else "Add your hotspots and choose a logger password."
    token = form_token(settings, bootstrap=not edit)
    required = "" if edit else "required"
    password_help = "At least 8 characters. Leave both fields blank to keep your current password." if edit else "At least 8 characters."
    qrz_help = "A key is saved. Leave this blank to keep it." if settings["qrz_api_key"] else "Optional. Leave blank to save ADIF locally."
    notice = f"<p class='notice'>{e(error)}</p>" if error else ("<p class='notice ok'>Settings saved.</p>" if saved else "")
    back = "<a href='/'>Back to logger</a>" if edit else "<span class='muted'>Open the logger from a desktop or phone on your LAN.</span>"
    remove = "<label class='wide checkbox'><input type='checkbox' name='remove_qrz_key' value='yes'> Remove the saved QRZ key</label>" if edit and settings["qrz_api_key"] else ""
    hotspots = configured_hotspots(settings)
    rows = "".join(hotspot_fields(hotspot, index) for index, hotspot in enumerate(hotspots))
    template = hotspot_fields({"id": "", "label": "", "url": "", "freq": ""}, "__INDEX__")
    poll_options = "".join(option(value, settings["poll_seconds"], f"{value} seconds") for value in (5, 10, 15, 30, 60))
    limit_options = "".join(option(value, settings["poll_limit"]) for value in (20, 40, 75, 100, 200))
    retention_options = "".join(option(value, settings["queue_retention_days"],
                                       "1 day — recommended" if value == 1 else f"{value} days")
                                for value in (1, 3, 7, 14, 30))
    theme_options = option("wpsd", settings["theme_mode"], "Match WPSD") + option("logger", settings["theme_mode"], "Logger default")
    clock_options = option("local", settings["display_time_mode"], "Local time") + option("utc", settings["display_time_mode"], "UTC")
    timezone_choices = timezone_options(settings["display_timezone"])
    theme_status = " · ".join(f'{e(hotspot["label"])}: {e(THEME_CACHES.get(hotspot["url"], {}).get("status", "Waiting for WPSD colors"))}' for hotspot in hotspots)
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>{page_styles(settings)}</head>
<body><main class='setup-shell'><header class='setup-header'><div>{BRAND}<h1>{title}</h1><p class='muted'>{intro}</p></div>{back}</header>{notice}
<form method='post' action='{action}'><input type='hidden' name='csrf' value='{token}'><input type='hidden' name='hotspots_form' value='yes'>
<h2>Hotspots</h2><p class='help-box'>Give each hotspot a name, such as YSF desk or DMR travel. Each contact keeps its source. Removing a hotspot stops polling it and keeps its existing log entries.</p>
<div id='hotspots' data-next='{len(hotspots)}'>{rows}</div><button class='secondary' type='button' id='add-hotspot'>Add hotspot</button>
<p class='help-box'><strong>WPSD API URL:</strong> open the hotspot's dashboard and copy its address, then add <code>/api/</code>. Example: <code>http://192.168.1.50/api/</code>. A reserved IP works best in Docker. <a href='https://manual.wpsd.radio/advanced/api/'>WPSD API help</a><br>
<strong>Radio TX frequency:</strong> open <strong>Admin → Configuration</strong> in WPSD and use <strong>Radio Frequency RX</strong>. Your radio transmits on the hotspot's receive frequency. On duplex hotspots this differs from WPSD's TX frequency. <a href='https://manual.wpsd.radio/initial_startup/'>Frequency help</a></p>
<hr class='section-rule'><h2>Station and QRZ</h2><div class='setup-grid'>
<label>Station callsign<input required name='station_callsign' value='{e(settings["station_callsign"])}' autocomplete='username' placeholder='N0CALL'><span class='field-help'>Use the callsign that owns your QRZ logbook and appears on your RF transmissions.</span></label>
<label>QRZ Logbook API key<input name='qrz_api_key' type='password' value='' autocomplete='off' placeholder='Optional'><span class='field-help'>{qrz_help}</span></label>{remove}
<div class='wide help-box'>Get the key from <strong>My Logbook → Settings → API</strong> in QRZ. Copy the key for your station's logbook. API uploads need an eligible QRZ subscription. <a href='https://www.qrz.com/docs/logbook/QRZLogbookAPI.html'>QRZ API guide</a></div></div>
<hr class='section-rule'><h2>Preferences</h2><div class='setup-grid'>
<label>Poll interval<select name='poll_seconds'>{poll_options}</select><span class='field-help'>Ten seconds is a good default.</span></label>
<label>Rows per hotspot<select name='poll_limit'>{limit_options}</select></label>
<label>Activity queue retention<select name='queue_retention_days'>{retention_options}</select><span class='field-help'>One day is the default. A storage cap also keeps busy Raspberry Pi installations bounded. Saved and uploaded contacts are kept in Saved.</span></label>
<label>WPSD timestamp source zone<input required name='wpsd_timezone' value='{e(settings["wpsd_timezone"])}' placeholder='UTC'><span class='field-help'>Keep UTC for current WPSD. Change this only for an older feed that sends local timestamps without an offset.</span></label>
<label>Local time zone<select required id='display-timezone' name='display_timezone' data-detect='{"no" if edit else "yes"}'>{timezone_choices}</select><span class='field-help'>Used for the Local clock. Your browser selects its zone during first setup; you can change it here.</span></label>
<label>Default activity clock<select name='display_time_mode'>{clock_options}</select><span class='field-help'>The activity page also has a Local / UTC toggle.</span></label>
<label>Theme<select name='theme_mode'>{theme_options}</select><span class='field-help'>A hotspot filter uses that hotspot's colors. All hotspots uses the first hotspot's colors.</span></label>
<div class='wide field-help'>{theme_status}. WPSD color changes refresh within five minutes.</div>
<label>Logger password<input {required} type='password' name='password' minlength='8' autocomplete='new-password'><span class='field-help'>{password_help}</span></label>
<label>Repeat password<input {required} type='password' name='password_confirm' minlength='8' autocomplete='new-password'></label></div>
<div class='setup-actions'><span class='muted'>DMR · YSF · D-Star · P25 · NXDN · legacy M17 · FM</span><button>{'Save settings' if edit else 'Start logger'}</button></div></form>
<template id='hotspot-template'>{template}</template>
<script>
const list = document.getElementById('hotspots');
const add = document.getElementById('add-hotspot');
const displayTimezone = document.getElementById('display-timezone');
if (displayTimezone.dataset.detect === 'yes' && displayTimezone.value === 'UTC') {{
  const browserTimezone = Intl.DateTimeFormat().resolvedOptions().timeZone;
  if (browserTimezone && Array.from(displayTimezone.options).some(option => option.value === browserTimezone)) {{
    displayTimezone.value = browserTimezone;
  }}
}}
function updateButtons() {{
  const rows = list.querySelectorAll('.hotspot-row');
  rows.forEach(row => row.querySelector('[data-remove-hotspot]').disabled = rows.length === 1);
  add.disabled = rows.length >= 16;
}}
add.addEventListener('click', () => {{
  const index = Number(list.dataset.next);
  list.dataset.next = index + 1;
  const wrapper = document.createElement('div');
  wrapper.innerHTML = document.getElementById('hotspot-template').innerHTML.replaceAll('__INDEX__', String(index));
  const row = wrapper.firstElementChild;
  row.querySelector('input[name=\"hotspot_label_' + index + '\"]').value = 'Hotspot ' + (list.children.length + 1);
  list.appendChild(row);
  updateButtons();
  row.querySelector('input[name=\"hotspot_label_' + index + '\"]').focus();
}});
list.addEventListener('click', event => {{
  if (event.target.closest('[data-remove-hotspot]') && list.children.length > 1) {{
    event.target.closest('.hotspot-row').remove();
    updateButtons();
  }}
}});
updateButtons();
</script>{page_footer()}</main></body></html>"""


def contact_hotspot(row, settings):
    return next((hotspot for hotspot in configured_hotspots(settings) if hotspot["id"] == row["hotspot_id"]),
                {"id": row["hotspot_id"], "label": row["hotspot_label"], "url": "", "freq": ""})


def contact_comment(row, settings):
    description = f'{row["mode"]} {row["target"]} via WPSD'.strip()
    if row["ysf_room"]:
        description = f'YSF room {row["ysf_room"]} | {row["target"]} via WPSD'
    elif row["mode"] == "YSF":
        hotspot = contact_hotspot(row, settings)
        status = SOURCE_STATUS.get(hotspot["id"], {})
        if status.get("url") == hotspot["url"] and status.get("ysf_room") and not status.get("error"):
            description += f'; current room {status["ysf_room"]} (verify)'
    return description[:200]


def default_propagation(row):
    return "INTERNET" if row["direction"].upper() in ("NET", "NETWORK") else "RPT"


def review_page(settings, row):
    e = html.escape
    hotspot = contact_hotspot(row, settings)
    source = source_settings(settings, hotspot) if hotspot["url"] else settings
    token = form_token(settings)
    local_time, local_date, local_zone = display_timestamp(row["heard_utc"], settings["display_timezone"], "local")
    mode_options = "".join(option(mode, row["mode"]) for mode in MODE_SPECS)
    propagation_options = "".join(option(code, default_propagation(row), label) for code, label in
                                  (("INTERNET", "Internet-assisted"), ("RPT", "Repeater / gateway"), ("LOS", "Direct RF / line of sight")))
    evidence = f'Possible exchange: {row["exchange_pattern"]}' if row["exchange_pattern"] else "Heard only. No A/B/A exchange was detected."
    room_note = "" if row["mode"] != "YSF" or row["ysf_room"] else "<p class='review-note'>The room at this transmission is unknown. A current room in the comment is only a suggestion; check it before logging.</p>"
    header = f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Review {e(row["call"])}</title>{page_styles(source)}</head><body><main class='setup-shell'>
<header class='setup-header'><h1>{e(row["call"])} <span class='muted'>/ Contact review</span></h1><a href='/'>Back to activity</a></header>
<div class='review-meta'><span>Hotspot <strong>{e(hotspot["label"])}</strong></span><span>Mode <strong>{e(row["mode"])}</strong></span><span>Destination <strong>{e(row["ysf_room"] or row["target"])}</strong></span></div>"""
    delete = f"<a class='linkbtn danger' href='/delete?id={e(row['id'])}'>Delete entry</a>"
    if row["log_status"] == "pending":
        return header + f"""<p class='notice'>QRZ result uncertain. Check your QRZ logbook before choosing. This record stays out of ADIF export until resolved.</p><form method='post' action='/resolve'><input type='hidden' name='csrf' value='{token}'><input type='hidden' name='id' value='{e(row["id"])}'><div class='actions'><button name='resolution' value='found'>Found in QRZ</button><button class='secondary' name='resolution' value='retry'>Not in QRZ — reopen</button>{delete}</div></form>{page_footer()}</main></body></html>"""
    if row["logged_at"]:
        label = "Uploaded to QRZ" if row["log_status"] in ("qrz", "qrz_manual") else "Saved for ADIF"
        return header + f"<p class='notice ok'>{label}. The saved record is included in your ADIF export.</p><div class='actions'><a class='linkbtn secondary' href='/export.adi'>ADIF export</a>{delete}</div>{page_footer()}</main></body></html>"
    return header + f"""<p class='review-note'>{e(evidence)}. Timing is a clue; it cannot establish what was said.</p>{room_note}
<form method='post' action='/log'><input type='hidden' name='csrf' value='{token}'><input type='hidden' name='id' value='{e(row["id"])}'><div class='grid'>
<label>Callsign<input required name='call' value='{e(row["call"])}'></label>
<label>UTC date / time<input required type='datetime-local' step='1' name='when' value='{e(row["heard_utc"][:19])}'><span class='field-help'>Local: {e(local_date)} {e(local_time)} {e(local_zone)} · {e(settings["display_timezone"])}</span></label>
<label>Radio TX frequency · MHz<input required name='freq' inputmode='decimal' value='{e(hotspot["freq"])}'></label>
<label>Band<input required name='band' value='{e(band_for(hotspot["freq"]))}' placeholder='70cm'></label>
<label>Mode<select name='mode'>{mode_options}</select></label><label>Propagation<select name='prop_mode'>{propagation_options}</select></label>
<label class='wide'>Comment<input name='comment' maxlength='200' value='{e(contact_comment(row, settings))}'></label></div>
<p class='review-note'>Log a two-way contact you actually made. Band describes your local RF link; Internet-assisted identifies a network path. P25 and NXDN use DIGITALVOICE with the protocol in the comment.</p>
<p class='field-help'>Use plain letters, numbers, and punctuation in the comment; ADIF .adi files use ASCII.</p>
<div class='actions'><button name='action' value='qrz' {'disabled' if not settings["qrz_api_key"] else ''}>Log to QRZ</button><button class='secondary' name='action' value='save'>Save to ADIF</button>{delete}</div></form>{page_footer()}</main></body></html>"""


def dashboard_page(settings, query):
    e = html.escape
    hotspots = configured_hotspots(settings)
    selected = query.get("hotspot", [""])[0]
    selected_hotspot = next((hotspot for hotspot in hotspots if hotspot["id"] == selected), None)
    if not selected_hotspot:
        selected = ""
    view = query.get("view", ["exchanges"])[0]
    if view == "all":
        view = "queue"
    if view not in ("exchanges", "queue", "saved"):
        view = "exchanges"
    clock = query.get("clock", [settings["display_time_mode"]])[0]
    if clock not in ("local", "utc"):
        clock = settings["display_time_mode"]
    mode = query.get("mode", [""])[0]
    if mode not in MODE_SPECS:
        mode = ""
    conditions, params = [], []
    if selected:
        conditions.append("hotspot_id=?")
        params.append(selected)
    if mode:
        conditions.append("mode=?")
        params.append(mode)
    base_where = " AND ".join(conditions) or "1=1"
    with db() as cx:
        counts = cx.execute(f"""SELECT
            SUM(CASE WHEN logged_at IS NULL THEN 1 ELSE 0 END),
            SUM(CASE WHEN logged_at IS NULL AND exchange_pattern!='' THEN 1 ELSE 0 END),
            SUM(CASE WHEN log_status='pending' THEN 1 ELSE 0 END),
            SUM(CASE WHEN logged_at IS NOT NULL AND COALESCE(log_status,'')!='pending' THEN 1 ELSE 0 END)
            FROM heard WHERE {base_where}""", params).fetchone()
        extra = {"queue": " AND (logged_at IS NULL OR log_status='pending')",
                 "exchanges": " AND (exchange_pattern!='' AND logged_at IS NULL OR log_status='pending')",
                 "saved": " AND logged_at IS NOT NULL AND COALESCE(log_status,'')!='pending'"}[view]
        entries = cx.execute(f"SELECT * FROM heard WHERE {base_where}{extra} ORDER BY heard_utc DESC LIMIT ?", params + [ACTIVITY_LIMIT]).fetchall()
    source = source_settings(settings, selected_hotspot or hotspots[0])
    source_status = []
    for hotspot in ([selected_hotspot] if selected_hotspot else hotspots):
        status = SOURCE_STATUS.get(hotspot["id"], {})
        if status.get("url") != hotspot["url"]:
            status = {}
        state = status.get("error") or ("Connected" if status.get("last_ok") else "Waiting for first poll")
        room = f' / {e(status["ysf_room"])}' if status.get("ysf_room") and not status.get("error") else ""
        source_status.append(f"<span class='{'error' if status.get('error') else ''}'><strong>{e(hotspot['label'])}</strong> · {e(state)}{room}</span>")
    tabs = []
    for code, label in (("exchanges", "Possible exchanges"), ("queue", "Activity queue"), ("saved", "Saved")):
        url = "/?" + urllib.parse.urlencode({"view": code, "hotspot": selected, "mode": mode, "clock": clock})
        tabs.append(f"<a class='{'active' if view == code else ''}' href='{e(url)}'>{label}</a>")
    clocks = []
    for code, label in (("local", "Local"), ("utc", "UTC")):
        url = "/?" + urllib.parse.urlencode({"view": view, "hotspot": selected, "mode": mode, "clock": code})
        clocks.append(f"<a class='{'active' if clock == code else ''}' href='{e(url)}'>{label}</a>")
    hotspot_options = option("", selected, "All hotspots") + "".join(option(item["id"], selected, item["label"]) for item in hotspots)
    mode_options = option("", mode, "All modes") + "".join(option(item, mode) for item in MODE_SPECS)
    summary = "".join(f"<span><strong>{count or 0}</strong>{label}</span>" for count, label in zip(counts, ("in queue", "possible exchanges", "need QRZ check", "saved")))
    page = [f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>Hotspot Logger</title>{page_styles(source)}</head>
<body><main class='shell'><header class='site-header'><div><h1>{BRAND}</h1><span class='brand-kicker'>{e(settings["station_callsign"])} / Contact review</span></div>
<nav class='header-actions' aria-label='Page actions'><a class='linkbtn secondary' href='/settings'>Settings</a><a class='linkbtn secondary' href='{e("/?" + urllib.parse.urlencode({"view": view, "hotspot": selected, "mode": mode, "clock": clock}))}'>Refresh</a><a class='linkbtn secondary' href='/export.adi'>ADIF export</a><a class='linkbtn danger' href='{e("/clear?" + urllib.parse.urlencode({"hotspot": selected}))}'>Clear queue</a></nav></header>
<div class='source-strip'>{"".join(source_status)}</div><div class='summary-line'>{summary}</div>
<div class='toolbar'><nav class='tabs' aria-label='Activity views'>{"".join(tabs)}</nav><div class='toolbar-controls'><nav class='clock-toggle' aria-label='Displayed time'>{"".join(clocks)}</nav><form method='get' action='/' class='filters'><input type='hidden' name='view' value='{view}'><input type='hidden' name='clock' value='{clock}'><select name='hotspot' aria-label='Hotspot'>{hotspot_options}</select><select name='mode' aria-label='Mode'>{mode_options}</select><button class='secondary'>Apply</button></form></div></div>
<div class='table-wrap'><table><thead><tr><th>{'Local time' if clock == 'local' else 'UTC time'}</th><th>Station</th><th>Hotspot</th><th>Mode</th><th>Destination</th><th>Status</th><th>Actions</th></tr></thead><tbody>"""]
    for row in entries:
        hotspot = contact_hotspot(row, settings)
        if row["log_status"] == "pending":
            label, state = "Check QRZ result", "pending"
        elif row["logged_at"]:
            label, state = ("Uploaded to QRZ" if row["log_status"] in ("qrz", "qrz_manual") else "Saved for ADIF"), "saved"
        elif row["exchange_pattern"]:
            label, state = "Possible exchange", "possible"
        else:
            label, state = "Heard only", ""
        evidence = f"<span class='small'>{e(row['exchange_pattern'])}</span>" if row["exchange_pattern"] and not row["logged_at"] else ""
        target_detail = f"<span class='small'>{e(row['target'])}</span>" if row["ysf_room"] else ""
        shown_time, shown_date, shown_zone = display_timestamp(row["heard_utc"], settings["display_timezone"], clock)
        time_label = "Local time" if clock == "local" else "UTC time"
        page.append(f"""<tr><td data-label='{time_label}'><div>{e(shown_time)}<span class='small'>{e(shown_date)} · {e(shown_zone)}</span></div></td>
<td data-label='Station'><div><span class='call'>{e(row["call"])}</span><span class='small'>{e(row["direction"])} · {e(row["duration"])} s</span></div></td>
<td data-label='Hotspot'>{e(hotspot["label"])}</td><td data-label='Mode'><span class='mode'>{e(row["mode"])}</span></td>
<td data-label='Destination'><div>{e(row["ysf_room"] or row["target"] or "—")}{target_detail}</div></td>
<td data-label='Status'><div><span class='state {state}'>{label}</span>{evidence}</div></td>
<td data-label='Actions'><div class='row-actions'><a href='/review?id={e(row["id"])}'>{'Open' if row["logged_at"] and row["log_status"] != "pending" else 'Review'}</a><a class='delete' href='/delete?id={e(row["id"])}'>Delete</a></div></td></tr>""")
    if not entries:
        message = "No possible exchanges detected. Activity queue includes heard stations you can review manually." if view == "exchanges" else ("No saved contacts in this view." if view == "saved" else "No queued activity in this view.")
        page.append(f"<tr><td colspan='7' class='empty'>{message}</td></tr>")
    page.append(f"""</tbody></table></div><p class='context'>A/B/A and B/A/B timing can suggest an exchange involving your RF callsign. It is not a confirmed QSO. Only you decide what to log.</p>
{page_footer(f'Latest {ACTIVITY_LIMIT} entries in this view · Times {settings["display_timezone"] if clock == "local" else "UTC"}')}</main></body></html>""")
    return "".join(page)

def removal_page(settings, row=None, count=0, hotspot=None):
    e = html.escape
    action = "/delete" if row is not None else "/clear"
    title = f"Delete {e(row['call'])} from logger?" if row is not None else f"Clear {count} queued contacts?"
    explanation = ("This deletes the local entry and its ADIF copy. The same WPSD record will stay removed."
                   if row is not None else "This clears all unlogged contacts. Saved contacts and entries awaiting a QRZ check are kept.")
    if row is None:
        explanation += f" Scope: {e(hotspot['label']) if hotspot else 'all hotspots'}."
    notice = ("<p class='notice'>This does not delete a contact from QRZ. Use Delete in your QRZ logbook to remove an uploaded contact.</p>"
              if row is not None and row['log_status'] in ('qrz', 'qrz_manual', 'pending') else "")
    entry = f"<input type='hidden' name='id' value='{e(row['id'])}'>" if row is not None else ""
    if hotspot:
        entry += f"<input type='hidden' name='hotspot' value='{e(hotspot['id'])}'>"
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'><title>{title}</title>{page_styles(settings)}</head>
<body><div class='setup-shell'><section class='setup-card'><h1>{title}</h1><p>{explanation}</p>{notice}
<form method='post' action='{action}'><input type='hidden' name='csrf' value='{form_token(settings)}'><input type='hidden' name='confirm' value='yes'>{entry}
<div class='actions'><a class='linkbtn secondary' href='/'>Cancel</a><button class='danger' type='submit'>{'Delete entry' if row is not None else 'Clear queue'}</button></div></form></section>{page_footer()}</div></body></html>"""


class Handler(BaseHTTPRequestHandler):
    def setup(self):
        super().setup()
        self.connection.settimeout(15)

    def authenticated(self, settings):
        auth = self.headers.get("Authorization", "")
        if not auth.startswith("Basic "):
            return False
        try:
            decoded = base64.b64decode(auth[6:], validate=True).decode("utf-8")
            username, password = decoded.split(":", 1)
            return (hmac.compare_digest(username.upper(), settings["station_callsign"])
                    and password_matches(password, settings["password_hash"]))
        except (ValueError, UnicodeError, TypeError):
            return False

    def send_page(self, code, content, content_type="text/html; charset=utf-8", headers=None):
        body = content.encode("utf-8") if isinstance(content, str) else content
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("X-Frame-Options", "DENY")
        self.send_header("Referrer-Policy", "no-referrer")
        scripts = re.findall(r"<script>(.*?)</script>", content, re.S) if isinstance(content, str) else []
        hashes = " ".join("'sha256-" + base64.b64encode(hashlib.sha256(script.encode()).digest()).decode() + "'" for script in scripts)
        script_policy = f"; script-src {hashes}" if hashes else ""
        self.send_header("Content-Security-Policy", "default-src 'none'; img-src 'self'; style-src 'unsafe-inline'; form-action 'self'; base-uri 'none'; frame-ancestors 'none'" + script_policy)
        for key, val in (headers or {}).items():
            self.send_header(key, val)
        self.end_headers()
        self.wfile.write(body)

    def redirect(self, location):
        self.send_page(303, b"", headers={"Location": location})

    def challenge(self):
        self.send_page(401, "Sign in with your station callsign and web password", "text/plain",
                       {"WWW-Authenticate": 'Basic realm="Hotspot Logger", charset="UTF-8"'})

    def read_form(self):
        length = int(self.headers.get("Content-Length", "0"))
        if not 0 < length <= 16384:
            raise ValueError("Form too large")
        body = self.rfile.read(length)
        if len(body) != length:
            raise ValueError("Incomplete form. Reload and try again.")
        parsed = urllib.parse.parse_qs(body.decode("utf-8"), keep_blank_values=True, max_num_fields=256, errors="strict")
        return {key: values[0] if key in ("password", "password_confirm") else values[0].strip()
                for key, values in parsed.items()}

    def do_GET(self):
        path = urllib.parse.urlsplit(self.path).path
        if path == "/assets/hotspot-logger.png":
            return self.send_page(200, (Path(__file__).parent / "assets" / "hotspot-logger.png").read_bytes(), "image/png")
        settings = get_settings()
        ready = settings_ready(settings)
        if path == "/healthz":
            state = "setup" if not ready else ("ok" if STATUS["last_ok"] and not STATUS["error"] else "degraded")
            payload = json.dumps({"status": state, "version": VERSION, "configured": ready,
                                  "wpsd_connected": bool(STATUS["last_ok"]),
                                  "poll_error": bool(STATUS["error"])}).encode()
            return self.send_page(200, payload, "application/json")
        if not ready:
            if path != "/setup":
                return self.redirect("/setup")
            return self.send_page(200, setup_page(settings))
        if not self.authenticated(settings):
            return self.challenge()
        if path == "/setup":
            return self.redirect("/settings")
        if path == "/settings":
            saved = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("saved") == ["1"]
            return self.send_page(200, setup_page(settings, edit=True, saved=saved))
        if path == "/review":
            identity = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
            with db() as cx:
                row = cx.execute("SELECT * FROM heard WHERE id=?", (identity,)).fetchone()
            if not row:
                return self.send_page(404, "Entry no longer available", "text/plain")
            return self.send_page(200, review_page(settings, row))
        if path == "/delete":
            identity = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("id", [""])[0]
            with db() as cx:
                row = cx.execute("SELECT * FROM heard WHERE id=?", (identity,)).fetchone()
            if row is None:
                return self.send_page(404, "Entry no longer available", "text/plain")
            return self.send_page(200, removal_page(settings, row=row))
        if path == "/clear":
            identity = urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query).get("hotspot", [""])[0]
            hotspot = next((item for item in configured_hotspots(settings) if item["id"] == identity), None)
            if identity and not hotspot:
                return self.send_page(404, "Hotspot no longer available", "text/plain")
            with db() as cx:
                count = cx.execute("SELECT COUNT(*) FROM heard WHERE logged_at IS NULL AND COALESCE(log_status,'') != 'pending' AND (?='' OR hotspot_id=?)", (identity, identity)).fetchone()[0]
            return self.send_page(200, removal_page(settings, count=count, hotspot=hotspot))
        if path == "/export.adi":
            with db() as cx:
                entries = cx.execute("SELECT log_adif FROM heard WHERE log_adif IS NOT NULL AND logged_at IS NOT NULL AND log_status IN ('save','qrz','qrz_manual') ORDER BY logged_at").fetchall()
            data = "ADIF Export from Hotspot Logger\n<ADIF_VER:5>3.1.7<EOH>\n" + "\n".join(entry[0] for entry in entries) + "\n"
            return self.send_page(200, data, "application/octet-stream",
                                  {"Content-Disposition": 'attachment; filename="hotspot-logger.adi"'})
        if path != "/":
            return self.send_page(404, "Not found", "text/plain")
        return self.send_page(200, dashboard_page(settings, urllib.parse.parse_qs(urllib.parse.urlsplit(self.path).query)))

    def do_POST(self):
        path = urllib.parse.urlsplit(self.path).path
        settings = get_settings()
        ready = settings_ready(settings)
        if path == "/setup" and not ready:
            form = {}
            try:
                form = self.read_form()
                if not hmac.compare_digest(form.get("csrf", "").encode(), form_token(bootstrap=True).encode()):
                    return self.send_page(403, "Invalid form token", "text/plain")
                save_configuration(form, initial=True)
                return self.redirect("/")
            except (ValueError, UnicodeError) as exc:
                draft = dict(settings)
                draft.update({key: form.get(key, draft.get(key, "")) for key in DEFAULTS
                              if key not in ("password_hash", "csrf_secret", "qrz_api_key", "hotspots")})
                try:
                    draft["hotspots"] = json.dumps(hotspot_form_values(form, settings))
                except ValueError:
                    pass
                return self.send_page(400, setup_page(draft, error=str(exc)))
        if not ready:
            return self.redirect("/setup")
        if not self.authenticated(settings):
            return self.challenge()
        if path not in ("/settings", "/log", "/resolve", "/delete", "/clear"):
            return self.send_page(404, "Not found", "text/plain")
        form = {}
        try:
            form = self.read_form()
            if not hmac.compare_digest(form.get("csrf", "").encode(), form_token(settings).encode()):
                return self.send_page(403, "Invalid form token", "text/plain")
            if path == "/settings":
                save_configuration(form, initial=False)
                return self.redirect("/settings?saved=1")
            if path in ("/delete", "/clear"):
                if form.get("confirm") != "yes":
                    raise ValueError("Confirm deletion on the logger page")
                with WRITE_LOCK, db() as cx:
                    if path == "/delete":
                        row = cx.execute("SELECT id FROM heard WHERE id=?", (form.get("id", ""),)).fetchone()
                        if row is None:
                            raise ValueError("Entry no longer available")
                        cx.execute("INSERT OR IGNORE INTO removed(id) VALUES(?)", (row['id'],))
                        cx.execute("DELETE FROM heard WHERE id=?", (row['id'],))
                    else:
                        hotspot = form.get("hotspot", "")
                        if hotspot and hotspot not in {item["id"] for item in configured_hotspots(settings)}:
                            raise ValueError("Hotspot no longer available")
                        cx.execute("INSERT OR IGNORE INTO removed(id) SELECT id FROM heard WHERE logged_at IS NULL AND COALESCE(log_status,'') != 'pending' AND (?='' OR hotspot_id=?)", (hotspot, hotspot))
                        cx.execute("DELETE FROM heard WHERE logged_at IS NULL AND COALESCE(log_status,'') != 'pending' AND (?='' OR hotspot_id=?)", (hotspot, hotspot))
                    cx.execute("DELETE FROM activity WHERE id IN (SELECT id FROM removed)")
                return self.redirect("/")
            if path == "/resolve":
                resolution = form.get("resolution", "")
                if resolution not in ("found", "retry"):
                    raise ValueError("Unknown resolution")
                with WRITE_LOCK, db() as cx:
                    row = cx.execute("SELECT * FROM heard WHERE id=?", (form.get("id", ""),)).fetchone()
                    if not row or row["log_status"] != "pending":
                        raise ValueError("Entry is not awaiting reconciliation")
                    if resolution == "found":
                        cx.execute("UPDATE heard SET log_status='qrz_manual' WHERE id=?", (row["id"],))
                    else:
                        cx.execute("UPDATE heard SET logged_at=NULL, log_status=NULL, log_adif=NULL WHERE id=?", (row["id"],))
                return self.redirect("/")
            call = form.get("call", "").upper()
            station = settings["station_callsign"]
            if not CALL.fullmatch(call) or call.split("/")[0] == station.split("/")[0]:
                raise ValueError("Check contact callsign")
            when = dt.datetime.fromisoformat(form.get("when", ""))
            when = when.replace(tzinfo=UTC) if when.tzinfo is None else when.astimezone(UTC)
            if not (dt.datetime.now(UTC)-dt.timedelta(days=3650) <= when <= dt.datetime.now(UTC)+dt.timedelta(days=1)):
                raise ValueError("Check UTC time")
            freq = form.get("freq", "")
            band = form.get("band", "").lower()
            if band not in ("10m", "6m", "2m", "70cm", "33cm", "23cm"):
                raise ValueError("Choose a supported band")
            if band_for(freq) != band:
                raise ValueError("Frequency and band disagree")
            action = form.get("action", "")
            qrz_key = settings["qrz_api_key"]
            if action not in ("save", "qrz") or (action == "qrz" and not qrz_key):
                raise ValueError("QRZ key is not configured")
            with WRITE_LOCK:
                with db() as cx:
                    row = cx.execute("SELECT * FROM heard WHERE id=?", (form.get("id", ""),)).fetchone()
                    if not row:
                        raise ValueError("Entry no longer available")
                    if row["logged_at"]:
                        raise ValueError("Already logged here")
                    adif = make_adif(call, form.get("mode", row["mode"]), when, band, freq, row["target"],
                                     (form.get("comment") or contact_comment(row, settings))[:200], station,
                                     propagation=form.get("prop_mode", default_propagation(row)))
                    cx.execute("UPDATE heard SET logged_at=?, log_status=?, log_adif=?, call=?, mode=?, heard_utc=? WHERE id=? AND logged_at IS NULL",
                        (dt.datetime.now(UTC).isoformat(), "pending" if action == "qrz" else "save", adif,
                         call, form.get("mode", row["mode"]), when.isoformat(), row["id"]))
                if action == "qrz":
                    try:
                        logid = qrz_insert(adif, qrz_key, station)
                    except ValueError:
                        with db() as cx:
                            cx.execute("UPDATE heard SET logged_at=NULL, log_status=NULL, log_adif=NULL WHERE id=?", (row["id"],))
                        raise
                    with db() as cx:
                        cx.execute("UPDATE heard SET qrz_logid=?, log_adif=?, log_status='qrz' WHERE id=?",
                                   (logid, adif, row["id"]))
            return self.redirect("/")
        except (ValueError, OverflowError, urllib.error.URLError, TimeoutError, QRZUncertainError) as exc:
            if path == "/settings":
                draft = dict(settings)
                draft.update({key: form.get(key, draft.get(key, "")) for key in DEFAULTS
                              if key not in ("password_hash", "csrf_secret", "qrz_api_key", "hotspots")})
                try:
                    draft["hotspots"] = json.dumps(hotspot_form_values(form, settings))
                except ValueError:
                    pass
                return self.send_page(400, setup_page(draft, edit=True, error=str(exc)))
            return self.send_page(400, f"<!doctype html><meta name='viewport' content='width=device-width,initial-scale=1'>{CSS}<div class='setup-shell'><h1>Could not save</h1><p>{html.escape(str(exc))}</p><p>If QRZ timed out, check your QRZ logbook before trying again.</p><a href='/'>Back</a>{page_footer()}</div>")


if __name__ == "__main__":
    init_db()
    threading.Thread(target=poll_loop, daemon=True).start()
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()

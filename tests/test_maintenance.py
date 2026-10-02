import io
from pathlib import Path
import sqlite3
import tarfile
import tempfile
import unittest

import maintenance


class MaintenanceTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.addCleanup(self.folder.cleanup)
        self.database = Path(self.folder.name) / "logger.sqlite"
        self.connection = sqlite3.connect(self.database)
        self.addCleanup(self.connection.close)
        self.connection.executescript("""PRAGMA journal_mode=WAL;
            CREATE TABLE settings(key TEXT PRIMARY KEY,value TEXT NOT NULL);
            CREATE TABLE heard(id TEXT PRIMARY KEY,log_adif TEXT,call TEXT,mode TEXT,target TEXT,
                direction TEXT,heard_utc TEXT,duration TEXT,raw TEXT,first_seen TEXT,
                logged_at TEXT,qrz_logid TEXT,log_status TEXT);
            CREATE TABLE removed(id TEXT PRIMARY KEY);
            INSERT INTO settings VALUES('station_callsign','N0CALL'),('qrz_api_key','TEST-KEY'),('password_hash','TEST-HASH');
            INSERT INTO heard(id,log_adif) VALUES('saved','<CALL:5>W1ABC<EOR>');
            INSERT INTO removed VALUES('deleted');""")
        self.connection.commit()

    def archive(self, name="logger.sqlite", data=b"not a database", symlink=False):
        output = io.BytesIO()
        with tarfile.open(fileobj=output, mode="w:gz") as archive:
            member = tarfile.TarInfo(name)
            if symlink:
                member.type = tarfile.SYMTYPE
                member.linkname = "/etc/passwd"
                archive.addfile(member)
            else:
                member.size = len(data)
                archive.addfile(member, io.BytesIO(data))
        output.seek(0)
        return output

    def test_live_wal_backup_and_restore_preserve_settings_contacts_and_removed_ids(self):
        self.assertTrue(Path(str(self.database) + "-wal").exists())
        output = io.BytesIO()
        maintenance.backup(self.database, output)
        self.connection.execute("UPDATE settings SET value='CHANGED' WHERE key='qrz_api_key'")
        self.connection.execute("DELETE FROM heard")
        self.connection.commit()
        output.seek(0)
        staged = maintenance.stage_restore(self.database, output)
        self.assertEqual(staged.stat().st_mode & 0o777, 0o600)
        # Staging validates without touching the live database.
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM heard").fetchone()[0], 0)
        self.connection.close()
        Path(str(self.database) + "-wal").write_bytes(b"stale WAL")
        Path(str(self.database) + "-shm").write_bytes(b"stale shared memory")
        maintenance.restore(self.database, str(staged))
        self.assertFalse(staged.exists())
        self.assertFalse(Path(str(self.database) + "-wal").exists())
        self.assertFalse(Path(str(self.database) + "-shm").exists())
        with sqlite3.connect(self.database) as restored:
            settings = dict(restored.execute("SELECT key,value FROM settings"))
            self.assertEqual(settings["qrz_api_key"], "TEST-KEY")
            self.assertEqual(settings["password_hash"], "TEST-HASH")
            self.assertEqual(restored.execute("SELECT log_adif FROM heard").fetchone()[0], "<CALL:5>W1ABC<EOR>")
            self.assertEqual(restored.execute("SELECT id FROM removed").fetchone()[0], "deleted")
        self.assertEqual(self.database.stat().st_mode & 0o777, 0o600)

    def test_invalid_archives_leave_live_data_and_no_staged_files(self):
        for name, data, symlink in (("../../logger.sqlite", b"bad", False),
                                    ("logger.sqlite", b"bad", True), ("logger.sqlite", b"bad", False)):
            with self.subTest(name=name, symlink=symlink):
                with self.assertRaises((ValueError, sqlite3.Error)):
                    maintenance.stage_restore(self.database, self.archive(name, data, symlink))
                self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM heard").fetchone()[0], 1)
                self.assertEqual(list(self.database.parent.glob(".restore-*.sqlite")), [])

    def test_other_sqlite_databases_are_rejected(self):
        other = self.database.parent / "other.sqlite"
        with sqlite3.connect(other) as cx:
            cx.execute("CREATE TABLE unrelated(id TEXT)")
        with self.assertRaisesRegex(ValueError, "not a Hotspot Logger"):
            maintenance.stage_restore(self.database, self.archive(data=other.read_bytes()))

    def test_restore_rejects_arbitrary_paths(self):
        with self.assertRaisesRegex(ValueError, "Invalid staged"):
            maintenance.restore(self.database, str(self.database))
        self.assertEqual(self.connection.execute("SELECT COUNT(*) FROM heard").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()

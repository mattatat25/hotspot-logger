"""Consistent database backups and validated restores for the Docker scripts."""
import argparse
import contextlib
import os
from pathlib import Path
import re
import secrets
import shutil
import sqlite3
import sys
import tarfile
import tempfile


def check_database(path):
    with contextlib.closing(sqlite3.connect(path.resolve().as_uri() + "?mode=ro", uri=True)) as cx:
        if cx.execute("PRAGMA quick_check").fetchall() != [("ok",)]:
            raise ValueError("The backup failed the SQLite integrity check")
        tables = {row[0] for row in cx.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        if not {"heard", "settings"} <= tables:
            raise ValueError("This is not a Hotspot Logger database")
        required = {
            "settings": {"key", "value"},
            "heard": {"id", "call", "mode", "target", "direction", "heard_utc", "duration",
                      "raw", "first_seen", "logged_at", "qrz_logid", "log_adif", "log_status"},
        }
        for table, columns in required.items():
            found = {row[1] for row in cx.execute(f"PRAGMA table_info({table})")}
            if not columns <= found:
                raise ValueError(f"The backup is missing required {table} columns")


def backup(database, output):
    with tempfile.TemporaryDirectory() as folder:
        snapshot = Path(folder) / "logger.sqlite"
        with contextlib.closing(sqlite3.connect(database.resolve().as_uri() + "?mode=ro", uri=True)) as source:
            with contextlib.closing(sqlite3.connect(snapshot)) as destination:
                source.backup(destination)
        snapshot.chmod(0o600)
        check_database(snapshot)
        with tarfile.open(fileobj=output, mode="w|gz") as archive:
            archive.add(snapshot, arcname="logger.sqlite")


def stage_restore(database, input_stream):
    staged = database.parent / (".restore-" + secrets.token_hex(8) + ".sqlite")
    try:
        with tarfile.open(fileobj=input_stream, mode="r|gz") as archive:
            members = 0
            for member in archive:
                members += 1
                if members != 1 or member.name != "logger.sqlite" or not member.isfile():
                    raise ValueError("Expected one regular file named logger.sqlite in the backup")
                if not 0 < member.size <= 512 * 1024 * 1024:
                    raise ValueError("Backup database must be between 1 byte and 512 MB")
                with staged.open("xb") as destination, archive.extractfile(member) as source:
                    staged.chmod(0o600)
                    shutil.copyfileobj(source, destination)
            if members != 1:
                raise ValueError("The backup archive is empty")
        check_database(staged)
        return staged
    except Exception:
        staged.unlink(missing_ok=True)
        raise


def staged_path(database, name):
    staged = Path(name)
    if staged.parent != database.parent or not re.fullmatch(r"\.restore-[0-9a-f]{16}\.sqlite", staged.name):
        raise ValueError("Invalid staged backup path")
    return staged


def restore(database, name):
    staged = staged_path(database, name)
    check_database(staged)
    # The service must be stopped so no connection retains the old database.
    for suffix in ("-wal", "-shm"):
        Path(str(database) + suffix).unlink(missing_ok=True)
    os.replace(staged, database)
    database.chmod(0o600)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("backup", "stage-restore", "restore", "discard-staged"))
    parser.add_argument("staged", nargs="?")
    args = parser.parse_args()
    database = Path(os.getenv("DB_PATH", "/data/logger.sqlite")).absolute()
    try:
        if args.action == "backup":
            backup(database, sys.stdout.buffer)
        elif args.action == "stage-restore":
            print(stage_restore(database, sys.stdin.buffer))
        elif not args.staged:
            parser.error("a staged backup path is required")
        elif args.action == "restore":
            restore(database, args.staged)
        else:
            staged_path(database, args.staged).unlink(missing_ok=True)
    except (OSError, ValueError, sqlite3.Error, tarfile.TarError) as exc:
        print(f"{args.action} failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

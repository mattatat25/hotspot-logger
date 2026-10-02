# Contributing

Created by KF0WSS. This is a small hobby project; focused fixes and clear bug reports are welcome.

## Run locally

Use Python 3.12. No Python packages are required.

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh scripts/*.sh
```

To try the GUI with a disposable database:

```bash
DB_PATH=/tmp/wpsd-dev.sqlite PORT=8787 python3 app.py
```

Open `http://127.0.0.1:8787` and complete the setup form. Use a test callsign and leave the QRZ key blank. These process options are for development; normal users configure the application in the GUI.

## Changes

- Read WPSD without modifying its files or settings.
- Keep QRZ uploads under explicit operator control.
- Preserve stored contacts, removed IDs, and settings during upgrades.
- Add focused tests for parsing, ADIF, database migrations, or submission-state changes.
- Update the relevant guide when behavior changes.
- Keep docs concrete: describe what a user enters, clicks, or should expect.

Do not commit databases, backups, keys, or real API responses. Test fixtures use sample callsigns and dummy keys.

The GitHub workflow checks amd64 and arm64 containers, browser layouts, and backup/restore. It does not submit anything to QRZ. See [Testing](docs/TESTING.md) for coverage and the real-radio checks.

## Bug reports

Use the repository's bug-report form. Include versions, steps, the actual result, and what you expected. When an API sample is needed, share a redacted single object.

[Release instructions](docs/RELEASING.md)

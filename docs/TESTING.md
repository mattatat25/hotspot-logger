# Testing

The Python tests use the standard library and run without WPSD hardware or a QRZ subscription:

```bash
python3 -m unittest discover -s tests -v
bash -n setup.sh scripts/*.sh
```

Tests use temporary databases and dummy credentials. QRZ responses are mocked; no real contact is submitted.

## Automated checks

The GitHub **Test** workflow runs on both amd64 and arm64 Linux. It checks:

- Feed parsing, mode mapping, room capture, and possible exchanges.
- Setup, authentication, form tokens, and concurrent submissions.
- QRZ success, rejection, and uncertain-result handling.
- ADIF export, contact deletion, and database migrations.
- Backup permissions, restore, and rejection of invalid archives.
- Startup through `setup.sh` and the container health check.
- Full PNG data, so a valid header alone cannot hide a damaged logo.
- Desktop and phone browser layouts, setup controls, and the served logo.

The ARM64 job checks the same architecture used by a Pi with a 64-bit OS. It does not measure Pi performance or test SD-card reliability. The automatic Docker package installer needs administrator access and is separate from the tests that use an existing Docker installation.

## Before a release

Compare fresh activity with a real WPSD dashboard. Check a contact you actually worked, verify its fields in QRZ, and inspect an ADIF export. Exercise the page on a desktop and phone, including the WPSD theme you use.

WPSD builds and browser behavior can differ from the fixtures. Report the software versions with any mismatch.

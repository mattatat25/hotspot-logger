# Changelog

## 0.8.0-beta.4

- Update existing installations from the public `main` branch even when the local branch has an older name.
- Add exact recovery steps for early beta checkouts that still track the removed review branch.
- Show the latest 50 activity entries instead of 100.

## 0.8.0-beta.3

- Make possible-exchange detection tolerant of WPSD direction, duration, talkgroup, timeslot, and DG-ID formatting differences.
- Ignore network echoes and short bursts without erasing an otherwise valid A/B/A sequence.

## 0.8.0-beta.2

- Add a guided Docker install for Ubuntu, Debian, and Raspberry Pi OS 64-bit.
- Print the browser address after the logger passes its startup check.
- Back up before updates and stop if the checkout has local changes.
- Support Docker commands that need sudo in setup and maintenance scripts.
- Include time-zone data for older feeds using local timestamps.
- Keep oversized, conflicting, or incomplete QRZ responses pending for manual checking.
- Skip timestamps at the calendar limits instead of failing a whole poll.
- Check the complete logo image and test both amd64 and arm64 containers.
- Rewrite the installation, security, and project guides for the public beta.


## 0.8.0-beta.1

- Rename the application to Hotspot Logger, with an original antenna/contact-list logo and KF0WSS credit.
- Mark the footer and documentation as Beta and identify the project as independent of WPSD and QRZ.
- Prevent competing first-run submissions from replacing completed setup.
- Restrict database and SQLite sidecar permissions to the application account.
- Treat QRZ `AUTH` responses as rejected requests so the entry can be corrected.
- Reject invalid form tokens cleanly and limit incomplete request reads.
- Skip timestamps outside the supported date range and correctly convert offset contact times to UTC.
- Validate backup table columns before replacing the live database.
- Keep existing Docker service names, volume selection, settings keys, and contact IDs for upgrade compatibility.
- Add regression coverage for setup, QRZ responses, timestamps, and database permissions.

## 0.7.0 — 2026-10-01

- Added KF0WSS's creator mark to the README and app pages.
- Rewrote the installation guide for a fresh Ubuntu Server VM and desktop browser access; added daily-use, backup/restore, ZIP-update, and release guides.
- Added GitHub issue and pull-request templates and a container setup/backup/restore smoke test.
- Kept ambiguous QRZ responses pending until checked, and excluded rejected or unresolved submissions from ADIF export.
- Preserved reviewed callsign, time, and mode in saved rows and filters.
- Added consistent private backups and a restore command that validates the database before stopping the service.
- Corrected reset instructions for the named Docker volume and the eight-character password minimum.
- Preserved spaces in passwords and checked malformed hotspot ports and ADIF frequency/text formats.

## 0.6.0 — 2026-10-01

- Added multiple GUI-configured hotspots with separate names, addresses, frequencies, connection status, colors, and record identities.
- Replaced the large dashboard cards with a compact desktop table and labeled mobile rows, source/mode filters, and a dedicated contact review page.
- Added D-Star, P25, NXDN, legacy M17, and FM voice normalization with valid ADIF mappings; P25/NXDN protocol names remain in comments.
- Captured YSF room names from the public WPSD status panel for fresh activity, without assigning current rooms to old records.
- Added possible A/B/A and B/A/B exchange evidence using the station's RF activity, scoped by hotspot and channel. Logging remains manual.
- Reduced the password minimum to eight characters; existing passwords remain valid.
- Made propagation editable, defaulting network contacts to Internet-assisted, and documented QRZ confirmation and award rules.
- Scoped Clear queue to the selected hotspot and added database migration coverage for existing installations.

## 0.5.0 — 2026-10-01

- Added confirmed deletion for individual queued and saved contacts, including their local ADIF copies.
- Added Clear queue for all unlogged contacts while retaining saved contacts and uncertain QRZ submissions.
- Persist removed record IDs so repeat WPSD polls do not restore deleted entries.
- Added automatic WPSD theme matching from the configured hotspot's public stylesheet, refreshed every five minutes.
- Added a GUI theme preference and color-sync status, with a default-palette fallback.

## 0.4.2 — 2026-10-01

- Removed the redundant Origin/Referer requirement that blocked first-run setup in some LAN browsers.
- Retained cryptographic CSRF tokens on setup, settings, and logging forms.

## 0.4.1 — 2026-10-01

- Made first-run setup reachable from desktop and phone browsers on a trusted LAN by default.
- Fixed same-origin form validation for LAN browsers that suppress Origin and Referer headers.
- Updated setup output and deployment documentation for headless Ubuntu servers.

## 0.4.0 — 2026-09-24

- Replaced `.env` onboarding with a first-run web setup wizard and authenticated Settings page.
- Added field-by-field directions and official WPSD/QRZ help links inside setup.
- Store the web password as a salted PBKDF2 hash and keep configuration in SQLite.
- Switched Docker persistence to a named volume and simplified setup and backups.

## 0.3.0 — 2026-09-24

- Added a desktop dashboard with queue totals and a separate recently handled panel.
- Kept the review flow responsive for tablets and phones.
- Expanded the QSO editor to four columns on wide screens and one column on phones.

## 0.2.0 — 2026-09-24

- Added current and legacy WPSD Last Heard field support, including `time_utc` and `src`.
- Added a mobile first review UI and one tap logging when frequency is configured.
- Added explicit QRZ timeout reconciliation instead of automatic retries.
- Added unauthenticated container health endpoint with limited status data.
- Added guided setup, backup/update scripts, hardened Docker Compose, documentation, and GitHub Actions checks.
- Added QRZ rejection parsing and response size limits.

## 0.1.0 — 2026-09-24

- Initial WPSD polling, QRZ insert, SQLite state, and ADIF export.

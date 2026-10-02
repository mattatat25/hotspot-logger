# Release a version

1. Update `VERSION` in `app.py`, the README version, and `CHANGELOG.md`.
2. Run the checks in [Testing](TESTING.md) and require the GitHub **Test** workflow to pass.
3. Check the GUI on a desktop and phone. Compare fresh WPSD activity and verify a real contact in QRZ.
4. Merge the reviewed pull request.
5. Create a GitHub release from that commit, with a matching tag such as `v0.8.0-beta.2`.

Use **Hotspot Logger 0.8.0-beta.2** as the release title and describe the user-visible changes. Keep **Set as a pre-release** enabled while the app is in beta. GitHub supplies source ZIP and tar archives automatically.

## Repository settings

- Name: `hotspot-logger`
- Description: `Review digital voice contacts from WPSD hotspots and save them to QRZ Logbook or ADIF. Created by KF0WSS.`
- Topics: `amateur-radio`, `digital-voice`, `contact-logging`, `wpsd`, `qrz`, `raspberry-pi`, `docker`

Before publishing a release, check the current tree and new commits for credentials or personal data. Confirm that anonymous visitors can open the README and clone the repository.

Renaming the GitHub repository does not require renaming existing installation folders. Keep those folders and their Compose project names unchanged to preserve data-volume selection. See [updating an older installation](BACKUP-AND-UPDATES.md#updating-an-older-installation).

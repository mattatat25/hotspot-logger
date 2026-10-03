HOTSPOT LOGGER FOR WINDOWS
Created by KF0WSS
Version 0.8.0-beta.11

FIRST RUN

1. Keep this entire HotspotLogger folder together.
2. Double-click HotspotLogger.exe.
3. Your browser opens the setup page at http://127.0.0.1:8787.
4. Enter your callsign, hotspot details, logger password, and optional QRZ key in the browser.

Python, Docker, Git, and an .env file are not required.

If Windows SmartScreen displays "Windows protected your PC," first verify that this ZIP came from the project's GitHub Releases page and that its SHA-256 value matches SHA256SUMS.txt. Then select "More info," confirm the app is HotspotLogger.exe, and select "Run anyway." Do not disable Windows Security.

NETWORK ACCESS

The Windows beta accepts connections only from this computer by default. To use the logger from a phone or another computer, select "Allow other devices on my trusted network" in the launcher and apply the setting. Allow the app on Private networks if Windows Firewall asks. Do not allow it on public networks, and do not forward port 8787 through your router.

DATA AND BACKUPS

Closing the control window keeps Hotspot Logger running beside the Windows clock. Right-click the tray icon to open the logger, show the controls, restart, or exit. The control window also has an option to start Hotspot Logger automatically when you sign in to Windows.

Select "Open data folder" in the launcher. Settings and contacts are stored in logger.sqlite. Choose Exit from the tray icon before copying that file as a backup. Updating the program folder does not remove this data folder.

WINDOWS TRUST WARNING

This beta is not Authenticode-signed. Windows may show an unknown-publisher or SmartScreen warning even when the published SHA-256 checksum matches. Do not turn off Windows Security. Check the checksum, read SCAN-RESULT.txt, scan the extracted folder with Windows Security, and use only a package downloaded from this repository's Releases page.

Choose Exit from the tray icon when you want to stop Hotspot Logger completely.

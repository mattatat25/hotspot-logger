# Windows beta

The Windows beta is a portable 64-bit package. It does not install Python, Docker, Git, a Windows service, a browser extension, or an automatic updater.

## Download and start

1. Open the repository's **Releases** page.
2. Under the newest release, download `HotspotLogger-Windows-x64-0.8.0-beta.11.zip` from **Assets**. Do not download one of GitHub's automatic **Source code** files.
3. Extract the ZIP. Keep the entire `HotspotLogger` folder together.
4. Double-click `HotspotLogger.exe`.
5. The launcher opens `http://127.0.0.1:8787` in your browser. Complete the same browser setup used by Linux installations.

### If Windows shows a SmartScreen warning

This beta is not code-signed, so Windows may display **Windows protected your PC** the first time it runs. If you downloaded the ZIP from this repository's Releases page and its SHA-256 value matches `SHA256SUMS.txt`, select **More info**, confirm the app name is `HotspotLogger.exe`, then select **Run anyway**. Do not disable Microsoft Defender or SmartScreen.

The package is portable, but the data is not stored beside the executable. Settings, credentials, contacts, the launcher setting, and its log are kept in `%LOCALAPPDATA%\Hotspot Logger` so replacing the program folder does not erase them.

## Run in the background

Closing the control window leaves Hotspot Logger running in the notification area beside the Windows clock. Use the tray icon to open the logger, show the controls, restart the server, or exit completely.

To launch it automatically after signing in to Windows, open **Show controls**, select **Start Hotspot Logger when I sign in to Windows**, and apply the setting. Automatic starts stay in the tray and do not open a browser tab.

## Use it from another device

Windows listens only on the same computer by default. In the launcher:

1. Select **Allow other devices on my trusted network**.
2. Select **Apply network setting**.
3. If Windows Firewall asks, allow the app on **Private networks** only.
4. Open the LAN address shown by the launcher from your phone or another computer.

This setting does not make Internet exposure safe. Do not forward port 8787 through the router.

## Back up and update

Choose **Exit** from the tray icon, then copy `logger.sqlite` somewhere safe. To update, extract the newer package into a new folder and run its executable. It will use the existing data folder automatically. If automatic startup is enabled, open the new copy once and reapply that setting so Windows points to the new folder.

If the app does not start, open `%LOCALAPPDATA%\Hotspot Logger\hotspot-logger.log`. Do not post that file without reviewing it for private network details.

## Executable trust

The workflow builds an ordinary PyInstaller one-folder package. UPX compression, code obfuscation, self-update code, and a one-file self-extractor are not used. The workflow starts the packaged executable, checks its health endpoint, attempts a Microsoft Defender scan, records the scan result inside the package, and publishes a SHA-256 checksum with the artifact. A GitHub-hosted runner may have an unavailable Defender engine; `SCAN-RESULT.txt` says whether the scan completed.

Those checks do not make an unsigned executable trusted by Windows. This beta has no Authenticode signature, so SmartScreen may show **Unknown publisher** or block a low-reputation download. Do not disable Windows Security. Verify the checksum against `SHA256SUMS.txt` and use only release assets from this repository.

Future Windows releases may use consistent Authenticode signing or Microsoft Store distribution. Signing identifies the publisher and protects file integrity, but a new signing identity may still need time to build SmartScreen reputation.

# Troubleshooting

Run terminal commands from the folder containing `compose.yaml`.

## The page does not open from my desktop

Check the URL: `http://SERVER_IP:8787`. Do not use your desktop's `localhost` or the hotspot's IP.

On the server:

```bash
hostname -I
docker compose ps
docker compose logs --tail=100 logger
curl -sS http://127.0.0.1:8787/healthz
```

If the local health check works, check that the desktop and VM share the LAN, the VM uses bridged networking, and the address is correct. If the local check fails, read the container logs.

## Docker says permission denied or cannot connect

The setup, backup, restore, and update scripts use `sudo` for Docker when your account needs it. Run the scripts as your normal user. For a manual Docker command, add `sudo`, for example `sudo docker compose ps`.

If the daemon is stopped:

```bash
sudo systemctl start docker
bash setup.sh
```

For a missing Compose plugin or a conflicting container package, follow the [manual Docker installation instructions](INSTALL.md#manual-docker-installation). Setup does not replace an existing container runtime.

## Setup stops with a port conflict

Another application may already use port 8787. Run `sudo ss -ltnp 'sport = :8787'` to identify it. Stop the conflicting service only if you know it is safe, or run the logger on a separate host.

## Git asks for credentials

Check that the clone URL is `https://github.com/mattatat25/hotspot-logger.git`. Public source downloads do not need a GitHub account. If you have access to a private preview, use a GitHub SSH key or token; an account password will not authenticate Git.

## Login keeps failing after changing Settings

The username is your **station callsign**. If you changed the callsign or password, enter the new values. Browsers may cache Basic authentication; close the browser or try a private window.

## WPSD polling fails

In **Settings**, check that each source uses its own hotspot IP followed by `/api/`. Reserve IP addresses instead of relying on `.local` names inside Docker.

Test the API from Ubuntu, replacing the sample address:

```bash
curl -sS 'http://192.168.1.50/api/?limit=3&names=false&country=false'
```

Then test from the container:

```bash
docker compose exec -T logger python -c "import urllib.request; print(urllib.request.urlopen('http://192.168.1.50/api/?limit=1', timeout=5).status)"
```

A failed source does not stop the other hotspots. The page shows the failing source's label.

## WPSD connects but no callers appear

- Clear the hotspot and mode filters, then select **Activity queue**.
- Check that WPSD reports a supported voice mode and a resolved callsign.
- Your own callsign is excluded from the contact queue.
- The feed needs a complete date and time; a time of day alone is insufficient.

If the page reports unrecognized rows, compare a redacted sample with [WPSD compatibility](WPSD-COMPATIBILITY.md).

## No possible exchanges appear

A/B/A detection needs your callsign on RF, the other callsign, and matching channel information. Known durations under two seconds are ignored; a missing duration does not discard an otherwise usable WPSD row. YSF uses the observed room when available and falls back to DG-ID on that hotspot when it is not. Your current poll limit may miss bursts in a busy room.

Use **Activity queue** and review contacts manually when evidence is incomplete. The detector never proves that someone spoke to you.

## The YSF destination only says DG-ID

DG-ID and room name are different values. Room capture needs a fresh transmission and the public YSF status panel, or a room supplied by the API. Historical entries retain an unknown room.

The review comment may suggest the **current room (verify)**. Replace it with the room you used; do not assume the current link was active for an old contact.

## The frequency or band looks wrong

In **Settings**, enter your radio's transmit frequency for that hotspot. In WPSD, this is **Radio Frequency RX**, not TX on a duplex hotspot.

The logger supports ADIF 10m, 6m, 2m, 70cm, 33cm, and 23cm frequency ranges. Both 441.425 and 446.425 are 70cm. Review the propagation field separately for an Internet-routed contact.

## The timestamp is wrong

The logger always uploads UTC. Use the activity page's **Local / UTC** toggle for display, and keep **WPSD timestamp source zone → UTC** for current WPSD.

Only change it for an older/custom feed with local times and no offset. Use an IANA zone such as `America/Chicago`, then compare a fresh entry with WPSD.

## The QRZ button is disabled or QRZ rejects a contact

Check the saved API key, the logbook callsign, and your QRZ subscription. API inserts require XML-level access or higher.

Read the displayed rejection. Correct the fields or key and retry. The logger does not send QRZ's replace option. Locally saved ADIF works without an API key.

## QRZ result uncertain

A timeout, server error, or incomplete reply can happen after QRZ received the contact. The entry stays locked until you check it.

1. Open QRZ and look for the callsign and UTC time.
2. Select **Found in QRZ** if the QSO exists.
3. Select **Not in QRZ — reopen** only after confirming it is absent.

Unresolved entries are excluded from ADIF export. Explicitly rejected requests are also excluded. Saved and confirmed uploads remain exportable.

## Theme matching fails

Open **Settings** and read the source's theme status. The public dashboard and stylesheet must be reachable from the logger. Unsupported colors or unavailable pages retain the last matched colors or use the default palette.

Refresh the browser after changing WPSD colors; matching is checked every five minutes. **All hotspots** uses the first source's theme.

## Restore a backup

Use the [backup and restore guide](BACKUP-AND-UPDATES.md). Removing a local `data` folder does not reset this app: it uses a named Docker volume.

## Erase the local installation

This permanently removes the logger's settings, password, key, and all local contacts. It does not delete QSOs in QRZ. Back up first if you need any of this data.

From this project's folder:

```bash
docker compose down -v
docker compose up -d --build
```

The GUI then opens first-run setup. Never use `docker system prune --volumes` for this; it can affect unrelated projects.

## Report a bug

Use the GitHub bug-report form. Include the logger and WPSD versions, the exact error, and steps to reproduce it. Remove passwords, API keys, callsigns unrelated to the problem, and private addresses from screenshots or API samples.

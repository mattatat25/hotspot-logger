# Backups, restore, and updates

Run these commands from the project folder. Configuration and contacts live in the named Docker volume, not the source-code folder.

## Make a backup

With the logger running:

```bash
bash scripts/backup.sh
```

The script prints the path of a new archive in `backups/`. It uses SQLite's backup API, so the database is copied consistently while the app runs. The archive contains settings, the QRZ key, password hash, contacts, and removed-record IDs.

Copy the archive somewhere private outside the VM. Git ignores the backups folder. Do not attach an archive to a GitHub issue.

## Restore a backup

Restoring replaces the local database with the backup. Take a backup of the current instance first if you need to keep its data.

```bash
bash scripts/restore.sh backups/hotspot-logger-TIMESTAMP-SUFFIX.tar.gz
```

Replace the example filename with the actual path printed by the backup script.

The script builds the image, validates the archive and SQLite database, then stops the logger, replaces the database, and starts it again. An invalid archive is rejected before the running service stops. The restore does not contact QRZ or change its logbook.

Sign in with the callsign and password from the backup. Check hotspot addresses in **Settings**, especially after moving to a different network.

## Update a Git checkout

```bash
bash scripts/update.sh
```

The updater checks for local changes, backs up the running logger, pulls the current branch with `git pull --ff-only`, and rebuilds the container. It waits for a healthy web server before reporting success. A failed backup stops the update. GUI settings and saved contacts remain in the same data volume. Confirm the new version in the page footer.

If you are upgrading from 0.8.0-beta.1 or earlier, run `bash scripts/backup.sh` once before using the old updater; those versions do not back up automatically.

If Git reports local changes or a divergent branch, stop and inspect the changes. Do not fix it with `git reset --hard` unless you understand what it will discard.

## Update a ZIP download

ZIP downloads have no Git history, so the update script cannot pull a new version.

1. Make a backup with the current installation.
2. Download and extract the new ZIP into a **different folder**.
3. From the old folder, run `docker compose stop logger`.
4. In the new folder, run `bash scripts/restore.sh /absolute/path/to/your/backup.tar.gz`.
5. Open the GUI and verify your settings and contacts.

Keep the old folder and backup until verification is complete. Compose uses the folder name in its default volume name. Reusing a different folder without restoring can look like a blank installation.

## Move to another computer or Pi

Download the project on the new host and run `bash setup.sh` to install Docker and start a fresh instance. Do not complete the browser setup. Transfer a backup privately, then run the restore script from the new project folder. After restoring, sign in with the callsign and password from the backup.

Stop the old logger before using the new one. Running two copies of the same database can lead to separate submission histories. Do not upload contacts from both.

## Stop or remove the app

```bash
docker compose down
```

This stops and removes the container while keeping the data volume.

`docker compose down -v` deletes the data volume and all local settings and contacts. It does not delete QSOs from QRZ.

[Installation](INSTALL.md) · [Troubleshooting](TROUBLESHOOTING.md)

## Updating an older installation

Keep using your existing project directory and Compose project name. Docker uses that name when selecting the data volume. Renaming or moving the directory can make an existing database appear missing. The service, volume definition, and settings keys are unchanged. Existing backup filenames remain accepted.

After the repository rename, update the remote URL from inside your existing folder:

```bash
git remote set-url origin https://github.com/mattatat25/hotspot-logger.git
```

If your install tracks the earlier review branch, back up first, then use `git fetch origin`, `git switch main`, and `bash scripts/update.sh`. Do not rename the installation folder.

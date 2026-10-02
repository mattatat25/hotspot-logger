# Security

Hotspot Logger is built for one operator on a trusted home network.

## Network access

Port **8787** is published on all host interfaces. Complete initial setup promptly: anyone who can reach a new installation can configure it. Do not forward this port through your router. Use a private VPN or an HTTPS reverse proxy for remote access.

The app uses HTTP Basic authentication. Plain HTTP does not encrypt passwords or settings in transit. There is no built-in login rate limiter. Docker-published ports may bypass UFW rules; follow [Docker's firewall guidance](https://docs.docker.com/engine/network/packet-filtering-firewalls/).

The unauthenticated `/healthz` endpoint returns the version and connection status, without callsigns, keys, hotspot addresses, or contact data.

## Stored credentials

Passwords are stored as salted PBKDF2 hashes. The QRZ API key must remain readable by the application and is stored in the local database. Database files use mode `0600`; the container runs as a non-root account. Host administrators and users with Docker access can still read the data.

Backups contain the same credentials and contacts. Keep them private and copy them off the server. Do not attach a database or backup to an issue.

If a key is exposed, regenerate it in QRZ and replace it in **Settings**. Change an exposed logger password there as well. Deleting a secret from the latest source revision does not remove it from Git history.

## Report a vulnerability

Use **Security → Report a vulnerability** in the GitHub repository when available. If that option is missing, open an issue asking for a private reporting channel without including exploit details or credentials.

Include the affected version, steps to reproduce the problem, and its impact.

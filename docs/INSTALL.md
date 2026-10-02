# Install Hotspot Logger

The logger runs on a computer that can reach your WPSD hotspots. Use a browser on your desktop or phone to set it up and review contacts. The server itself does not need a desktop environment.

## Choose a host

| Host | Starting point |
| --- | --- |
| Raspberry Pi | Pi 4 or Pi 5, 2 GB RAM, Raspberry Pi OS Lite **64-bit**, 16 GB or larger storage |
| Ubuntu VM | Ubuntu Server 24.04 or 26.04 LTS, 2 vCPUs, 2 GB RAM, 20 GB disk |
| Existing Linux Docker host | Docker Engine and a current Docker Compose plugin, with port 8787 available |

These are practical starting allocations, not performance benchmarks. On Unraid, put the Ubuntu VM on a bridged network so it receives its own LAN address. Use a separate Pi for the logger rather than adding software to your WPSD hotspot.

### Prepare a Raspberry Pi

1. Open [Raspberry Pi Imager](https://www.raspberrypi.com/software/) on your desktop.
2. Select your Pi and **Raspberry Pi OS Lite (64-bit)**. A graphical desktop is unnecessary.
3. Set a username, password, and hostname. Configure Wi-Fi if you are not using Ethernet, and enable SSH in Imager's customization settings.
4. Write the card, put it in the Pi, connect the network, and power it on.
5. Find its address in your router's client list, then connect from a terminal:

```bash
ssh YOUR_USERNAME@SERVER_IP
```

Replace both placeholders. Use the account you created in Imager; there is no assumed default password. The automatic installer supports the Bookworm and Trixie releases of the 64-bit OS. A 64-bit kernel on a 32-bit OS is not enough: `dpkg --print-architecture` must report `arm64`.

### Prepare Ubuntu Server

Use the VM console or SSH. If SSH was not installed during Ubuntu setup:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
hostname -I
```

Connect from your desktop with `ssh YOUR_USERNAME@SERVER_IP`.

## Download and start

On the server:

```bash
sudo apt update && sudo apt install -y git
git clone https://github.com/mattatat25/hotspot-logger.git
cd hotspot-logger
bash setup.sh
```

If Docker is missing, setup asks whether to install it. Answer `y` to install Docker Engine and Compose from Docker's official package repository. Enter your Linux password when `sudo` asks. Setup uses `sudo` for Docker when needed, without changing your account's group membership.

The installer supports 64-bit Ubuntu 22.04/24.04/26.04 and Debian 12/13, including Raspberry Pi OS Lite 64-bit. It stops if it finds conflicting container packages or an existing Docker package source. It does not uninstall or replace those packages.

When Docker is already installed, setup uses it. The image builds for the host architecture automatically; you do not choose a special Pi image.

Setup waits for the logger's health check and prints a URL such as **`http://192.168.1.80:8787`**. Open that address on your desktop or phone. Use the server's address, not your desktop's `localhost` or the hotspot's address.

### Manual Docker installation

For another host, an existing container installation, or a missing Compose plugin, follow Docker's instructions for [Ubuntu](https://docs.docker.com/engine/install/ubuntu/) or [Debian](https://docs.docker.com/engine/install/debian/). Docker directs 64-bit Raspberry Pi OS users to the Debian instructions.

Check Docker with `sudo docker info` and `sudo docker compose version`, then run `bash setup.sh` as your normal login user. The setup script needs a Compose release supporting `up --wait-timeout`.

### Download as a ZIP

Git is recommended because it makes updates easier. If you prefer a ZIP:

1. Open the repository and select **Code → Download ZIP**.
2. Extract it on the server and enter the extracted folder.
3. Run `bash setup.sh`.

Keep the folder name unchanged after installation. It determines which Docker data volume is used. ZIP updates use [backup and restore](BACKUP-AND-UPDATES.md#update-a-zip-download).

## Complete the browser setup

| Field | What to enter | Where to find it |
| --- | --- | --- |
| Hotspot name | A label such as YSF desk or DMR travel | Choose a name you recognize. |
| WPSD API URL | The hotspot's address followed by `/api/` | For dashboard `http://192.168.1.50/`, use `http://192.168.1.50/api/`. |
| Radio TX frequency | MHz, such as `441.425` | WPSD **Admin → Configuration → Radio Frequency RX**. |
| Station callsign | Your radio and logbook callsign | Use the same callsign as the QRZ logbook you plan to use. |
| QRZ Logbook API key | Optional key for that logbook | QRZ **My Logbook → Settings → API**; [QRZ instructions](https://www.qrz.com/docs/logbook30/api). |
| Timestamp time zone | `UTC` | Only change it for an older feed that reports local time without an offset. |
| Logger password | At least eight characters, entered twice | Choose a password for this logger. |

Leave the poll interval at **10 seconds**, rows at **40**, and theme at **Match WPSD** to start. Select **Add hotspot** for additional sources, then **Start logger**.

Your callsign is the login username. Use it with the password you just created. All later changes are made in **Settings**; no configuration file is needed.

For a duplex hotspot with RX 441.425 and TX 446.425, enter **441.425**: your radio transmits to the hotspot's receiver. Reserve the server and hotspot addresses in your router so they do not change.

## Check the first contact

Compare a fresh entry with the WPSD dashboard. After a real QSO, review the contact and check its time, mode, frequency, and room or talkgroup. Save it locally or upload it, then inspect the resulting ADIF or QRZ entry.

The container's health check confirms the web server is running. Each hotspot's connection status appears separately in the GUI.

## Network access

Port 8787 listens on all server interfaces. Keep it on your trusted LAN and complete first-run setup promptly. Use a private VPN for remote access. Plain HTTP does not encrypt your login or API key while you enter it.

Docker-published ports can bypass UFW rules; see [Docker's firewall guidance](https://docs.docker.com/engine/network/packet-filtering-firewalls/). Do not forward port 8787 directly from the Internet.

[Using the logger](USAGE.md) · [Backup and updates](BACKUP-AND-UPDATES.md) · [Troubleshooting](TROUBLESHOOTING.md)

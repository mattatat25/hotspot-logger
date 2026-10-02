# Using the logger

Open `http://SERVER_IP:8787` and sign in with your station callsign and logger password.

## Enter your settings

Open **Settings**. Changes take effect without restarting Docker.

### Add a hotspot

1. Select **Add hotspot**.
2. Give it a name you recognize, such as **YSF desk** or **DMR travel**.
3. Open that hotspot's WPSD dashboard and copy its address.
4. Add `/api/` to the address. For `http://192.168.1.50/`, enter `http://192.168.1.50/api/`.
5. In WPSD, open **Admin → Configuration** and copy **Radio Frequency RX** into **Radio TX frequency · MHz**.
6. Select **Save settings** and check its connection status in the logger.

Use the address of each individual hotspot. A DMR radio and a YSF hotspot are different sources. The logger cannot discover a second hotspot's address from the first one.

Rename a hotspot freely. Removing one stops polling but keeps its entries. If you add it again as a new source, it receives a new source ID; older entries keep their original source.

### Set up QRZ

1. Sign in to QRZ and open **My Logbook**.
2. Select the logbook for your station callsign.
3. Open **Settings → API**, or [the QRZ API page](https://www.qrz.com/docs/logbook30/api).
4. Copy the **Logbook API key** into the logger's Settings.
5. Save Settings.

This is the logbook key, not your QRZ password or XML callsign-lookup credentials. API inserts require an XML-level subscription or higher. Without that access, leave the key blank and use ADIF.

A blank key field keeps an existing key. Check **Remove the saved QRZ key** to delete it. Password fields work the same way: leave both blank to keep the password, or enter and repeat a new one of at least eight characters.

### Theme and polling

**Match WPSD** uses the hotspot's public theme colors. A selected hotspot controls the page's colors; **All hotspots** uses the first source. Color changes are checked every five minutes. Refresh the page to see them.

Start with a **10-second** poll interval and **40 rows** per hotspot. A busy room may need more rows to avoid missing bursts. Polls run sequentially, so the complete cycle can take longer when sources are slow or offline.

Keep **Timestamp time zone → UTC** for current WPSD. Only change it when an older feed supplies local timestamps without an offset.

## Review and save a contact

1. Make a two-way contact on your radio.
2. In **All activity**, select the hotspot or mode if needed.
3. Find the station and select **Review**.
4. Check the fields below.
5. Select **Log to QRZ** or **Save to ADIF**.

| Field | Check |
| --- | --- |
| Callsign | The station you actually worked. |
| UTC date / time | The contact time in UTC, including its date. |
| Radio TX frequency | Your radio's transmit frequency to this hotspot, in MHz. |
| Band | The local RF band derived from that frequency. |
| Mode | The originating radio mode, including cross-mode contacts. |
| Propagation | Internet-assisted for a network path, Repeater / gateway for a repeater path, or Direct RF / line of sight for a direct contact. |
| Comment | The actual room, talkgroup, or reflector you used, plus any note you want. |

Frequency and band must agree. ADIF's 70cm range is 420–450 MHz, so 441.425 is 70cm even when the contact used the Internet. Band and propagation describe different parts of the contact.

ADIF `.adi` string fields use ASCII. Use plain letters, numbers, and punctuation in comments; replace accented letters and symbols before saving.

### Mode values sent to QRZ and ADIF

| Radio mode | ADIF MODE | ADIF SUBMODE |
| --- | --- | --- |
| YSF / C4FM | DIGITALVOICE | C4FM |
| DMR | DIGITALVOICE | DMR |
| D-Star | DIGITALVOICE | DSTAR |
| P25 | DIGITALVOICE | Omitted; P25 is included in the comment. |
| NXDN | DIGITALVOICE | Omitted; NXDN is included in the comment. |
| Legacy M17 | DIGITALVOICE | M17 |
| FM | FM | Omitted. |

The app uses valid [ADIF 3.1.7 values](https://www.adif.org/317/ADIF_317.htm). It does not invent P25 or NXDN submodes. M17 is supported only when an older/custom feed reports it. Paging/POCSAG is excluded.

## Understand the status

| Status | Meaning |
| --- | --- |
| Heard only | WPSD reported the station. No exchange pattern was detected. |
| Possible exchange | A/B/A or B/A/B timing involving your RF callsign was observed. |
| Saved for ADIF | You saved the contact locally; it is in ADIF export. |
| Uploaded to QRZ | QRZ returned a complete successful insert response, or you manually confirmed it after checking. |
| Check QRZ result | The result is uncertain. Check QRZ before reopening the entry. |

Possible exchanges need matching hotspot, mode, target/room, and a reported timeslot when available, with voice bursts of at least two seconds within five minutes. Network echoes of your callsign do not qualify. Polling gaps, nets, busy rooms, or missing callsigns can still produce false positives or missed exchanges. Confirm the QSO yourself.

An upload is not a QSL confirmation. QRZ confirmation requires matching independent logs from both operators. QRZ's award rules also treat Internet/repeater contacts separately; see [confirmations](https://www.qrz.com/docs/logbook30/confirmations-how) and [award rules](https://www.qrz.com/page/qrz-operating-awards).

## YSF rooms and DG-ID

YSF's **DG-ID** is separate from its linked room. For fresh activity, the logger prefers an API room or reads **YSF Status → Link** from the public dashboard.

A comment can read `YSF room US-LZARC | DG-ID 0 via WPSD`. The captured room stays with the entry when the hotspot changes rooms later.

Historical Last Heard rows cannot be assigned a room from today's link. Their review page marks the room as unknown. A **current room (verify)** suggestion needs checking or replacing before saving.

## Export ADIF

Select **ADIF export** to download `hotspot-logger.adi`. It includes all local saves and successful/resolved QRZ uploads across your hotspots, regardless of the current filter. It excludes rejected and unresolved submissions.

For manual QRZ import, open the correct QRZ logbook and use its **Settings → Import** option. Do not repeatedly import the same contacts or import contacts already uploaded by this logger without checking for duplicates.

## Delete or clear entries

**Delete** removes one local entry and its ADIF copy after a confirmation page. It does not remove the QSO from QRZ; delete that separately in QRZ if needed. A removed WPSD record stays removed across subsequent polls.

**Clear queue** removes unlogged candidates, including entries beyond the 100 displayed. It keeps saved contacts and uncertain QRZ submissions. A selected hotspot limits the clear to that source. **All hotspots** clears every source. The mode filter does not narrow this action; read the scope on the confirmation page.

## Handle an uncertain QRZ result

Open the entry and check QRZ for the callsign and UTC time. Select **Found in QRZ** if it exists. Select **Not in QRZ — reopen** only after confirming it is absent. The logger never retries automatically.

[Installation](INSTALL.md) · [Backup and updates](BACKUP-AND-UPDATES.md) · [Troubleshooting](TROUBLESHOOTING.md)

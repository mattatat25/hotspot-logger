# WPSD compatibility

## Supported endpoint

Preferred current endpoint:

```text
http://HOTSPOT/api/?limit=40&names=false&country=false
```

An older endpoint using `/api/last_heard.php?num_transmissions=40` is also recognized when that exact path is configured.

The parser supports a top level JSON array and arrays inside `lastheard`, `last_heard`, `heard`, `entries`, `records`, `data`, or `results`.

## Recognized fields

| Meaning | Recognized names include |
| --- | --- |
| UTC time | `time_utc`, `heard_at`, `timestamp`, `datetime`, `start`, `time` |
| Mode | `mode`, `protocol`, `type` |
| Callsign | `callsign`, `call`, `source_callsign` |
| Target | `target`, `talkgroup`, `destination`, `reflector`, `room` |
| Direction | `src`, `source`, `direction`, `origin`, `via` |
| Duration | `duration`, `seconds` |

Voice modes include DMR, YSF/C4FM/Fusion, D-Star, P25/APCO25, NXDN, legacy M17, and FM when reported. A cross-mode label such as `YSF2DMR` follows its originating radio mode. Paging/POCSAG and unidentified numeric callers are excluded. Your station callsign stays out of the contact queue, while RF transmissions are retained as exchange evidence.

## Multiple hotspots

Add and name sources in **Settings → Hotspots**. Each has its own API URL and radio transmit frequency. The original single-source configuration becomes **Hotspot 1** on upgrade; rename it freely. Existing contact IDs, ADIF records, removed IDs, and passwords remain valid. New source IDs are stable through renames and scope record identity, filters, colors, and exchange evidence.

## Room and exchange metadata

YSF room fields in a feed are preferred. When a transmission only has DG-ID, the logger reads the hotspot's public dashboard and recognizes the **YSF Status → Link** panel and older **YSF Net** panels. It captures that current room only for recent activity within the greater of 60 seconds or two poll intervals. A historical row cannot establish its room from today's link. The review page marks current-room suggestions for verification rather than inventing historical room names.

The supported API primarily supplies Last Heard, not a semantic QSO record. Possible-exchange detection needs your callsign on **RF**, other participants' callsigns, timestamps, durations of at least two seconds, and matching channel context. Missing data keeps an entry **Heard only**. A/B/A and B/A/B evidence is a heuristic, never an automatic QRZ upload or confirmation.

For duplex sources, WPSD's RX frequency is your radio's TX frequency. Keep these distinct when entering the source's frequency.

## Inspecting an installed hotspot

From the Docker host:

```bash
curl -sS 'http://HOTSPOT-IP/api/?limit=3&names=false&country=false'
```

Check for a complete timestamp, mode, callsign, target, source, and duration. Redact callsigns, names, addresses, and other private information before sharing a sample in an issue.

If WPSD returns data but the logger reports that no rows were recognized, open an issue with:

- WPSD version
- endpoint path used
- redacted single JSON object
- whether its displayed time is UTC or local

The WPSD API manual documents how to request Last Heard JSON but does not promise a fixed response schema. This adapter therefore treats unknown shapes as an explicit error instead of guessing a QSO time.

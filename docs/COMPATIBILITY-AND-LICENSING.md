# Compatibility and licensing

Hotspot Logger is an independent project created by KF0WSS. WPSD and QRZ are named to explain compatibility. Neither project has endorsed Hotspot Logger, and no permission to use their logos is claimed.

## WPSD

The logger reads the configured hotspot's API and public dashboard. It does not modify WPSD, distribute its software, or download a central reflector directory. Room names and theme colors come from the hotspot you configure.

WPSD's software license does not automatically cover its branding, website content, or compiled data. See the [WPSD API documentation](https://manual.wpsd.radio/advanced/api/) and [W0CHP legal notices](https://w0chp.radio/legal/) for their separate terms.

## QRZ Logbook

QRZ publishes a [Logbook API](https://www.qrz.com/docs/logbook/QRZLogbookAPI.html) for external logging applications. Hotspot Logger submits a contact only after you select **Log to QRZ**, using your logbook key and an identifying User-Agent. Your account must have the required API privileges.

[QRZ's terms](https://www.qrz.com/page/qrz_terms.html) require written permission to use its marks. Describing compatibility and using another service's name as your own branding are different uses; the clause alone does not settle whether a particular reference infringes a trademark. API access is also separate from permission to use branding. These notes explain the project's approach, not a legal clearance.

## Software and data

The application code is available under the [MIT license](../LICENSE). Python, Alpine Linux, Docker, and their dependencies retain their respective licenses. The project license does not grant rights to third-party marks.

Settings, credentials, and contact history are stored locally. There is no analytics service. Contact details go to QRZ only when you approve an upload. Treat databases and backups as private; see [SECURITY.md](../SECURITY.md).

Logging a contact does not establish that a two-way exchange occurred, confirm a QSL, or determine award eligibility. Review each entry and follow your logbook provider's rules.

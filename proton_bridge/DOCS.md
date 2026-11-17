# Proton Mail Bridge

Runs Proton's official Bridge (pinned version, checksum-verified) so Home Assistant's
IMAP integration can read your inbox. IMAP is only reachable from Home Assistant itself
on port 9143 of this app's internal hostname. Nothing is opened on your network.

## First login
1. Open **Proton Bridge** in the sidebar. You get Bridge's command line.
2. Type `login` and follow the prompts (email, password, 2FA code).
3. Type `info` and note the IMAP **username** and the Bridge-generated **password**.
   That password is not your Proton password; it only works against this Bridge.
4. Leave the panel. Bridge keeps running in the background.

Updating Bridge is done by changing the pinned version in the Dockerfile.

## Connecting Home Assistant's IMAP integration
- **Server:** this app's hostname (shown on the app's Info page, e.g. `xxxxxxxx-proton-bridge`)
- **Port:** `9143`
- **Username / password:** from `info` in the Bridge panel
- **Security:** STARTTLS, with certificate verification off (Bridge uses a self-signed certificate on the internal network)

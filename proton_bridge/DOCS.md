# Proton Mail Bridge

Runs Proton's official Bridge (pinned version, checksum-verified) so Home Assistant's
IMAP integration can read your inbox. IMAP is only reachable from Home Assistant itself
on port 9143 of this app's internal hostname. Nothing is opened on your network.

## First login
1. Open **Proton Bridge** from the app page (**Open web UI**) or turn on **Show in sidebar**.
2. Sign in with your Proton email and password, then your two-factor code (and mailbox password, if you use one).
3. Once signed in, the **Home Assistant connection** card shows the IMAP username and the Bridge-generated password.
   That password is not your Proton password; it only works against this Bridge.

The **Settings** tab covers the All Mail folder, alternative routing, usage diagnostics, automatic updates,
repair and restart. The **Console** tab gives you Bridge's own command line for everything else.

Updating Bridge is done by changing the pinned version in the Dockerfile.

## Connecting Home Assistant's IMAP integration
- **Server:** this app's hostname (shown on the app's Info page, e.g. `xxxxxxxx-proton-bridge`)
- **Port:** `9143`
- **Username / password:** from `info` in the Bridge panel
- **Security:** SSL (turn on **IMAP over SSL** in Settings; Home Assistant has no STARTTLS), with certificate verification off (Bridge uses a self-signed certificate)

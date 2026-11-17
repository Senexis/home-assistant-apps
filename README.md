# Home Assistant apps

Personal Home Assistant apps (add-ons).

| App | Description |
|---|---|
| [Proton Mail Bridge](proton_bridge/) | Proton's official Bridge, so Home Assistant can read (IMAP) and send (SMTP) Proton Mail. Only reachable inside Home Assistant. |

## Install

In Home Assistant, go to **Settings → Apps → App store → ⋮ → Repositories** and add:

```
https://github.com/Senexis/home-assistant-apps
```

Proton Mail Bridge is downloaded from proton.me at build time and verified against a pinned
SHA-256 checksum; it is not redistributed here. It requires a paid Proton plan.

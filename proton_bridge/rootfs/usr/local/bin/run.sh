#!/bin/bash
set -euo pipefail

# Everything Bridge stores (login vault, keychain, cache) lives in /data.
export HOME=/data/home
export GNUPGHOME="$HOME/.gnupg"
export PASSWORD_STORE_DIR="$HOME/.password-store"
mkdir -p "$HOME"
chmod 700 "$HOME"

# First run: create a local keychain (gpg key + pass) that Bridge uses to store its vault key.
if [ ! -f "$HOME/.keychain-ready" ]; then
  mkdir -p "$GNUPGHOME" && chmod 700 "$GNUPGHOME"
  gpg --batch --pinentry-mode loopback --passphrase '' \
      --quick-gen-key 'Proton Bridge (Home Assistant)' default default never
  pass init 'Proton Bridge (Home Assistant)'
  touch "$HOME/.keychain-ready"
fi

# Tell Bridge to use that keychain (there is no desktop secret service in here).
PREFS="$HOME/.config/protonmail/bridge-v3/prefs.json"
if [ ! -f "$PREFS" ]; then
  mkdir -p "$(dirname "$PREFS")"
  printf '{"preferred_keychain":"pass"}\n' > "$PREFS"
fi

# Bridge only listens on 127.0.0.1:1143; expose it to Home Assistant on the internal network.
socat TCP-LISTEN:9143,fork,reuseaddr TCP:127.0.0.1:1143 &

# The web UI (Ingress only) runs Bridge's CLI itself and restarts it if it exits.
exec python3 -u /app/server.py

FROM debian:trixie-slim@sha256:8aa5a7bf5a1955bddbe7d74fcdd0b91ab30e74362a8b73af672b0481b35b44a0

# Proton's official Bridge release, pinned and checksum-verified.
# Kept current by .github/workflows/update-check.yaml (daily). By hand: change both values
# (sha256 of the .deb from proton.me) and bump the config.yaml version.
ARG BRIDGE_VERSION=3.27.2
ARG BRIDGE_SHA256=cf08332dcc4a332c3592476855e2007e6daadbcdac11fab6af83470a3255a8dc

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg pass socat python3 \
      libsecret-1-0 libfido2-1 libcbor0.10 libglib2.0-0t64 \
 && curl -fsSL -o /tmp/bridge.deb \
      "https://proton.me/download/bridge/protonmail-bridge_${BRIDGE_VERSION}-1_amd64.deb" \
 && echo "${BRIDGE_SHA256}  /tmp/bridge.deb" | sha256sum -c - \
 && dpkg-deb --fsys-tarfile /tmp/bridge.deb | tar -xO ./usr/lib/protonmail/bridge/bridge > /usr/local/bin/bridge \
 && chmod 0755 /usr/local/bin/bridge \
 && /usr/local/bin/bridge --version \
 && rm -f /tmp/bridge.deb \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/*

COPY rootfs /
RUN chmod 0755 /usr/local/bin/run.sh

CMD ["/usr/local/bin/run.sh"]

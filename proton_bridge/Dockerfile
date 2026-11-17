FROM debian:trixie-slim

# Proton's official Bridge release, pinned and checksum-verified.
# To update: change both values (sha256 of the .deb from proton.me) and bump config.yaml version.
ARG BRIDGE_VERSION=3.27.2
ARG BRIDGE_SHA256=cf08332dcc4a332c3592476855e2007e6daadbcdac11fab6af83470a3255a8dc
# ttyd (web terminal) isn't packaged in Debian trixie: official static release, checksum from its SHA256SUMS.
ARG TTYD_VERSION=1.7.7
ARG TTYD_SHA256=8a217c968aba172e0dbf3f34447218dc015bc4d5e59bf51db2f2cd12b7be4f55

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update \
 && apt-get install -y --no-install-recommends \
      ca-certificates curl gnupg pass tmux nginx socat \
      libsecret-1-0 libfido2-1 libcbor0.10 libglib2.0-0t64 \
 && curl -fsSL -o /usr/local/bin/ttyd \
      "https://github.com/tsl0922/ttyd/releases/download/${TTYD_VERSION}/ttyd.x86_64" \
 && echo "${TTYD_SHA256}  /usr/local/bin/ttyd" | sha256sum -c - \
 && chmod 0755 /usr/local/bin/ttyd \
 && curl -fsSL -o /tmp/bridge.deb \
      "https://proton.me/download/bridge/protonmail-bridge_${BRIDGE_VERSION}-1_amd64.deb" \
 && echo "${BRIDGE_SHA256}  /tmp/bridge.deb" | sha256sum -c - \
 && dpkg-deb --fsys-tarfile /tmp/bridge.deb | tar -xO ./usr/lib/protonmail/bridge/bridge > /usr/local/bin/bridge \
 && chmod 0755 /usr/local/bin/bridge \
 && /usr/local/bin/bridge --version \
 && rm -f /tmp/bridge.deb \
 && apt-get purge -y curl && apt-get autoremove -y \
 && rm -rf /var/lib/apt/lists/* /etc/nginx/sites-enabled/*

COPY rootfs /
RUN chmod 0755 /usr/local/bin/run.sh /usr/local/bin/bridge-loop.sh

CMD ["/usr/local/bin/run.sh"]

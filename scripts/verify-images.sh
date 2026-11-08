#!/usr/bin/env bash
# Re-check every image listed in /srv/netboot/http/SHA256SUMS.
# Add a new image only after comparing its hash with the official one:
#   cd /srv/netboot/http && sha256sum tools/memtest/memtest64.efi
#   (compare with the vendor's published sum, then)
#   sha256sum tools/memtest/memtest64.efi >> SHA256SUMS
set -euo pipefail
cd /srv/netboot/http
[[ -s SHA256SUMS ]] || { echo "SHA256SUMS is empty or missing"; exit 1; }
sha256sum --check --quiet SHA256SUMS && echo "All images match SHA256SUMS"

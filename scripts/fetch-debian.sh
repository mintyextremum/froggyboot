#!/usr/bin/env bash
# Download the Debian 13 netboot kernel and initrd and check them against
# Debian's SHA256SUMS before they land in the menu folder.
set -euo pipefail
DEST=/srv/netboot/http/linux/debian
BASE=https://deb.debian.org/debian/dists/trixie/main/installer-amd64/current/images
TMP="$(mktemp -d)"; trap 'rm -rf "$TMP"' EXIT

[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
cd "$TMP"
curl -fsSL -o SHA256SUMS "$BASE/SHA256SUMS"
for f in linux initrd.gz; do
    curl -fsSL -o "$f" "$BASE/netboot/debian-installer/amd64/$f"
    want="$(awk -v p="./netboot/debian-installer/amd64/$f" '$2==p {print $1}' SHA256SUMS)"
    have="$(sha256sum "$f" | cut -d' ' -f1)"
    [[ -n "$want" && "$want" == "$have" ]] || { echo "Checksum mismatch for $f" >&2; exit 1; }
    echo "ok  $f"
done
install -d "$DEST"
install -m 644 linux initrd.gz "$DEST/"
cd /srv/netboot/http
# Record the verified sums in the server's own list.
touch SHA256SUMS
grep -v ' linux/debian/' SHA256SUMS > SHA256SUMS.new || true
sha256sum linux/debian/linux linux/debian/initrd.gz >> SHA256SUMS.new
mv SHA256SUMS.new SHA256SUMS
echo "Debian netboot installed to $DEST"

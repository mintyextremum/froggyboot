#!/usr/bin/env bash
# EXPERIMENTAL: prepare a shim -> signed iPXE chain with a local Machine Owner Key.
# See docs/SECUREBOOT.md. Does not change dnsmasq; prints the line to switch.
set -euo pipefail
[[ $EUID -eq 0 ]] || { echo "Run as root" >&2; exit 1; }
TFTP=/srv/netboot/tftp
HTTP=/srv/netboot/http
MOK=/etc/froggyboot/mok

apt-get install -y -qq shim-signed sbsigntool >/dev/null
install -d -m 700 "$MOK"
if [[ ! -f "$MOK/MOK.key" ]]; then
    openssl req -new -x509 -newkey rsa:2048 -nodes -days 3650 -subj "/CN=Froggyboot MOK/" \
        -keyout "$MOK/MOK.key" -out "$MOK/MOK.crt" 2>/dev/null
    openssl x509 -in "$MOK/MOK.crt" -outform DER -out "$MOK/MOK.der"
fi

sign() { # sign FILE in place, keeping FILE.unsigned
    local f="$1"
    if sbverify --cert "$MOK/MOK.crt" "$f" >/dev/null 2>&1; then return; fi
    [[ -f "$f.unsigned" ]] || cp "$f" "$f.unsigned"
    sbsign --key "$MOK/MOK.key" --cert "$MOK/MOK.crt" --output "$f" "$f.unsigned"
    echo "signed $f"
}

install -m 644 /usr/lib/shim/shimx64.efi.signed "$TFTP/shimx64.efi"
install -m 644 /usr/lib/shim/mmx64.efi.signed "$TFTP/mmx64.efi"
sbsign --key "$MOK/MOK.key" --cert "$MOK/MOK.crt" --output "$TFTP/grubx64.efi" "$TFTP/ipxe.efi"
echo "signed $TFTP/grubx64.efi (iPXE)"

# Unsigned EFI binaries in the HTTP tree (distribution kernels already signed stay untouched).
while IFS= read -r -d '' f; do
    head -c 2 "$f" | grep -q MZ || continue
    if sbverify --list "$f" 2>/dev/null | grep -q 'signature 1'; then continue; fi
    sign "$f"
done < <(find "$HTTP" -type f \( -name 'vmlinuz*' -o -name linux -o -name bzImage -o -name wimboot -o -name '*.efi' \) -print0)

install -m 644 "$MOK/MOK.der" "$HTTP/froggyboot-mok.der"
cat <<EOF

Done. To switch UEFI clients to shim, edit /etc/dnsmasq.d/netboot.conf:
  pxe-service=tag:efi64,X86-64_EFI,"Netboot",shimx64.efi
then: systemctl restart dnsmasq
Enroll $HTTP/froggyboot-mok.der once on every PC with MokManager.
Re-run this script after install.sh rebuilds iPXE or after adding images.
EOF

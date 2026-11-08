#!/usr/bin/env bash
# Froggyboot installer for Debian 13. Run as root from the repository folder:
#   cp config.env.example config.env && nano config.env
#   sudo ./install.sh                # install / update configs and menus
#   sudo ./install.sh --rebuild-ipxe # also rebuild iPXE (after changing embed.ipxe)
# Safe to run again: images in /srv are never touched, passwords are kept.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
SRV_ROOT=/srv/netboot
IMAGES=/srv/images/windows
IPXE_SRC=/usr/local/src/ipxe
REBUILD_IPXE=0
[[ "${1:-}" == "--rebuild-ipxe" ]] && REBUILD_IPXE=1

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo ./install.sh"
[[ -f "$REPO/config.env" ]] || die "No config.env. Copy config.env.example to config.env and edit it."
# Accept a config.env edited on Windows (CRLF).
# shellcheck disable=SC1090
source <(tr -d '\r' < "$REPO/config.env")

# ---------- validate config ----------
ip_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
[[ "${SERVER_IP:-}" =~ $ip_re ]] || die "SERVER_IP is not an IPv4 address"
[[ "${NET_CIDR:-}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] || die "NET_CIDR must look like 192.168.1.0/24"
NET_ADDR="${NET_CIDR%/*}"
[[ -n "${IFACE:-}" ]] && ip link show "$IFACE" >/dev/null 2>&1 || die "Interface '${IFACE:-}' not found (see: ip -br addr)"
[[ "${SMB_USER:-}" =~ ^[a-z][a-z0-9_-]{1,31}$ ]] || die "SMB_USER: lowercase letters/digits only"
[[ "${SMB_PASS:-}" =~ ^[A-Za-z0-9]{8,}$ ]] || die "SMB_PASS: letters and digits only, 8+ characters"
[[ "$SMB_PASS" != "ChangeMe2026" ]] || die "Change SMB_PASS in config.env"
ip -br addr show "$IFACE" | grep -qw "${SERVER_IP}" || warn "$SERVER_IP is not assigned to $IFACE - check config.env"

render() { # render SRC DST [crlf]
    install -d "$(dirname "$2")"
    tr -d '\r' < "$1" | sed \
        -e "s|@SERVER_IP@|$SERVER_IP|g" \
        -e "s|@IFACE@|$IFACE|g" \
        -e "s|@NET_ADDR@|$NET_ADDR|g" \
        -e "s|@NET_CIDR@|$NET_CIDR|g" \
        -e "s|@SMB_USER@|$SMB_USER|g" \
        -e "s|@SMB_PASS@|$SMB_PASS|g" > "$2.tmp"
    [[ "${3:-}" == crlf ]] && sed -i 's/$/\r/' "$2.tmp"
    mv "$2.tmp" "$2"
}

# ---------- packages ----------
log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq dnsmasq nginx apache2-utils samba curl ca-certificates \
    git make gcc binutils perl liblzma-dev mtools >/dev/null

# ---------- folders and menus ----------
log "Creating $SRV_ROOT and $IMAGES"
install -d -m 755 "$SRV_ROOT"/{tftp,http} "$SRV_ROOT"/http/{linux/debian,linux/ubuntu,tools/memtest,tools/gparted,tools/sysrescue,blobs/clonezilla} \
    "$SRV_ROOT"/http/secure/{install,console} "$SRV_ROOT"/http/danger/{clonezilla,shredos} "$IMAGES"

log "Rendering menus and WinPE scripts"
render "$REPO/server/embed.ipxe" "$SRV_ROOT/embed.ipxe"
while IFS= read -r -d '' f; do
    rel="${f#"$REPO/server/http/"}"
    case "$f" in
        *.cmd|*.ini) render "$f" "$SRV_ROOT/http/$rel" crlf ;;
        *)           render "$f" "$SRV_ROOT/http/$rel" ;;
    esac
done < <(find "$REPO/server/http" -type f -print0)
# install.cmd holds the Samba password: readable by nginx only.
chown root:www-data "$SRV_ROOT/http/secure/install/install.cmd"
chmod 640 "$SRV_ROOT/http/secure/install/install.cmd"

# ---------- iPXE ----------
if [[ $REBUILD_IPXE -eq 1 || ! -f "$SRV_ROOT/tftp/undionly.kpxe" || ! -f "$SRV_ROOT/tftp/ipxe.efi" ]]; then
    log "Building iPXE with embedded script (takes a few minutes)"
    if [[ -d "$IPXE_SRC/.git" ]]; then git -C "$IPXE_SRC" pull -q; else git clone -q https://github.com/ipxe/ipxe.git "$IPXE_SRC"; fi
    cat > "$IPXE_SRC/src/config/local/general.h" <<'EOF'
#define REBOOT_CMD
#define POWEROFF_CMD
#define PING_CMD
#define NSLOOKUP_CMD
EOF
    make -s -C "$IPXE_SRC/src" -j"$(nproc)" bin/undionly.kpxe EMBED="$SRV_ROOT/embed.ipxe"
    make -s -C "$IPXE_SRC/src" -j"$(nproc)" bin-x86_64-efi/ipxe.efi EMBED="$SRV_ROOT/embed.ipxe"
    install -m 644 "$IPXE_SRC/src/bin/undionly.kpxe" "$IPXE_SRC/src/bin-x86_64-efi/ipxe.efi" "$SRV_ROOT/tftp/"
else
    log "iPXE already built (use --rebuild-ipxe after changing SERVER_IP or embed.ipxe)"
fi

if [[ ! -f "$SRV_ROOT/http/secure/wimboot" ]]; then
    log "Downloading wimboot"
    curl -fsSL -o "$SRV_ROOT/http/secure/wimboot" https://github.com/ipxe/wimboot/releases/latest/download/wimboot
fi

# ---------- dnsmasq ----------
log "Configuring dnsmasq (proxy-DHCP on $IFACE)"
render "$REPO/server/etc/dnsmasq-netboot.conf" /etc/dnsmasq.d/netboot.conf
systemctl enable -q dnsmasq
systemctl restart dnsmasq

# ---------- nginx ----------
log "Configuring nginx"
render "$REPO/server/etc/nginx-netboot.conf" /etc/nginx/sites-available/netboot
: > /etc/nginx/netboot-danger-macs.conf
for mac in ${DANGER_MACS:-}; do
    mac="$(tr 'A-F:' 'a-f-' <<<"$mac")"
    [[ "$mac" =~ ^([0-9a-f]{2}-){5}[0-9a-f]{2}$ ]] || die "Bad MAC in DANGER_MACS: $mac"
    echo "    $mac 1;" >> /etc/nginx/netboot-danger-macs.conf
done
[[ -s /etc/nginx/netboot-danger-macs.conf ]] || warn "DANGER_MACS is empty: the danger zone is closed for every PC"
ln -sf /etc/nginx/sites-available/netboot /etc/nginx/sites-enabled/netboot
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    warn "Disabling the default nginx site (it also wants default_server on port 80)"
    rm /etc/nginx/sites-enabled/default
fi
for pair in "windows:tech" "danger:admin"; do
    zone="${pair%%:*}"; user="${pair#*:}"
    file="/etc/nginx/netboot-$zone.htpasswd"
    if [[ ! -s "$file" ]]; then
        log "Set the $zone password for user '$user' (use different passwords!)"
        htpasswd -c "$file" "$user"
    fi
    chown root:www-data "$file"; chmod 640 "$file"
done
tr -d '\r' < "$REPO/server/etc/logrotate-netboot" > /etc/logrotate.d/netboot
chmod 644 /etc/logrotate.d/netboot
nginx -t -q
systemctl enable -q nginx
systemctl reload-or-restart nginx

# ---------- Samba ----------
log "Configuring Samba share [images] (read-only, user $SMB_USER)"
id "$SMB_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SMB_USER"
render "$REPO/server/etc/samba-netboot.conf" /etc/samba/netboot.conf
grep -q '^include = /etc/samba/netboot.conf' /etc/samba/smb.conf || \
    printf '\n# Froggyboot\ninclude = /etc/samba/netboot.conf\n' >> /etc/samba/smb.conf
printf '%s\n%s\n' "$SMB_PASS" "$SMB_PASS" | smbpasswd -s -a "$SMB_USER" >/dev/null
chown -R root:root "$IMAGES"; chmod 755 "$IMAGES"
testparm -s >/dev/null 2>&1 || die "testparm reports an error in smb.conf"
systemctl enable -q smbd
systemctl restart smbd

# ---------- what is still missing ----------
log "Done. Checking which images are in place:"
check() { [[ -e "$SRV_ROOT/http/$1" ]] && echo "  [ok]      $1" || echo "  [missing] $1"; }
for f in linux/debian/linux linux/debian/initrd.gz \
         linux/ubuntu/vmlinuz linux/ubuntu/initrd linux/ubuntu/ubuntu-server.iso \
         tools/memtest/memtest64.bin tools/memtest/memtest64.efi \
         tools/gparted/vmlinuz tools/gparted/initrd.img tools/gparted/filesystem.squashfs \
         tools/sysrescue/sysresccd/boot/x86_64/vmlinuz \
         secure/wimboot secure/BCD secure/boot.sdi secure/boot.wim \
         danger/clonezilla/vmlinuz danger/clonezilla/initrd.img blobs/clonezilla/filesystem.squashfs \
         danger/shredos/bzImage; do check "$f"; done
ls "$IMAGES"/*.wim "$IMAGES"/*.esd >/dev/null 2>&1 && echo "  [ok]      $IMAGES/*.wim" || echo "  [missing] $IMAGES/install.wim"
echo
echo "Missing items just fail back to the menu. See README.md -> 'Images'."
echo "Debian can be fetched automatically: sudo ./scripts/fetch-debian.sh"

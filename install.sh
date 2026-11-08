#!/usr/bin/env bash
# Froggyboot installer / updater for Debian 13 (amd64 or arm64, e.g. Raspberry Pi 5).
#   sudo ./install.sh                 first run asks a few questions, later runs just update
#   sudo ./install.sh --rebuild-ipxe  force an iPXE rebuild
# Safe to run again: images, passwords, hosts.yml and menu.yml edits are kept.
set -euo pipefail

REPO="$(cd "$(dirname "$0")" && pwd)"
OPT=/opt/froggyboot
ETC=/etc/froggyboot
SRV_ROOT=/srv/netboot
IMAGES=/srv/images/windows
INCOMING=/srv/froggyboot/incoming
IPXE_SRC=/usr/local/src/ipxe
REBUILD_IPXE=0
[[ "${1:-}" == "--rebuild-ipxe" ]] && REBUILD_IPXE=1

log()  { printf '\033[1;32m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m  %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m  %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "Run as root: sudo ./install.sh"
grep -qE '^(ID|ID_LIKE)=.*debian' /etc/os-release || warn "Not Debian - continuing, but only Debian 13 is tested"

# ---------- packages ----------
log "Installing packages"
export DEBIAN_FRONTEND=noninteractive
PKGS=(dnsmasq nginx apache2-utils samba curl ca-certificates openssl git make gcc libc6-dev binutils perl
      liblzma-dev mtools libarchive-tools wimtools python3 python3-fastapi python3-uvicorn
      python3-jinja2 python3-yaml python3-passlib)
ARCH="$(uname -m)"
CROSS=""
if [[ "$ARCH" != "x86_64" ]]; then
    # iPXE for PC clients must be x86: cross-compile on ARM servers (Raspberry Pi).
    PKGS+=(gcc-x86-64-linux-gnu binutils-x86-64-linux-gnu)
    CROSS="x86_64-linux-gnu-"
fi
apt-get update -qq
apt-get install -y -qq "${PKGS[@]}" >/dev/null

# ---------- config.env: repo copy, installed copy, or first-run wizard ----------
install -d -m 750 "$ETC"
CONF=""
for c in "$REPO/config.env" "$ETC/config.env"; do [[ -f "$c" ]] && { CONF="$c"; break; }; done
if [[ -z "$CONF" ]]; then
    log "First run: a few questions (Enter keeps the suggestion)"
    def_if="$(ip route show default 2>/dev/null | awk '{print $5; exit}')"
    read -rp "  Network interface facing the PCs [$def_if]: " IFACE; IFACE="${IFACE:-$def_if}"
    cidr="$(ip -o -4 addr show dev "$IFACE" 2>/dev/null | awk '{print $4; exit}')"
    [[ -n "$cidr" ]] || die "No IPv4 address on $IFACE"
    def_ip="${cidr%/*}"
    def_net="$(python3 -c "import ipaddress,sys; print(ipaddress.ip_interface(sys.argv[1]).network)" "$cidr")"
    read -rp "  This server's IP [$def_ip]: " SERVER_IP; SERVER_IP="${SERVER_IP:-$def_ip}"
    read -rp "  PC network [$def_net]: " NET_CIDR; NET_CIDR="${NET_CIDR:-$def_net}"
    read -rp "  MACs allowed into the danger zone (space separated, may be empty): " DANGER_MACS
    read -rp "  Use HTTPS for passwords? [y/N]: " h; [[ "${h,,}" == y* ]] && HTTPS=yes || HTTPS=no
    SMB_PASS="$(tr -dc 'A-Za-z0-9' </dev/urandom | head -c 20)"
    cat > "$ETC/config.env" <<EOF
# Written by install.sh. Edit and run install.sh again.
SERVER_IP=$SERVER_IP
IFACE=$IFACE
NET_CIDR=$NET_CIDR
SMB_USER=winpe
SMB_PASS=$SMB_PASS
DANGER_MACS="$DANGER_MACS"
HTTPS=$HTTPS
APP_PORT=8070
TELEGRAM_TOKEN=
TELEGRAM_CHAT=
EOF
    CONF="$ETC/config.env"
fi
# shellcheck disable=SC1090
source <(tr -d '\r' < "$CONF")
[[ "$CONF" != "$ETC/config.env" ]] && tr -d '\r' < "$CONF" > "$ETC/config.env"

ip_re='^([0-9]{1,3}\.){3}[0-9]{1,3}$'
[[ "${SERVER_IP:-}" =~ $ip_re ]] || die "SERVER_IP is not an IPv4 address"
[[ "${NET_CIDR:-}" =~ ^([0-9]{1,3}\.){3}[0-9]{1,3}/[0-9]{1,2}$ ]] || die "NET_CIDR must look like 192.168.1.0/24"
NET_ADDR="${NET_CIDR%/*}"
if [[ -z "${IFACE:-}" ]] || ! ip link show "$IFACE" >/dev/null 2>&1; then
    die "Interface '${IFACE:-}' not found (see: ip -br addr)"
fi
SMB_USER="${SMB_USER:-winpe}"
[[ "$SMB_USER" =~ ^[a-z][a-z0-9_-]{1,31}$ ]] || die "SMB_USER: lowercase letters/digits only"
[[ "${SMB_PASS:-}" =~ ^[A-Za-z0-9]{8,}$ ]] || die "SMB_PASS: letters and digits only, 8+ characters"
[[ "$SMB_PASS" != "ChangeMe2026" ]] || die "Change SMB_PASS in config.env"
APP_PORT="${APP_PORT:-8070}"
HTTPS="${HTTPS:-no}"; [[ "${HTTPS,,}" =~ ^(1|yes|true|on)$ ]] && HTTPS=yes || HTTPS=no
ip -br addr show "$IFACE" | grep -qw "${SERVER_IP}" || warn "$SERVER_IP is not assigned to $IFACE - check config.env"

render() { # render SRC DST [crlf]
    install -d "$(dirname "$2")"
    tr -d '\r' < "$1" | sed \
        -e "s|@SERVER_IP@|$SERVER_IP|g" \
        -e "s|@IFACE@|$IFACE|g" \
        -e "s|@NET_ADDR@|$NET_ADDR|g" \
        -e "s|@NET_CIDR@|$NET_CIDR|g" \
        -e "s|@SMB_USER@|$SMB_USER|g" \
        -e "s|@SMB_PASS@|$SMB_PASS|g" \
        -e "s|@APP_PORT@|$APP_PORT|g" > "$2.tmp"
    [[ "${3:-}" == crlf ]] && sed -i 's/$/\r/' "$2.tmp"
    mv "$2.tmp" "$2"
}

# ---------- users, folders, app code ----------
log "Installing the app to $OPT"
getent group froggyboot >/dev/null || groupadd --system froggyboot
id froggyboot >/dev/null 2>&1 || useradd --system --gid froggyboot --home-dir /var/lib/froggyboot \
    --no-create-home --shell /usr/sbin/nologin froggyboot
usermod -aG froggyboot www-data
id "$SMB_USER" >/dev/null 2>&1 || useradd --system --no-create-home --shell /usr/sbin/nologin "$SMB_USER"
usermod -aG froggyboot "$SMB_USER"
if [[ "$REPO" != "$OPT" ]]; then
    install -d "$OPT"
    rm -rf "${OPT:?}/froggyboot" "${OPT:?}/recipes" "${OPT:?}/server" "${OPT:?}/etc" "${OPT:?}/scripts"
    cp -r "$REPO/froggyboot" "$REPO/recipes" "$REPO/server" "$REPO/etc" "$REPO/scripts" "$OPT/"
    install -m 755 "$REPO/install.sh" "$OPT/install.sh"
fi
find "$OPT" -name __pycache__ -prune -exec rm -rf {} +
tr -d '\r' < "$OPT/server/etc/froggyboot-cli" > /usr/local/bin/froggyboot
chmod 755 /usr/local/bin/froggyboot
for f in menu.yml hosts.yml; do
    [[ -f "$ETC/$f" ]] || install -m 640 "$OPT/etc/$f" "$ETC/$f"
done
chown -R root:froggyboot "$ETC"; chmod 750 "$ETC"; chmod 640 "$ETC"/*.yml "$ETC/config.env"

install -d -m 755 "$SRV_ROOT"/{tftp,http} "$SRV_ROOT"/http/{linux,tools,blobs/clonezilla} \
    "$SRV_ROOT"/http/secure/{install,console} "$SRV_ROOT"/http/danger/{clonezilla,shredos} "$IMAGES"
install -d -m 2770 -o "$SMB_USER" -g froggyboot "$INCOMING" "$INCOMING/reports" "$INCOMING/backups"

log "Rendering WinPE scripts and tools"
render "$OPT/server/embed.ipxe" "$SRV_ROOT/embed.ipxe"
while IFS= read -r -d '' f; do
    rel="${f#"$OPT/server/http/"}"
    case "$f" in
        *.cmd|*.ini) render "$f" "$SRV_ROOT/http/$rel" crlf ;;
        *)           render "$f" "$SRV_ROOT/http/$rel" ;;
    esac
done < <(find "$OPT/server/http" -type f -print0)
# install.cmd holds the Samba password: only nginx (group froggyboot) may read it.
chown root:froggyboot "$SRV_ROOT/http/secure/install/install.cmd"
chmod 640 "$SRV_ROOT/http/secure/install/install.cmd"
# Hand-written menus from v0.1 are replaced by generated ones.
rm -f "$SRV_ROOT/http/linux.ipxe" "$SRV_ROOT/http/tools.ipxe"
for old in secure/windows.ipxe danger/danger.ipxe; do
    [[ -f "$SRV_ROOT/http/$old" ]] && ! grep -q 'Generated by froggyboot' "$SRV_ROOT/http/$old" && rm -f "$SRV_ROOT/http/$old"
done

# ---------- TLS (optional) ----------
TLS="$ETC/tls"
if [[ "$HTTPS" == yes ]]; then
    install -d -m 750 -g froggyboot "$TLS"
    if [[ ! -f "$TLS/ca.crt" ]]; then
        log "Creating a local CA for iPXE HTTPS (valid 20 years)"
        openssl req -x509 -newkey rsa:3072 -nodes -days 7300 -subj "/CN=Froggyboot local CA" \
            -keyout "$TLS/ca.key" -out "$TLS/ca.crt" 2>/dev/null
    fi
    if [[ ! -f "$TLS/server.crt" ]] || ! openssl x509 -in "$TLS/server.crt" -noout -subject | grep -q "CN *= *$SERVER_IP\$"; then
        log "Issuing the server certificate for $SERVER_IP"
        openssl req -newkey rsa:2048 -nodes -subj "/CN=$SERVER_IP" -keyout "$TLS/server.key" -out "$TLS/server.csr" 2>/dev/null
        openssl x509 -req -in "$TLS/server.csr" -CA "$TLS/ca.crt" -CAkey "$TLS/ca.key" -CAcreateserial -days 3650 \
            -extfile <(printf 'subjectAltName=IP:%s,DNS:%s\nextendedKeyUsage=serverAuth\n' "$SERVER_IP" "$SERVER_IP") \
            -out "$TLS/server.crt" 2>/dev/null
        rm -f "$TLS/server.csr"
    fi
    chmod 640 "$TLS"/*.key; chgrp froggyboot "$TLS"/*
    install -m 644 "$TLS/ca.crt" "$SRV_ROOT/http/froggyboot-ca.crt"
fi

# ---------- iPXE (rebuilt when its inputs change) ----------
params="ip=$SERVER_IP https=$HTTPS embed=$(sha256sum "$SRV_ROOT/embed.ipxe" | cut -c1-16)"
[[ "$HTTPS" == yes ]] && params+=" ca=$(sha256sum "$TLS/ca.crt" | cut -c1-16)"
if [[ $REBUILD_IPXE -eq 1 || ! -f "$SRV_ROOT/tftp/ipxe.efi" || "$(cat "$SRV_ROOT/tftp/.build" 2>/dev/null)" != "$params" ]]; then
    log "Building iPXE ($params) - takes a few minutes"
    if [[ -d "$IPXE_SRC/.git" ]]; then git -C "$IPXE_SRC" pull -q; else git clone -q https://github.com/ipxe/ipxe.git "$IPXE_SRC"; fi
    {
        echo "#define REBOOT_CMD"; echo "#define POWEROFF_CMD"; echo "#define PING_CMD"; echo "#define NSLOOKUP_CMD"
        [[ "$HTTPS" == yes ]] && echo "#define DOWNLOAD_PROTO_HTTPS"
    } > "$IPXE_SRC/src/config/local/general.h"
    extra=(EMBED="$SRV_ROOT/embed.ipxe")
    [[ "$HTTPS" == yes ]] && extra+=(TRUST="$TLS/ca.crt")
    [[ -n "$CROSS" ]] && extra+=(CROSS="$CROSS")
    make -s -C "$IPXE_SRC/src" -j"$(nproc)" bin/undionly.kpxe bin-x86_64-efi/ipxe.efi "${extra[@]}"
    install -m 644 "$IPXE_SRC/src/bin/undionly.kpxe" "$IPXE_SRC/src/bin-x86_64-efi/ipxe.efi" "$SRV_ROOT/tftp/"
    echo "$params" > "$SRV_ROOT/tftp/.build"
else
    log "iPXE is up to date"
fi

if [[ ! -f "$SRV_ROOT/http/secure/wimboot" ]]; then
    log "Downloading wimboot"
    curl -fsSL -o "$SRV_ROOT/http/secure/wimboot" https://github.com/ipxe/wimboot/releases/latest/download/wimboot
fi

# ---------- dnsmasq ----------
log "Configuring dnsmasq (proxy-DHCP on $IFACE)"
render "$OPT/server/etc/dnsmasq-netboot.conf" /etc/dnsmasq.d/netboot.conf
systemctl enable -q dnsmasq
systemctl restart dnsmasq

# ---------- passwords ----------
for pair in "windows:tech" "danger:admin"; do
    zone="${pair%%:*}"; user="${pair#*:}"
    file="/etc/nginx/netboot-$zone.htpasswd"
    if [[ ! -s "$file" ]]; then
        log "Set the $zone password for user '$user' (use different passwords!)"
        htpasswd -c "$file" "$user"
    fi
    chown root:froggyboot "$file"; chmod 640 "$file"
done
rm -f /etc/nginx/netboot-danger-macs.conf  # v0.1 leftover: the app checks the whitelist now

# ---------- app ----------
log "Rendering menus and starting the app"
froggyboot check
froggyboot render
tr -d '\r' < "$OPT/server/etc/froggyboot.service" > /etc/systemd/system/froggyboot.service
systemctl daemon-reload
systemctl enable -q froggyboot
systemctl restart froggyboot

# ---------- nginx ----------
log "Configuring nginx"
render "$OPT/server/etc/nginx-netboot.conf" /etc/nginx/sites-available/netboot
if [[ "$HTTPS" == yes ]]; then
    listen="    listen 443 ssl default_server;\n    ssl_certificate $TLS/server.crt;\n    ssl_certificate_key $TLS/server.key;"
    only='        if ($scheme = http) { return 403; }'
else
    listen=""; only=""
fi
sed -i -e "s|^@HTTPS_LISTEN@$|$listen|" -e "s|^@HTTPS_ONLY@$|$only|" /etc/nginx/sites-available/netboot
ln -sf /etc/nginx/sites-available/netboot /etc/nginx/sites-enabled/netboot
if [[ -L /etc/nginx/sites-enabled/default ]]; then
    warn "Disabling the default nginx site (it also wants default_server on port 80)"
    rm /etc/nginx/sites-enabled/default
fi
tr -d '\r' < "$OPT/server/etc/logrotate-netboot" > /etc/logrotate.d/netboot
chmod 644 /etc/logrotate.d/netboot
nginx -t -q
systemctl enable -q nginx
systemctl restart nginx   # restart, not reload: www-data joined the froggyboot group

# ---------- Samba ----------
log "Configuring Samba shares [images] (read-only) and [incoming] (reports, backups)"
render "$OPT/server/etc/samba-netboot.conf" /etc/samba/netboot.conf
grep -q '^include = /etc/samba/netboot.conf' /etc/samba/smb.conf || \
    printf '\n# Froggyboot\ninclude = /etc/samba/netboot.conf\n' >> /etc/samba/smb.conf
printf '%s\n%s\n' "$SMB_PASS" "$SMB_PASS" | smbpasswd -s -a "$SMB_USER" >/dev/null
chown root:root "$IMAGES"; chmod 755 "$IMAGES"
testparm -s >/dev/null 2>&1 || die "testparm reports an error in smb.conf"
systemctl enable -q smbd
systemctl restart smbd

# ---------- summary ----------
sleep 1
systemctl is-active -q froggyboot || warn "froggyboot service is not running: journalctl -u froggyboot"
scheme=http; [[ "$HTTPS" == yes ]] && scheme=https
log "Done."
echo "  Panel:   $scheme://$SERVER_IP/panel/  (user admin)"
echo "  Images:  froggyboot recipes; froggyboot add debian ubuntu-server alpine"
echo "  Windows: install.wim -> $IMAGES, WinPE files -> $SRV_ROOT/http/secure/ (see docs/INSTALL.md)"
echo "  Menu:    edit $ETC/menu.yml and $ETC/hosts.yml, then: froggyboot render"

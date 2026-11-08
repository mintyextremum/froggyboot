#!/usr/bin/env bash
# Build froggyboot_<version>_all.deb into ./build/.
# The package installs the code to /opt/froggyboot; the user then runs
# `sudo froggyboot-setup` (= install.sh), which asks questions and builds iPXE.
set -euo pipefail
cd "$(dirname "$0")/.."
VER="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' froggyboot/__init__.py)"
ROOT="build/deb"
rm -rf "$ROOT"; mkdir -p "$ROOT/DEBIAN" "$ROOT/opt/froggyboot" "$ROOT/usr/sbin"
cp -r froggyboot recipes server etc scripts "$ROOT/opt/froggyboot/"
install -m 755 install.sh "$ROOT/opt/froggyboot/install.sh"
find "$ROOT" -name __pycache__ -prune -exec rm -rf {} +
ln -s /opt/froggyboot/install.sh "$ROOT/usr/sbin/froggyboot-setup"
cat > "$ROOT/DEBIAN/control" <<EOF
Package: froggyboot
Version: $VER
Section: admin
Priority: optional
Architecture: all
Maintainer: Froggyboot contributors <noreply@github.com>
Depends: python3, python3-fastapi, python3-uvicorn, python3-jinja2, python3-yaml, python3-passlib,
 dnsmasq, nginx, samba, apache2-utils, curl, openssl, git, make, gcc, libc6-dev, perl, liblzma-dev, mtools,
 libarchive-tools, wimtools
Homepage: https://github.com/mintyextremum/froggyboot
Description: PXE boot menu server for computer classrooms
 Network boot menu with Linux installers, live tools and password-protected
 Windows installation, a web panel, one-time codes, approvals and logging.
 Run "sudo froggyboot-setup" after installing.
EOF
cat > "$ROOT/DEBIAN/postinst" <<'EOF'
#!/bin/sh
set -e
if [ "$1" = configure ]; then
    if [ -f /etc/froggyboot/config.env ]; then
        echo "Froggyboot updated. Apply with: sudo froggyboot-setup"
    else
        echo "Froggyboot installed. Configure it with: sudo froggyboot-setup"
    fi
fi
EOF
chmod 755 "$ROOT/DEBIAN/postinst"
mkdir -p build
dpkg-deb --build --root-owner-group "$ROOT" "build/froggyboot_${VER}_all.deb"
echo "build/froggyboot_${VER}_all.deb"

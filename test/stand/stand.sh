#!/usr/bin/env bash
# check:       boot the VM headless, expect the menu and an automatic local-disk boot.
# interactive: the VM's serial console in your terminal (Ctrl-A X quits QEMU);
#              panel at http://localhost:8080/panel/ (admin / admin).
set -euo pipefail
MODE="${1:-check}"
VM_MAC=52-54-00-12-34-56

mkdir -p /etc/froggyboot /var/lib/froggyboot /srv/netboot/http /srv/images/windows /srv/froggyboot/incoming/reports
cat > /etc/froggyboot/config.env <<CONF
SERVER_IP=10.0.2.2
IFACE=lo
NET_CIDR=10.0.2.0/24
SMB_PASS=standtest1
DANGER_MACS="$VM_MAC"
CONF
cp /opt/froggyboot/etc/menu.yml /etc/froggyboot/menu.yml
cat > /etc/froggyboot/hosts.yml <<CONF
rooms:
  - name: stand
    cols: 2
    hosts:
      - {name: stand-pc, mac: $VM_MAC}
CONF
htpasswd -bc /etc/nginx/netboot-windows.htpasswd tech tech 2>/dev/null
htpasswd -bc /etc/nginx/netboot-danger.htpasswd admin admin 2>/dev/null
sed -e 's|@NET_CIDR@|10.0.2.0/24|' -e 's|@APP_PORT@|8070|' -e '/^@HTTPS_LISTEN@$/d' -e '/^@HTTPS_ONLY@$/d' \
    -e 's|allow 127.0.0.1;|allow all;|' \
    /opt/froggyboot/server/etc/nginx-netboot.conf > /etc/nginx/sites-enabled/default
python3 -m froggyboot render
python3 -m froggyboot serve &
for _ in $(seq 50); do curl -fs http://127.0.0.1:8070/menu.ipxe >/dev/null 2>&1 && break; sleep 0.2; done
nginx

QEMU=(qemu-system-x86_64 -m 256 -boot n -no-reboot
      -netdev "user,id=n0,tftp=/srv/netboot/tftp,bootfile=undionly.kpxe"
      -device "e1000,netdev=n0,mac=${VM_MAC//-/:}")

if [[ "$MODE" == interactive ]]; then
    exec "${QEMU[@]}" -nographic
fi

timeout 150 "${QEMU[@]}" -display none -serial file:/tmp/serial.log &
qpid=$!
ok=0
for _ in $(seq 140); do
    sleep 1
    if sqlite3 /var/lib/froggyboot/state.db "select 1 from events where mac='$VM_MAC' and kind='local'" | grep -q 1; then
        ok=1; break
    fi
done
kill "$qpid" 2>/dev/null || true
echo "---- events"
sqlite3 /var/lib/froggyboot/state.db "select datetime(ts,'unixepoch'), mac, kind, detail from events"
echo "---- serial (tail)"
tail -c 2000 /tmp/serial.log | tr -d '\033' | sed 's/\[[0-9;]*[A-Za-z]//g' | tail -n 15
grep -q "NETBOOT" /tmp/serial.log || { echo "FAIL: menu never appeared"; exit 1; }
grep -q "set host stand-pc" <(curl -s "http://127.0.0.1/menu.ipxe?mac=$VM_MAC") || { echo "FAIL: dynamic menu"; exit 1; }
[[ $ok == 1 ]] || { echo "FAIL: no automatic local-disk boot recorded"; exit 1; }
echo "PASS: VM got the menu from the server and booted the local disk after the timeout"

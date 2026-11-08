# Troubleshooting

Start with the logs on the server:

```bash
journalctl -u dnsmasq -f            # PXE / proxy-DHCP / TFTP
tail -f /var/log/nginx/netboot.log  # which PC asked for which file, and the HTTP status
tail -f /var/log/nginx/error.log
```

The menu header shows the server IP, the client's IP and MAC, and the firmware mode. A photo of the screen is usually enough to diagnose a problem.

| Symptom | Likely cause | Fix |
| --- | --- | --- |
| PC never sees PXE, or says "No boot filename received" | dnsmasq not answering on that network | Check `IFACE` and `NET_CIDR` in `config.env`; `journalctl -u dnsmasq` should log `PXE(…)` lines. Firewall: allow UDP 67, 69, 4011 |
| iPXE starts, then "Netboot server unavailable" | Wrong `SERVER_IP` baked into iPXE, or nginx is down | `sudo ./install.sh --rebuild-ipxe`; `systemctl status nginx`; firewall: TCP 80 |
| `403` for every file | Client is outside `NET_CIDR` | Fix `NET_CIDR` and run `install.sh` again |
| `403` on the danger zone with the right password | MAC not in `DANGER_MACS` | Add it, run `install.sh` again |
| UEFI: "Boot from local disk" opens firmware setup | No entry after network in the UEFI boot order | Put the Windows/Linux boot manager after network boot |
| BIOS: "Boot from local disk" hangs | Disk isn't `0x80`, or there's no bootloader on it | Remove PXE from the boot order temporarily, or check the disk |
| Nothing boots with Secure Boot on | iPXE isn't signed | Disable Secure Boot (signed chain is on the roadmap) |
| Item returns to the menu immediately | Image missing | The last lines of `install.sh` list `[missing]` files |
| WinPE: "cannot reach \\server\images" | No network driver in `boot.wim`, or Samba down | Add the NIC driver to `/srv/images/windows/drivers/` or to `boot.wim`; `systemctl status smbd`; TCP 445 |
| WinPE: disk list is empty | Intel VMD / RST controller | Put the Intel RST VMD `.inf` driver in `/srv/images/windows/drivers/`, or switch the controller to AHCI in the BIOS |
| Windows 11 refuses old hardware | TPM / CPU checks | Use Windows 10, or an `unattend.xml` that matches your licence and policy |
| `dism /Apply-Image` fails | Corrupt or incomplete WIM | Re-copy it and compare its SHA-256 with the original |
| Ubuntu installer stops while loading the ISO | Not enough RAM (the whole ISO goes into RAM) | 8 GB RAM, or use Debian netinstall |
| Neighbouring rooms see the menu | Same broadcast domain | Check `IFACE`; ask the network admin about VLANs |

Still stuck? Open an issue with the menu header photo, firmware mode, and the matching lines from both logs.

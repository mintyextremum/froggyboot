# Froggyboot

**A self-hosted network boot menu for computer labs, classrooms and small offices.**
Any PC on the network boots over PXE and gets one menu with Linux installers, live/rescue systems, hardware tests and **Windows installation**. Images are stored on your own Debian server, so it works offline and without USB sticks.

[Русская версия](README.ru.md)

```
NETBOOT 192.168.1.10   this PC: 192.168.1.57  00-1a-2b-3c-4d-5e  efi
 Safe
   [d] Boot from local disk  (default in 10 s)
   [l] Linux installers                       >
   [t] Live systems and tools                 >
 Erases disks - password required
   [!] Windows install                        >
   [!] Danger zone                            >
```

## Why Froggyboot

You look after 1–10 rooms of PCs, you have no Windows Server or SCCM budget, and the router belongs to someone else. You do have an old PC that can run Debian.

- **Works next to an existing DHCP server.** dnsmasq runs in proxy-DHCP mode: the router keeps assigning IP addresses, and Froggyboot only answers PXE requests. You don't change anything on the network.
- **Windows included.** Public menus like netboot.xyz can't ship Windows. Your local server can, because the images are yours and never leave the LAN.
- **Safe by default.** With no key pressed, the local disk boots after 10 seconds. If the server is down, the local disk boots too. So network boot can stay first in the BIOS boot order on every PC.
- **Destructive actions are hard to reach.** Anything that erases a disk sits behind a disclaimer, a password checked by the server, and a typed confirmation.
- **Every choice is logged.** You see which PC (MAC, IP) picked which item, and when.
- **No custom backend.** It's built from dnsmasq, nginx, Samba and plain-text `.ipxe` files. You can read every line and change it.

### Compared with similar tools

| | Froggyboot | netboot.xyz | WDS + MDT | FOG | iVentoy |
| --- | --- | --- | --- | --- | --- |
| Windows install | yes | no | yes | via cloning | yes |
| Linux installers / live | yes | yes | no | limited | yes |
| Needs Windows Server | no | no | yes | no | no |
| Works next to a foreign DHCP | yes | yes | with tweaks | yes | yes |
| Password-protected destructive items | yes | no | n/a | n/a | no |
| Open source | yes | yes | no | yes | no |

Treat this table as an overview. Check the current versions of the other tools before relying on it.

## What's in the menu

| Section | Item | Protection | Internet |
| --- | --- | --- | --- |
| Main | Boot from local disk (default) | – | no |
| Linux | Debian 13 netinstall | the installer asks before partitioning | for packages |
| Linux | Ubuntu Server LTS (ISO in RAM, 8 GB RAM) | the installer asks | no |
| Tools | Memtest86+, GParted Live, SystemRescue, iPXE shell, reboot / power off | – | no |
| Windows | Windows 10 / 11 install, WinPE console | disclaimer + password + `ERASE` + disk choice in WinPE | no |
| Danger zone | Clonezilla, ShredOS (nwipe) | separate password + MAC whitelist (+ `WIPE`) | no |

Adding your own entries: see [docs/CUSTOMIZING.md](docs/CUSTOMIZING.md).

## How it works

```
 PC firmware ──PXE──> router DHCP (IP)  +  dnsmasq proxy-DHCP (boot file name)
      │
      └─TFTP─> iPXE (undionly.kpxe / ipxe.efi, with an embedded script)
                 │
                 └─HTTP─> nginx: menu.ipxe ──> kernels, initrds, WinPE
                                │                 (/secure, /danger: basic auth)
                                └─ access log: time, IP, MAC, user, file
 WinPE install.cmd ──SMB (read-only)──> Samba: install.wim, drivers, unattend.xml
```

1. The PC boots over PXE. The router gives it an IP address, and dnsmasq adds the iPXE file name.
2. iPXE loads the menu over HTTP. If the server doesn't answer, the PC boots its local disk.
3. After 10 seconds of inactivity, the menu boots the local disk: `exit` on UEFI, `sanboot` on BIOS.
4. Protected items go through the warning, a login, and a typed `ERASE`. Only then does nginx serve the files.
5. For Windows, wimboot loads WinPE into RAM. Then `install.cmd` lists the disks and waits for `ERASE <disk number>`.

## Requirements

- A Debian 13 server with a static IP in the PC network. Any old PC works. Plan disk space for the images: about 30–60 GB.
- Client PCs that can boot over the network (PXE), in BIOS or UEFI mode.
- On UEFI, the boot order must be **network, then disk**. On UEFI, `exit` hands control to the next boot entry.
- Secure Boot off on clients for now (signed chain is on the roadmap).
- Let the network admin know first. Show them that this is proxy-DHCP, not a second DHCP server.

## Quick start

```bash
git clone https://github.com/mintyextremum/froggyboot.git
cd froggyboot
cp config.env.example config.env
nano config.env                  # SERVER_IP, IFACE, NET_CIDR, SMB_PASS, DANGER_MACS
sudo ./install.sh                # asks for the 'tech' (Windows) and 'admin' (danger zone) passwords
sudo ./scripts/fetch-debian.sh   # first working menu entry, checksum-verified
```

Now boot a PC from the network. The menu should appear, and with no key pressed, the local disk boots after 10 seconds.

`install.sh` is safe to run again. It never touches images in `/srv`, and it keeps existing passwords. If you change `SERVER_IP` or `server/embed.ipxe`, run `sudo ./install.sh --rebuild-ipxe`.

If a firewall (`ufw`, `nftables`) is enabled, allow UDP 67, 69 and 4011, and TCP 80 and 445 from the PC subnet.

## Adding images

An image that isn't there yet doesn't break anything: its menu item just returns to the menu. At the end, `install.sh` prints which images are `[ok]` and which are `[missing]`.

Paths are relative to `/srv/netboot/http/`.

| Item | What to put there |
| --- | --- |
| Debian 13 | `sudo ./scripts/fetch-debian.sh` |
| Ubuntu Server | `casper/vmlinuz` and `casper/initrd` from the ISO → `linux/ubuntu/`, the ISO itself → `linux/ubuntu/ubuntu-server.iso` |
| Memtest86+ | `memtest64.bin` and `memtest64.efi` (the "Linux binary" archive on memtest.org) → `tools/memtest/` |
| GParted Live | `live/vmlinuz`, `live/initrd.img`, `live/filesystem.squashfs` from the ZIP → `tools/gparted/` |
| SystemRescue | the whole ISO extracted → `tools/sysrescue/` (you should get `sysresccd/boot/x86_64/vmlinuz`) |
| Clonezilla | `live/vmlinuz`, `live/initrd.img` → `danger/clonezilla/`. `live/filesystem.squashfs` → `blobs/clonezilla/` (public on purpose, so the password never lands on the kernel command line) |
| ShredOS | `bzImage` → `danger/shredos/`. Pick a release that ships a separate kernel, not only a USB image |
| WinPE | `BCD`, `boot.sdi`, `boot.wim` from the Windows ADK + WinPE add-on → `secure/`. `install.sh` downloads `wimboot` |
| Windows | `install.wim` or `.esd` from an official Microsoft ISO → `/srv/images/windows/` |

**Windows extras** in `/srv/images/windows/`:

- `drivers/`: `.inf` drivers (Intel VMD/RST, network). They are loaded before the disk list is shown and added to the installed system.
- `unattend.xml`: if present, it is copied to `Windows\Panther\`.

You don't rebuild `boot.wim` when you edit the scripts. wimboot injects `winpeshl.ini` and `install.cmd` at boot time.

**Checksums.** Compare each image with the official hash before you add it to the list:

```bash
cd /srv/netboot/http && sha256sum tools/memtest/memtest64.efi   # compare with the vendor's sum
sha256sum tools/memtest/memtest64.efi >> SHA256SUMS
sudo ./scripts/verify-images.sh
```

## Safety layers

**Layer 1, the iPXE menu**

1. The local disk boots by default after 10 seconds. `Esc` on the main menu boots the local disk too.
2. Destructive items are marked `[!]` and have no hotkeys, so one stray keypress can't select them.
3. A disclaimer screen comes first. "Back" is preselected, and it auto-returns after 30 seconds.
4. Login and password are checked by nginx (HTTP basic auth). Without them, the Windows menu and WinPE files are simply not served.
5. You type `ERASE` in capitals.

**Layer 2, WinPE**

6. The disk list is shown, and you pick the disk number by hand and type `ERASE <number>`. Empty input cancels and reboots. Partitioning only ever uses the chosen disk.

**Danger zone.** It has a separate `admin` password, and a MAC whitelist enforced by nginx on the whole `/danger/` folder.

**Logging.** Each request carries `?mac=...`, so `/var/log/nginx/netboot.log` shows the time, IP, MAC, user and file. Logs are kept for 8 weeks.

```bash
grep -E 'secure|danger' /var/log/nginx/netboot.log
```

**Limits, stated honestly.** Read [SECURITY.md](SECURITY.md). In short: the password travels over plain HTTP, and MAC addresses can be spoofed. This protects against accidents and curious users, not against an attacker on the same LAN.

## Repository layout

| Path | Goes to |
| --- | --- |
| `server/embed.ipxe` | embedded into `undionly.kpxe` and `ipxe.efi` |
| `server/http/*.ipxe` | `/srv/netboot/http/`: main menu, Linux, tools |
| `server/http/secure/` | Windows menu, `install.cmd`, `winpeshl.ini` (behind the technician password) |
| `server/http/danger/` | Clonezilla, ShredOS (behind the admin password and the MAC whitelist) |
| `server/etc/` | dnsmasq, nginx, Samba, logrotate templates |
| `install.sh` | installs packages, renders templates, builds iPXE, enables services |
| `scripts/` | `fetch-debian.sh`, `verify-images.sh` |

Templates use placeholders like `@SERVER_IP@`. `install.sh` fills them in from `config.env`.

## Troubleshooting

Common problems and fixes are in [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md): no menu, UEFI drops into firmware setup, WinPE can't find disks, and more.

## Roadmap

- **v0.1 (now):** menu, Debian/Ubuntu, tools, password-protected Windows, logging.
- **v0.2–0.3:** generate menus from one YAML file; Fedora, Arch, Alpine, Mint; apt-cacher-ng; HTTPS inside iPXE.
- **v1.0:** web panel (logs, passwords, assignments), unattended install of a whole room, `.deb` package, Secure Boot via shim.

Ideas and pull requests are welcome. See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licensing notes

Froggyboot is released under the [MIT](LICENSE) license. iPXE and wimboot are downloaded and built on your server and keep their own GPL licenses. Windows images must come from Microsoft and stay inside your network. Never publish them on a public mirror. Activation is the PC owner's responsibility.

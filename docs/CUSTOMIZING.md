# Customizing the menu

The menus are plain iPXE scripts in `server/http/`. Edit them in the repository, then run `sudo ./install.sh` to render and copy them to `/srv/netboot/http/`. You don't need to rebuild iPXE for menu changes.

Variables available in every menu (set in `menu.ipxe`):

| Variable | Value |
| --- | --- |
| `${srv}` | server IP |
| `${base}` | `http://<server IP>` |
| `${q}` | `mac=<client MAC>`. Append `?${q}` to every URL so the access log shows the PC |
| `${platform}` | `efi` or `pcbios` |

## Add a Linux live system or installer

1. Put the kernel and initrd under `/srv/netboot/http/linux/<name>/` and record their checksums in `SHA256SUMS`.
2. Add an item and a label to `server/http/linux.ipxe` or `tools.ipxe`:

```ipxe
item alpine  Alpine Linux (latest stable) - needs Internet

:alpine
set a ${base}/linux/alpine
kernel ${a}/vmlinuz-lts?${q} initrd=initramfs-lts alpine_repo=https://dl-cdn.alpinelinux.org/alpine/latest-stable/main modloop=${a}/modloop-lts ip=dhcp
initrd -n initramfs-lts ${a}/initramfs-lts?${q}
boot || goto menu
```

Rules of thumb:

- Always give the initrd an explicit name with `initrd -n <name>`, and use the same name in `initrd=<name>` on the kernel line. UEFI kernels need this match.
- End with `boot || goto menu`, so a missing file returns to the menu instead of hanging.
- Keep the text ASCII. The iPXE console can't show Cyrillic.

## Add something that erases disks

Anything that installs without asking (preseed, autoinstall, kickstart, cloning, wiping) goes into `server/http/danger/danger.ipxe`, never into the open menus. Use `${dz}` URLs there so nginx checks the password and the MAC whitelist, and `clear password` before `boot`.

## Change the timeout or default

In `menu.ipxe`: `choose --default local --timeout 10000 target`. The timeout is in milliseconds. Keep `local` as the default if network boot stays first in the BIOS boot order.

## Allow another PC into the danger zone

Add its MAC to `DANGER_MACS` in `config.env` and run `sudo ./install.sh` again.

## Change passwords

```bash
sudo htpasswd /etc/nginx/netboot-windows.htpasswd tech
sudo htpasswd /etc/nginx/netboot-danger.htpasswd admin
```

You can add more technicians with `htpasswd <file> <name>` (without `-c`). The log will show who did what.

# Установка

## Требования

- Debian 13 со статическим IP в сети ПК, 30–60 ГБ под образы.
- ПК грузятся по PXE, BIOS или UEFI. В UEFI порядок загрузки: сеть, потом диск. Secure Boot выключен.
- Если включён фаервол: UDP 67, 69, 4011 и TCP 80, 445 из подсети ПК.

## Шаги

```bash
git clone https://github.com/mintyextremum/froggyboot.git
cd froggyboot
cp config.env.example config.env
nano config.env                  # SERVER_IP, IFACE, NET_CIDR, SMB_PASS, DANGER_MACS
sudo ./install.sh                # пароли tech (Windows) и admin (опасная зона)
sudo ./scripts/fetch-debian.sh
```

Повторный запуск `install.sh` образы и пароли не трогает. После смены `SERVER_IP` или `server/embed.ipxe`: `sudo ./install.sh --rebuild-ipxe`.

## Образы

Пути от `/srv/netboot/http/`. Отсутствующий образ возвращает в меню, `install.sh` в конце печатает `[ok]` / `[missing]`.

| Пункт | Файлы |
| --- | --- |
| Debian 13 | `scripts/fetch-debian.sh` |
| Ubuntu Server | `casper/vmlinuz`, `casper/initrd` → `linux/ubuntu/`; ISO → `linux/ubuntu/ubuntu-server.iso` |
| Memtest86+ | `memtest64.bin`, `memtest64.efi` → `tools/memtest/` |
| GParted Live | `live/vmlinuz`, `live/initrd.img`, `live/filesystem.squashfs` → `tools/gparted/` |
| SystemRescue | весь ISO → `tools/sysrescue/` |
| Clonezilla | `live/vmlinuz`, `live/initrd.img` → `danger/clonezilla/`; `live/filesystem.squashfs` → `blobs/clonezilla/` |
| ShredOS | `bzImage` → `danger/shredos/` |
| WinPE | `BCD`, `boot.sdi`, `boot.wim` из Windows ADK → `secure/` |
| Windows | `install.wim` / `.esd` → `/srv/images/windows/`; драйверы → `drivers/`; `unattend.xml` по желанию |

Контрольные суммы: `sha256sum <файл> >> /srv/netboot/http/SHA256SUMS` после сверки с официальной, проверка — `sudo ./scripts/verify-images.sh`.

## Журнал

```bash
grep -E 'secure|danger' /var/log/nginx/netboot.log
```

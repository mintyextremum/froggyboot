# Установка

## Требования

- Debian 13 со статическим IP в сети ПК, amd64 или arm64 (Raspberry Pi 5). 30–60 ГБ под образы.
- ПК грузятся по PXE, BIOS или UEFI. В UEFI порядок загрузки: сеть, потом диск. Secure Boot выключен (см. [Secure Boot](SECUREBOOT.md)).
- Если включён фаервол: UDP 67, 69, 4011 и TCP 80, 443, 445 из подсети ПК.

## Из репозитория

```bash
git clone https://github.com/mintyextremum/froggyboot.git
cd froggyboot
sudo ./install.sh
```

## Из пакета

```bash
sudo apt install ./froggyboot_*_all.deb
sudo froggyboot-setup
```

Пакет лежит в разделе Releases на GitHub.

## Первый запуск

`install.sh` определяет интерфейс, IP и подсеть и спрашивает:

| Вопрос | Значение |
| --- | --- |
| Интерфейс, IP сервера, сеть ПК | по умолчанию — найденные значения |
| MAC для опасной зоны | можно оставить пустым и задать позже в `hosts.yml` |
| HTTPS | `y` — пароли идут по HTTPS, iPXE собирается с сертификатом сервера |
| Пароль `tech` | вход в зону Windows |
| Пароль `admin` | опасная зона и панель |

Ответы сохраняются в `/etc/froggyboot/config.env`. Пароль Samba генерируется сам. Для Telegram заполните `TELEGRAM_TOKEN` и `TELEGRAM_CHAT` и запустите `install.sh` снова.

Повторный запуск обновляет код и конфиги; образы, пароли, `menu.yml` и `hosts.yml` остаются. iPXE пересобирается сам, когда меняется IP, HTTPS или сертификат.

На Raspberry Pi и других ARM-серверах iPXE для ПК собирается кросс-компилятором x86-64.

## Файлы

| Путь | Что там |
| --- | --- |
| `/etc/froggyboot/config.env` | сеть, Samba, HTTPS, Telegram |
| `/etc/froggyboot/menu.yml` | пункты меню |
| `/etc/froggyboot/hosts.yml` | классы и ПК: MAC, имя, место на карте |
| `/etc/froggyboot/tls/` | центр сертификации и сертификат сервера (при HTTPS) |
| `/srv/netboot/http/` | меню, ядра, WinPE |
| `/srv/images/windows/` | `install.wim`, `drivers/`, `unattend.xml` |
| `/srv/froggyboot/incoming/` | отчёты WinPE и резервные копии `Users` |
| `/var/lib/froggyboot/state.db` | журнал, назначения, коды, отчёты о железе |
| `/var/log/nginx/netboot.log` | журнал запросов, 8 недель |

## Образы

```bash
froggyboot recipes
sudo froggyboot add debian ubuntu-server alpine fedora arch mint
```

Без рецепта (пути от `/srv/netboot/http/`):

| Пункт | Файлы |
| --- | --- |
| Memtest86+ | `memtest64.bin`, `memtest64.efi` → `tools/memtest/` |
| GParted Live | `live/vmlinuz`, `live/initrd.img`, `live/filesystem.squashfs` → `tools/gparted/` |
| SystemRescue, отчёт о железе | весь ISO → `tools/sysrescue/` |
| Clonezilla | `live/vmlinuz`, `live/initrd.img` → `danger/clonezilla/`; `live/filesystem.squashfs` → `blobs/clonezilla/` |
| ShredOS | `bzImage` → `danger/shredos/` |
| WinPE | `BCD`, `boot.sdi`, `boot.wim` из Windows ADK → `secure/` |
| Windows | `install.wim` / `.esd` → `/srv/images/windows/`; драйверы → `drivers/`; `unattend.xml` по желанию |

После копирования: `sudo froggyboot render` — пункт появится в меню. Контрольные суммы: `sha256sum <файл> >> /srv/netboot/http/SHA256SUMS`, проверка — `sudo /opt/froggyboot/scripts/verify-images.sh`.

## Тестовый стенд

Сервер и виртуальный ПК в одном контейнере, без настоящей сети:

```bash
docker build -t froggyboot-stand -f test/stand/Dockerfile .
docker run --rm -it -p 8080:80 froggyboot-stand interactive
```

Меню открывается в терминале (выход из QEMU — Ctrl-A, X), панель — http://localhost:8080/panel/ (admin / admin). `docker run --rm froggyboot-stand check` — автоматическая проверка, её же запускает CI.

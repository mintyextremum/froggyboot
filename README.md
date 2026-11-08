# Froggyboot

Локальное меню сетевой загрузки для компьютерного класса, по духу как netboot.xyz. Сервер на Debian 13, в меню установщики Linux, live-системы, утилиты и Windows. Работает рядом с чужим роутером: dnsmasq в режиме proxy-DHCP ничего не меняет в сети, а только отвечает на PXE-запросы.

**Безопасно по умолчанию.** Если ничего не нажать, через 10 секунд грузится локальный диск. Если сервер недоступен, тоже грузится диск. Всё, что стирает диски, закрыто дисклеймером, паролем (его проверяет nginx) и вводом слова-подтверждения.

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

## Что в репозитории

| Путь | Куда попадает на сервере |
| --- | --- |
| `server/embed.ipxe` | вшивается в `undionly.kpxe` и `ipxe.efi` |
| `server/http/*.ipxe` | `/srv/netboot/http/`: главное меню, Linux, утилиты |
| `server/http/secure/` | Windows: `windows.ipxe`, `install.cmd`, `winpeshl.ini` (пароль техника) |
| `server/http/danger/` | `danger.ipxe`: Clonezilla, ShredOS (пароль админа + белый список MAC) |
| `server/etc/` | шаблоны конфигов dnsmasq, nginx, Samba, logrotate |
| `install.sh` | ставит пакеты, подставляет настройки, собирает iPXE, включает службы |
| `scripts/fetch-debian.sh` | скачивает сетевой установщик Debian и сверяет SHA-256 |
| `scripts/verify-images.sh` | перепроверяет все образы по `/srv/netboot/http/SHA256SUMS` |
| `docs/PLACARD.md` | дисклеймер на русском для таблички в классе |

В шаблонах стоят метки `@SERVER_IP@`, `@IFACE@`, `@NET_CIDR@` и другие. `install.sh` заменяет их значениями из `config.env`.

## Установка

На чистом Debian 13 со статическим IP в сети класса:

```bash
git clone <repo> froggyboot && cd froggyboot
cp config.env.example config.env
nano config.env          # SERVER_IP, IFACE, NET_CIDR, SMB_PASS, DANGER_MACS
sudo ./install.sh        # спросит пароли: tech (Windows) и admin (опасная зона)
sudo ./scripts/fetch-debian.sh
```

Скрипт можно запускать повторно: образы в `/srv` он не трогает, пароли не перезаписывает. Если сменился `SERVER_IP` или изменён `embed.ipxe`, запусти `sudo ./install.sh --rebuild-ipxe`.

Перед первым запуском:

- **Предупреди сисадмина сети.** Покажи, что это proxy-DHCP: IP по-прежнему раздаёт роутер.
- **Настрой порядок загрузки на ПК: «сеть, потом диск».** В UEFI команда `exit` передаёт управление следующему пункту порядка загрузки. Если диск стоит раньше сети, меню не появится. Если после сети ничего нет, машина вернётся в меню прошивки.
- **Отключи Secure Boot.** В MVP iPXE не подписан.

## Образы

Пока образа нет, его пункт в меню просто возвращает в меню. В конце работы `install.sh` показывает список, где каждый образ отмечен как `[ok]` или `[missing]`.

| Пункт | Что положить |
| --- | --- |
| Debian 13 | `scripts/fetch-debian.sh` |
| Ubuntu Server | из ISO: `casper/vmlinuz` и `casper/initrd` в `linux/ubuntu/`, сам ISO — как `linux/ubuntu/ubuntu-server.iso`. ISO целиком грузится в ОЗУ, нужно 8 ГБ |
| Memtest86+ | `memtest64.bin` и `memtest64.efi` из архива «Linux binary» на memtest.org в `tools/memtest/` |
| GParted Live | из ZIP: `live/vmlinuz`, `live/initrd.img`, `live/filesystem.squashfs` в `tools/gparted/` |
| SystemRescue | распаковать весь ISO в `tools/sysrescue/` (должен появиться `sysresccd/boot/x86_64/vmlinuz`) |
| Clonezilla | `live/vmlinuz` и `live/initrd.img` в `danger/clonezilla/`, `live/filesystem.squashfs` в `blobs/clonezilla/` (открыт: пароль не должен попасть в командную строку ядра) |
| ShredOS | `bzImage` в `danger/shredos/`. Проверь, что в релизе есть отдельное ядро, а не только образ флешки |
| WinPE | из ADK + WinPE add-on: `BCD`, `boot.sdi`, `boot.wim` в `secure/` (`wimboot` скачивает `install.sh`) |
| Windows | `install.wim` (или `.esd`) из ISO с сайта Microsoft в `/srv/images/windows/` |

Пути указаны относительно `/srv/netboot/http/`.

**Проверка образов.** Сравни SHA-256 с официальным и только после этого добавь строку в список:

```bash
cd /srv/netboot/http && sha256sum tools/memtest/memtest64.efi >> SHA256SUMS
sudo ./scripts/verify-images.sh
```

### Дополнительно для Windows (папка `/srv/images/windows/`)

- `drivers/`: `.inf`-драйверы (Intel VMD/RST, сеть). `install.cmd` загружает их до показа дисков, а после установки добавляет в Windows.
- `unattend.xml`: при наличии копируется в `Windows\Panther\`.

`boot.wim` пересобирать не нужно: wimboot подкладывает `winpeshl.ini` и `install.cmd` в `X:\Windows\System32` при загрузке.

## Как устроена защита

**Рубеж 1, меню iPXE**

1. Через 10 секунд грузится локальный диск.
2. Опасные пункты отмечены `[!]`, у них нет горячих клавиш.
3. Экран-дисклеймер: по умолчанию выбрано «Back», через 30 секунд меню возвращается назад.
4. Логин и пароль. Их проверяет nginx: без пароля `windows.ipxe` и файлы WinPE просто не скачиваются.
5. Ввод `ERASE` заглавными.

**Рубеж 2, WinPE**

6. Список дисков, ручной выбор номера и ввод `ERASE <номер>`. Пустой ввод отменяет установку. Разметка берёт только выбранный диск.

**Опасная зона.** Отдельный пароль `admin` и белый список MAC (`DANGER_MACS`). Белый список nginx проверяет на всей папке `/danger/`, а не только на меню. Для ShredOS дополнительно нужно ввести `WIPE`.

**Журнал.** Каждый запрос несёт `?mac=...`, поэтому журнал nginx показывает время, IP, MAC, пользователя и выбранный файл:

```bash
grep -E 'secure|danger' /var/log/nginx/netboot.log
```

Журнал хранится 8 недель (logrotate).

**Честные ограничения.** Пароль идёт по обычному HTTP, MAC можно подделать, Secure Boot выключен. Всё это защищает от случайности и любопытных, но не от злоумышленника в той же сети. HTTPS в iPXE и подписанная цепочка shim → iPXE запланированы. Пароль Samba лежит в `install.cmd` за паролем техника, а у пользователя `winpe` права только на чтение.

## Дорожная карта

- **v0.1 (этот репозиторий):** меню, Debian/Ubuntu, утилиты, Windows за паролем, журнал.
- **v0.2–v0.3:** меню генерируется из YAML; Fedora, Arch, Alpine, Mint; apt-cacher-ng; HTTPS в iPXE.
- **v1.0:** веб-панель (журнал, пароли, назначения), автоустановка класса, `.deb`-пакет, Secure Boot.

Windows раздаётся только во внутренней сети: никаких публичных зеркал.

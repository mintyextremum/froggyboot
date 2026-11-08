# Меню, образы, рецепты

Меню задаётся в `/etc/froggyboot/menu.yml`. После правки: `sudo froggyboot render`. Главное меню приложение перечитывает само, подменю записываются в `/srv/netboot/http/`.

## Разделы

```yaml
timeout: 10          # секунд до загрузки с диска
hide_missing: true   # скрывать пункты, чьих файлов нет на сервере

sections:
  - id: linux
    key: l             # горячая клавиша, только для открытых разделов
    title: Linux installers
    zone: open         # open | windows | danger
    entries: [...]
  - id: windows
    title: Windows install
    zone: windows
    confirm: ERASE     # слово для ввода перед входом
    warning: [строки дисклеймера]
    entries: [...]
```

| Зона | Доступ | Папка файлов |
| --- | --- | --- |
| `open` | без пароля | пути от `/srv/netboot/http/` |
| `windows` | `tech`, `admin`, код, `ask`, назначение | `secure/` |
| `danger` | `admin`, код, `ask` + белый список MAC | `danger/` |

Всё, что ставит систему без вопросов (preseed, autoinstall, kickstart, клонирование, очистка), относится к зонам `windows` или `danger`.

## Пункты

```yaml
- id: alpine                       # латиница, цифры, _; уникален во всём меню
  title: Alpine Linux - needs Internet
  kernel: linux/alpine/vmlinuz-lts
  initrd: [linux/alpine/initramfs-lts]
  args: ip=dhcp modloop=${base}/linux/alpine/modloop-lts
  confirm: WIPE                    # необязательно: слово перед загрузкой
```

| `kind` | Поля |
| --- | --- |
| `linux` (по умолчанию) | `kernel`, `initrd`, `args` |
| `memtest` | `bios`, `efi` |
| `wimboot` | `mode: install` или `console`; только в зоне `windows` |
| `shell`, `reboot`, `poweroff` | — |

В `args` доступны переменные iPXE: `${base}` (http://сервер), `${srv}` (IP сервера), `${net0/mac:hexhyp}`.

Текст только ASCII: консоль iPXE не показывает кириллицу. Проверка: `froggyboot check`.

## Рецепты

`froggyboot add <имя>` скачивает файлы, сверяет SHA-256 со списком дистрибутива, распаковывает нужное из ISO и перерисовывает меню.

| Рецепт | Источник контрольных сумм |
| --- | --- |
| `debian` | `SHA256SUMS` установщика Debian 13 |
| `ubuntu-server` | `SHA256SUMS` релиза 24.04 |
| `alpine` | `latest-releases.yaml` |
| `fedora` | `.treeinfo` релиза |
| `arch` | `sha256sums.txt` |
| `mint` | `sha256sum.txt` релиза |

Рецепт — файл `recipes/<имя>.yml`:

```yaml
title: Alpine Linux (latest stable) netboot
dest: linux/alpine
source:
  type: alpine            # sums | alpine | treeinfo
  releases_url: https://dl-cdn.alpinelinux.org/alpine/latest-stable/releases/x86_64/latest-releases.yaml
files:
  - match: alpine-netboot-[0-9.]+-x86_64\.tar\.gz      # регулярное выражение по списку сумм
    extract: {boot/vmlinuz-lts: vmlinuz-lts}            # или extract: all, или без extract
    keep_as: name.iso                                  # сохранить и сам архив
```

Версии Fedora и Mint записаны в рецептах и `menu.yml`; для нового релиза меняются в обоих местах.

## Прочее

- Белый список опасной зоны: `DANGER_MACS` в `config.env` или `danger: true` в `hosts.yml`.
- Пароли:

```bash
sudo htpasswd /etc/nginx/netboot-windows.htpasswd tech
sudo htpasswd /etc/nginx/netboot-danger.htpasswd admin
```

Дополнительные техники — `htpasswd <файл> <имя>` без `-c`; в журнале видно, кто входил.

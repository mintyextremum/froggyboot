# Froggyboot

Меню сетевой загрузки для компьютерных классов на сервере с Debian. ПК загружается по PXE и получает меню: установщики Linux, live-системы, утилиты и установка Windows. Образы хранятся на сервере.

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

## Что умеет

- Работает рядом с чужим DHCP: dnsmasq в режиме proxy-DHCP, роутер не настраивается.
- Раздаёт Windows 10/11 через WinPE, BIOS и UEFI, с драйверами и `unattend.xml`.
- Без нажатий через 10 секунд грузит локальный диск. Если сервер недоступен — тоже.
- Пункты, стирающие диск, закрыты дисклеймером, паролем на сервере и вводом `ERASE`; в WinPE диск выбирается вручную.
- Опасная зона (Clonezilla, ShredOS) — отдельный пароль и белый список MAC.
- Журнал: время, IP, MAC, пользователь, файл.
- Работает без интернета, кроме сетевого установщика Debian.

## Меню

| Раздел | Пункты | Защита |
| --- | --- | --- |
| Главное | загрузка с диска | — |
| Linux | Debian 13, Ubuntu Server | установщик спрашивает сам |
| Утилиты | Memtest86+, GParted, SystemRescue, iPXE shell, перезагрузка, выключение | — |
| Windows | установка, консоль WinPE | дисклеймер, пароль, `ERASE`, выбор диска |
| Опасная зона | Clonezilla, ShredOS | пароль, белый список MAC, `WIPE` |

## Как устроено

```
ПК ──PXE──> роутер (IP) + dnsmasq proxy-DHCP (имя загрузчика)
 └─TFTP─> iPXE ──HTTP─> nginx: меню, ядра, WinPE; /secure и /danger под паролем
            WinPE ──SMB, только чтение──> Samba: install.wim, драйверы
```

Состав: dnsmasq, nginx, Samba, iPXE, wimboot и текстовые `.ipxe`-файлы. Своего бэкенда нет.

## Ограничения

- Пароль передаётся по HTTP, MAC подделывается: защита от случайностей, не от атак в той же сети.
- Secure Boot не поддерживается.
- Ubuntu Server грузит ISO в ОЗУ, нужно 8 ГБ.

## Документация

- [Установка](docs/INSTALL.md)
- [Свои пункты меню](docs/CUSTOMIZING.md)
- [Проблемы и решения](docs/TROUBLESHOOTING.md)
- [Модель безопасности](SECURITY.md)
- [Участие в проекте](CONTRIBUTING.md)

## Лицензия

[MIT](LICENSE). iPXE и wimboot — GPL, собираются на сервере.

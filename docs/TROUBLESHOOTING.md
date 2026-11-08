# Проблемы и решения

Журналы на сервере:

```bash
journalctl -u dnsmasq -f            # PXE, proxy-DHCP, TFTP
journalctl -u froggyboot -f         # приложение: меню, проверка паролей, Telegram
tail -f /var/log/nginx/netboot.log  # какой ПК какой файл запросил и код ответа
froggyboot log -n 50                # события: меню, выбор, входы, установки
```

В шапке меню видны IP сервера, имя или MAC ПК, его IP и режим (BIOS/UEFI): фото экрана обычно хватает для диагностики.

| Симптом | Причина | Решение |
| --- | --- | --- |
| ПК не видит PXE, «No boot filename received» | dnsmasq не отвечает в этой сети | `IFACE`, `NET_CIDR` в `config.env`; в `journalctl -u dnsmasq` должны быть строки `PXE(...)`; фаервол: UDP 67, 69, 4011 |
| iPXE пишет «Netboot server unavailable» | в iPXE старый IP или nginx остановлен | `sudo ./install.sh --rebuild-ipxe`; `systemctl status nginx`; фаервол: TCP 80 |
| Меню без имени ПК и без экзамена | приложение остановлено, отдаётся статическая копия | `systemctl status froggyboot`, `journalctl -u froggyboot` |
| Любой пароль — «Wrong password» | приложение остановлено (зоны закрываются) или неверный пароль | `systemctl status froggyboot`; проверка: `froggyboot log` |
| `403` на опасную зону с верным паролем | MAC нет в белом списке | `DANGER_MACS` или `danger: true` в `hosts.yml` |
| `403` на всё | ПК вне `NET_CIDR` | исправить `NET_CIDR`, запустить `install.sh` |
| HTTPS: «Permission denied» / ошибка сертификата в iPXE | iPXE собран со старым сертификатом | `sudo ./install.sh --rebuild-ipxe` |
| UEFI: «Boot from local disk» открывает настройки прошивки | после сети в порядке загрузки ничего нет | поставить Windows Boot Manager / диск после сетевой загрузки |
| BIOS: «Boot from local disk» зависает | диск не `0x80` или на нём нет загрузчика | проверить диск, временно убрать PXE из порядка загрузки |
| Пункт сразу возвращает в меню | файла нет | `froggyboot render` покажет скрытые пункты; `froggyboot add <рецепт>` |
| Пункта нет в меню | `hide_missing: true` и файлов нет | положить файлы, `froggyboot render` |
| WinPE: «cannot reach \\server\images» | нет драйвера сети в `boot.wim` или Samba остановлена | драйвер в `/srv/images/windows/drivers/` или в `boot.wim`; `systemctl status smbd`; TCP 445 |
| WinPE: список дисков пуст | контроллер Intel VMD / RST | драйвер Intel RST VMD в `drivers/` или режим AHCI в BIOS |
| Назначение не срабатывает | ПК не загружался по сети, назначение истекло (сутки) или уже стартовало | статус в панели; назначить заново |
| Нет отчётов установки в панели | WinPE не подключил `\\server\incoming` | `testparm -s`, права `/srv/froggyboot/incoming` (группа froggyboot) |
| Отчёт о железе не приходит | ISO SystemRescue не распакован или версия без `ar_source` | `tools/sysrescue/`; журнал на экране ПК |
| Wake-on-LAN не будит ПК | WoL выключен в BIOS или ПК в другой подсети | включить WoL; широковещательный пакет не проходит через роутер |
| Telegram молчит | неверный токен или id чата, нет доступа к api.telegram.org | `journalctl -u froggyboot \| grep telegram` |
| Windows 11 отказывается ставиться | проверки TPM и CPU | Windows 10 или `unattend.xml` по вашей лицензии и политике |
| Ubuntu / Mint зависает на загрузке ISO | мало памяти | 8 ГБ ОЗУ или сетевой установщик Debian |
| Соседние кабинеты видят меню | общий широковещательный домен | VLAN у сетевого администратора |

Issue на GitHub: фото шапки меню, режим загрузки и строки из журналов.

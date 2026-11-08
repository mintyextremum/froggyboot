# Secure Boot

Статус: **экспериментально, на реальном железе не проверено.**

Froggyboot по умолчанию требует выключенного Secure Boot: iPXE, wimboot и часть ядер не подписаны ключом Microsoft.

## Схема со своим ключом

1. Прошивка запускает `shimx64.efi` из пакета Debian `shim-signed` — он подписан Microsoft.
2. shim запускает `grubx64.efi` — это iPXE, подписанный своим ключом (MOK).
3. Ключ MOK один раз вносится в каждый ПК через MokManager.

`scripts/secureboot.sh` делает шаги на сервере:

- ставит `shim-signed`, `sbsigntool`;
- создаёт ключ в `/etc/froggyboot/mok/`;
- подписывает `ipxe.efi` как `grubx64.efi`, кладёт `shimx64.efi` и `mmx64.efi` в `/srv/netboot/tftp/`;
- подписывает неподписанные EFI-файлы в `/srv/netboot/http/` (ядра, `wimboot`, `memtest64.efi`), сохраняя оригиналы в `*.unsigned`;
- выкладывает сертификат для ПК: `/srv/netboot/http/froggyboot-mok.der`.

DHCP-ответ скрипт не меняет. Переключение UEFI-клиентов на shim — строка в `/etc/dnsmasq.d/netboot.conf`:

```
pxe-service=tag:efi64,X86-64_EFI,"Netboot",shimx64.efi
```

## Ограничения

- Ключ вносится в каждый ПК вручную через MokManager.
- Загружает ли iPXE ядра через проверку shim, зависит от версии iPXE и прошивки; при отказе ядро не стартует, ПК возвращается в меню.
- BIOS-клиентов это не касается.

# Участие

Issue и pull request принимаются на русском и английском.

## Правила

- **Безопасность по умолчанию не ослабляется.** Пункт, стирающий диск, не должен быть доступен без пароля, по таймауту или одной клавишей. Установщики с preseed / autoinstall — только в зонах `windows` или `danger`.
- **iPXE и WinPE — только ASCII.** `.cmd` и `.ini` — CRLF (`.gitattributes`).
- **Без новых служб.** Пакеты Debian и текстовые конфиги; приложение — то, что есть в Debian 13 (`python3-fastapi`, `python3-passlib` и т. д.).
- **Без образов, паролей и `config.env` в git.**

## Проверки

```bash
pip install fastapi uvicorn jinja2 pyyaml passlib httpx pytest
pytest -q
shellcheck -S warning install.sh scripts/*.sh packaging/*.sh test/stand/stand.sh
docker build -t froggyboot-stand -f test/stand/Dockerfile . && docker run --rm froggyboot-stand check
```

CI запускает то же самое, плюс `nginx -t` для HTTP и HTTPS и сборку `.deb`. Для изменений меню — укажите в PR, где проверяли: BIOS, UEFI, виртуалка или железо.

## Что можно взять

- Рецепты для новых дистрибутивов (`recipes/*.yml`) и пункты в `etc/menu.yml`.
- Рецепты для Memtest86+, GParted, SystemRescue, Clonezilla, ShredOS.
- Проверка Secure Boot-схемы на реальном железе.
- Многоадресная раздача `install.wim`.
- Отчёты о железе и проблемах в `docs/TROUBLESHOOTING.md`.

# Contributing

Thanks for helping! Issues and pull requests are welcome in English or Russian.

## Ground rules

- **Safe by default stays.** Never make an item that erases disks reachable with no password, a timeout, or a single keypress. Linux installers with preseed or autoinstall belong in the danger zone.
- **iPXE and WinPE text must be ASCII.** The iPXE console can't show Cyrillic, and WinPE is unreliable with it. `.cmd` and `.ini` files use CRLF; `.gitattributes` handles it.
- **No custom daemons in the MVP.** Prefer Debian packages and plain config files.
- **Never commit images, passwords or `config.env`.**

## Before opening a PR

```bash
bash -n install.sh scripts/*.sh
shellcheck install.sh scripts/*.sh
```

CI runs the same checks. If you changed a menu, say in the PR which firmware you tested it on (BIOS, UEFI, VM or real hardware).

## Good first contributions

- Menu entries for more distributions (Fedora, Arch, Alpine, Mint) in `server/http/linux.ipxe`, plus a line in the README table.
- `scripts/fetch-*.sh` downloaders with checksum verification, modelled on `fetch-debian.sh`.
- Hardware reports in `docs/TROUBLESHOOTING.md`.

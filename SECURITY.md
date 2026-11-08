# Security model

Froggyboot is built to stop **accidents and curious users**. It does not stop a determined attacker on the same LAN. PXE can't stop such an attacker in general. Please say so in your own documentation too.

## What is protected

- **Safe defaults.** The timeout, a missing server and `Esc` all lead to booting the local disk.
- **Server-side passwords.** nginx (HTTP basic auth) won't serve `windows.ipxe`, `danger.ipxe` or the WinPE files without valid credentials. No password is stored in the public `menu.ipxe`.
- **Two separate passwords.** `tech` opens Windows only. `admin` opens the danger zone. Rotate them regularly, for example every term.
- **MAC whitelist on the whole `/danger/` folder.**
- **The password doesn't linger.** It is cleared after the files are fetched, and it is never put on a kernel command line.
- **Network scope.** dnsmasq answers on one interface only. nginx and Samba serve only the configured subnet. The Samba share is read-only, and SMBv1 is off.
- **The `install.cmd` file**, which contains the read-only Samba password, can be read only by nginx and is served only behind the `tech` password.
- **Logs.** Every request is logged with time, IP, MAC and user, and logs are kept for 8 weeks.

## Known limits

| Limit | Consequence | Plan |
| --- | --- | --- |
| Basic auth over plain HTTP | Credentials can be sniffed on the LAN | HTTPS inside iPXE with an embedded certificate |
| MAC is supplied by the client | Whitelist can be bypassed by spoofing | It only prevents mistakes; keep the admin password strong |
| Secure Boot disabled | Unsigned boot chain | shim → signed iPXE |
| Rogue PXE servers | Another server on the LAN could answer first | Network-level controls (DHCP snooping) |

## Reporting a vulnerability

Please open a GitHub security advisory ("Report a vulnerability" on the Security tab) rather than a public issue.

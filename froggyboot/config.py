"""Settings (config.env), menu.yml and hosts.yml."""
from __future__ import annotations

import ipaddress
import os
import re
from dataclasses import dataclass, field
from pathlib import Path

import yaml

ETC = Path(os.environ.get("FROGGYBOOT_ETC", "/etc/froggyboot"))
VAR = Path(os.environ.get("FROGGYBOOT_VAR", "/var/lib/froggyboot"))
HTTP_ROOT = Path(os.environ.get("FROGGYBOOT_HTTP", "/srv/netboot/http"))
IMAGES = Path(os.environ.get("FROGGYBOOT_IMAGES", "/srv/images/windows"))
INCOMING = Path(os.environ.get("FROGGYBOOT_INCOMING", "/srv/froggyboot/incoming"))
NGINX_ETC = Path(os.environ.get("FROGGYBOOT_NGINX", "/etc/nginx"))

MAC_RE = re.compile(r"^([0-9a-f]{2}-){5}[0-9a-f]{2}$")
HOSTNAME_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9-]{0,14}$")
ZONES = ("open", "windows", "danger")
ZONE_DIR = {"open": "m", "windows": "secure", "danger": "danger"}


class ConfigError(ValueError):
    pass


def norm_mac(value: str) -> str:
    mac = value.strip().lower().replace(":", "-")
    if not MAC_RE.match(mac):
        raise ConfigError(f"bad MAC address: {value!r}")
    return mac


def read_env(path: Path) -> dict[str, str]:
    """Parse a shell-style KEY=VALUE file (the same one install.sh sources)."""
    out: dict[str, str] = {}
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, val = line.split("=", 1)
        val = val.strip()
        if len(val) >= 2 and val[0] == val[-1] and val[0] in "\"'":
            val = val[1:-1]
        out[key.strip()] = val
    return out


@dataclass
class Settings:
    server_ip: str
    iface: str
    net_cidr: str
    smb_user: str
    smb_pass: str
    https: bool = False
    app_port: int = 8070
    telegram_token: str = ""
    telegram_chat: str = ""
    danger_macs: list[str] = field(default_factory=list)

    @property
    def network(self) -> ipaddress.IPv4Network:
        return ipaddress.ip_network(self.net_cidr, strict=False)

    @property
    def net_addr(self) -> str:
        return str(self.network.network_address)

    @property
    def broadcast(self) -> str:
        return str(self.network.broadcast_address)

    @property
    def proto(self) -> str:
        return "https" if self.https else "http"


def load_settings(path: Path | None = None) -> Settings:
    env = read_env(path or ETC / "config.env")
    try:
        s = Settings(
            server_ip=str(ipaddress.ip_address(env["SERVER_IP"])),
            iface=env["IFACE"],
            net_cidr=env["NET_CIDR"],
            smb_user=env.get("SMB_USER", "winpe"),
            smb_pass=env["SMB_PASS"],
            https=env.get("HTTPS", "no").lower() in ("1", "yes", "true", "on"),
            app_port=int(env.get("APP_PORT", "8070")),
            telegram_token=env.get("TELEGRAM_TOKEN", ""),
            telegram_chat=env.get("TELEGRAM_CHAT", ""),
            danger_macs=[norm_mac(m) for m in env.get("DANGER_MACS", "").split()],
        )
        s.network  # validates NET_CIDR
    except KeyError as e:
        raise ConfigError(f"config.env: missing {e.args[0]}") from None
    except ValueError as e:
        raise ConfigError(f"config.env: {e}") from None
    if not re.fullmatch(r"[A-Za-z0-9]{8,}", s.smb_pass):
        raise ConfigError("config.env: SMB_PASS must be 8+ letters/digits")
    return s


def load_yaml(path: Path, default):
    if not path.exists():
        return default
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return default if data is None else data


# ---------------------------------------------------------------- hosts.yml
@dataclass
class Host:
    mac: str
    name: str
    room: str
    row: int = 0
    col: int = 0
    danger: bool = False


@dataclass
class Room:
    name: str
    cols: int
    hosts: list[Host]


def load_hosts(path: Path | None = None) -> list[Room]:
    data = load_yaml(path or ETC / "hosts.yml", {"rooms": []})
    rooms = []
    seen: set[str] = set()
    for r in data.get("rooms") or []:
        room = Room(name=str(r["name"]), cols=int(r.get("cols", 6)), hosts=[])
        for i, h in enumerate(r.get("hosts") or []):
            mac = norm_mac(str(h["mac"]))
            if mac in seen:
                raise ConfigError(f"hosts.yml: MAC {mac} listed twice")
            seen.add(mac)
            name = str(h.get("name") or "")
            # Also used as the Windows computer name: NetBIOS limit is 15 characters.
            if not HOSTNAME_RE.match(name):
                raise ConfigError(f"hosts.yml: {mac}: name must be 1-15 letters, digits or '-'")
            room.hosts.append(Host(
                mac=mac,
                name=name,
                room=room.name,
                row=int(h.get("row", i // room.cols + 1)),
                col=int(h.get("col", i % room.cols + 1)),
                danger=bool(h.get("danger", False)),
            ))
        rooms.append(room)
    return rooms


def hosts_by_mac(rooms: list[Room]) -> dict[str, Host]:
    return {h.mac: h for r in rooms for h in r.hosts}

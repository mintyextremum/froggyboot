import base64
import shutil
import subprocess
from pathlib import Path

import pytest

from froggyboot.config import Settings

REPO = Path(__file__).resolve().parent.parent


@pytest.fixture
def settings():
    return Settings(server_ip="192.168.1.10", iface="eth0", net_cidr="192.168.1.0/24",
                    smb_user="winpe", smb_pass="abcdefgh1", danger_macs=["00-1a-2b-3c-4d-5e"])


@pytest.fixture
def tree(tmp_path):
    etc, var, http, images, incoming, nginx = (tmp_path / d for d in
                                                ("etc", "var", "http", "images", "incoming", "nginx"))
    for d in (etc, var, http, images, incoming / "reports", nginx):
        d.mkdir(parents=True)
    shutil.copy(REPO / "etc" / "menu.yml", etc / "menu.yml")
    (etc / "hosts.yml").write_text(
        "rooms:\n  - name: '204'\n    cols: 4\n    hosts:\n"
        "      - {name: teacher, mac: 00:1A:2B:3C:4D:5E, danger: true}\n"
        "      - {name: pc01, mac: aa-bb-cc-dd-ee-01}\n", encoding="utf-8")
    from passlib.apache import HtpasswdFile
    for name, user, pw in (("windows", "tech", "techpass"), ("danger", "admin", "adminpass")):
        f = HtpasswdFile(str(nginx / f"netboot-{name}.htpasswd"), new=True)
        f.set_password(user, pw)
        f.save()
    # Fake images so entries are visible.
    for rel in ("linux/debian/linux", "linux/debian/initrd.gz", "secure/wimboot", "secure/BCD",
                "secure/boot.sdi", "secure/boot.wim", "danger/shredos/bzImage"):
        p = http / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"x")
    (images / "install.wim").write_bytes(b"x")
    return {"etc": etc, "var": var, "http_root": http, "images": images, "incoming": incoming, "nginx_etc": nginx}


@pytest.fixture
def client(settings, tree):
    from fastapi.testclient import TestClient
    from froggyboot.app import create_app
    app = create_app(settings, background=False, **tree)
    with TestClient(app) as c:
        c.app_db = app.state.db
        yield c


def basic(user, pw):
    return {"Authorization": "Basic " + base64.b64encode(f"{user}:{pw}".encode()).decode()}

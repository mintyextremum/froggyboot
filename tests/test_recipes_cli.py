import hashlib

import pytest

from froggyboot import recipes
from froggyboot.__main__ import main
from froggyboot.config import ConfigError, load_settings, read_env


def test_parse_sums_formats():
    h = "a" * 64
    text = f"{h}  ./netboot/linux\n{h} *ubuntu-24.04.3-live-server-amd64.iso\nSHA256 (Fedora.iso) = {h.upper()}\njunk\n"
    assert recipes.parse_sums(text) == {"netboot/linux": h, "ubuntu-24.04.3-live-server-amd64.iso": h,
                                        "Fedora.iso": h}


def test_pick_newest_and_missing():
    sums = {"ubuntu-24.04.2-live-server-amd64.iso": "x", "ubuntu-24.04.3-live-server-amd64.iso": "y"}
    assert recipes._pick(sums, r"ubuntu-24\.04(\.\d+)?-live-server-amd64\.iso").endswith("04.3-live-server-amd64.iso")
    with pytest.raises(ConfigError):
        recipes._pick(sums, r"nothing")


def test_bundled_recipes_load():
    names = recipes.list_recipes()
    assert {"debian", "ubuntu-server", "alpine", "fedora", "arch", "mint"} <= set(names)
    for n in names:
        r = recipes.load_recipe(n)
        assert r["dest"] and r["files"] and r["source"]["type"] in ("sums", "alpine", "treeinfo")


def test_install_verifies_checksum(tmp_path, monkeypatch):
    payload = b"kernel-bytes"
    good = hashlib.sha256(payload).hexdigest()
    rdir = tmp_path / "recipes"
    rdir.mkdir()
    (rdir / "demo.yml").write_text(
        "dest: linux/demo\nsource: {type: sums, sums_url: http://x/SHA256SUMS}\nfiles:\n  - match: images/vmlinuz\n")

    def fake_download(url, dst):
        dst.write_bytes(payload)
        return hashlib.sha256(payload).hexdigest()

    monkeypatch.setattr(recipes, "_download", fake_download)
    monkeypatch.setattr(recipes, "_get", lambda url, timeout=60: f"{good}  ./images/vmlinuz\n".encode())
    http = tmp_path / "http"
    assert recipes.install("demo", http, rdir, log=lambda *_: None) == ["linux/demo/vmlinuz"]
    assert (http / "linux/demo/vmlinuz").read_bytes() == payload
    assert "linux/demo/vmlinuz" in (http / "SHA256SUMS").read_text()

    monkeypatch.setattr(recipes, "_get", lambda url, timeout=60: f"{'0' * 64}  ./images/vmlinuz\n".encode())
    with pytest.raises(ConfigError, match="checksum mismatch"):
        recipes.install("demo", http, rdir, log=lambda *_: None)


def test_read_env_and_settings(tmp_path):
    f = tmp_path / "config.env"
    f.write_text('# c\r\nSERVER_IP=10.0.0.5\r\nIFACE=eth0\nNET_CIDR=10.0.0.0/24\nSMB_PASS=abcdefgh9\n'
                 'DANGER_MACS="AA:BB:CC:DD:EE:FF 00-11-22-33-44-55"\nHTTPS=yes\n')
    assert read_env(f)["DANGER_MACS"] == "AA:BB:CC:DD:EE:FF 00-11-22-33-44-55"
    s = load_settings(f)
    assert s.danger_macs == ["aa-bb-cc-dd-ee-ff", "00-11-22-33-44-55"]
    assert s.https and s.proto == "https" and s.broadcast == "10.0.0.255"
    f.write_text("SERVER_IP=10.0.0.5\nIFACE=eth0\nNET_CIDR=10.0.0.0/24\nSMB_PASS=short\n")
    with pytest.raises(ConfigError):
        load_settings(f)


def test_cli_check_render_code_exam(tree, settings, monkeypatch, capsys):
    import froggyboot.__main__ as cli
    import froggyboot.config as cfg
    (tree["etc"] / "config.env").write_text(
        "SERVER_IP=192.168.1.10\nIFACE=eth0\nNET_CIDR=192.168.1.0/24\nSMB_PASS=abcdefgh1\n")
    monkeypatch.setattr(cfg, "ETC", tree["etc"])
    monkeypatch.setattr(cli, "VAR", tree["var"])
    monkeypatch.setattr(cli, "HTTP_ROOT", tree["http_root"])
    import froggyboot.menu as menu_mod
    monkeypatch.setattr(menu_mod, "ETC", tree["etc"])
    monkeypatch.setattr(menu_mod, "HTTP_ROOT", tree["http_root"])
    monkeypatch.setattr(cfg, "load_settings", lambda path=None: settings)
    monkeypatch.setattr(cli, "load_settings", lambda path=None: settings)
    monkeypatch.setattr(cli, "load_hosts", lambda path=None: cfg.load_hosts(tree["etc"] / "hosts.yml"))
    assert main(["check"]) == 0
    assert main(["render"]) == 0
    assert (tree["http_root"] / "m" / "linux.ipxe").exists()
    assert main(["code", "windows", "--minutes", "5"]) == 0
    assert main(["exam", "linux/debian"]) == 0
    assert main(["exam", "danger/shredos"]) == 1
    assert main(["exam", "off"]) == 0
    out = capsys.readouterr().out
    assert "hidden (files missing)" in out and "exam mode off" in out

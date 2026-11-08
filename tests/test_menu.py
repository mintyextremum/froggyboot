import re

import pytest

from froggyboot.config import ConfigError, Host
from froggyboot.menu import load_menu, parse_menu, render_all, render_main, visible, write_all
from tests.conftest import REPO


def test_default_menu_renders_all_sections(settings):
    menu = load_menu(REPO / "etc" / "menu.yml")
    menu.hide_missing = False
    files = render_all(settings, menu)
    assert set(files) == {"menu.ipxe", "m/linux.ipxe", "m/tools.ipxe", "secure/windows.ipxe", "danger/danger.ipxe"}
    for name, text in files.items():
        assert text.startswith("#!ipxe\n"), name
        assert text.isascii(), name
        assert "{{" not in text and "{%" not in text, name


def test_every_goto_has_a_label(settings):
    menu = load_menu(REPO / "etc" / "menu.yml")
    menu.hide_missing = False
    texts = list(render_all(settings, menu).values())
    texts.append(render_main(settings, menu, host=Host("aa-bb-cc-dd-ee-ff", "pc1", "1"), exam="tools/memtest",
                             assignment={"entry": "windows/win_install", "token": "t", "label": "W", "disk": 0}))
    for text in texts:
        labels = set(re.findall(r"^:(\w+)$", text, re.M))
        for target in re.findall(r"goto (\w+)", text):
            assert target in labels, f"goto {target} without label"


def test_main_menu_is_safe_by_default(settings):
    menu = load_menu(REPO / "etc" / "menu.yml")
    text = render_main(settings, menu)
    assert "choose --default local --timeout 10000" in text
    # Protected sections never get hotkeys.
    assert not re.search(r"item --key \w+ (windows|danger)", text)
    assert "iseq ${confirm} ERASE || goto cancelled" in text


def test_protected_paths_use_credentials(settings):
    menu = load_menu(REPO / "etc" / "menu.yml")
    menu.hide_missing = False
    files = render_all(settings, menu)
    win = files["secure/windows.ipxe"]
    assert "set zp ${proto}://${username:uristring}:${password:uristring}@${srv}/secure" in win
    assert "kernel ${zp}/wimboot?${q}" in win
    assert win.count("clear password") >= 3
    danger = files["danger/danger.ipxe"]
    assert "iseq ${confirm} WIPE || goto menu" in danger


def test_hide_missing(settings, tree):
    menu = load_menu(REPO / "etc" / "menu.yml")
    shown = visible(menu, tree["http_root"])
    ids = {e.id for s in shown.sections for e in s.entries}
    assert "debian" in ids and "ubuntu" not in ids and "shell" in ids
    written = write_all(settings, menu, tree["http_root"])
    assert "m/linux.ipxe" in written
    assert (tree["http_root"] / "menu.ipxe").read_text().startswith("#!ipxe")


def test_exam_and_assignment_blocks(settings):
    menu = load_menu(REPO / "etc" / "menu.yml")
    menu.hide_missing = False
    text = render_main(settings, menu, exam="tools/memtest")
    assert "EXAM MODE" in text and "set froggy_jump memtest" in text
    assert "item windows" not in text
    # Exam entries must be in open sections.
    assert "EXAM MODE" not in render_main(settings, menu, exam="danger/shredos")
    text = render_main(settings, menu, assignment={"entry": "windows/win_install", "token": "TOK",
                                                   "label": "Win 11 Pro", "disk": 1})
    assert "set password TOK" in text and "set froggy_jump win_install" in text


@pytest.mark.parametrize("bad", [
    {"sections": [{"id": "x", "zone": "windows", "key": "w", "entries": []}]},
    {"sections": [{"id": "x", "entries": [{"id": "a", "kernel": "../etc/passwd"}]}]},
    {"sections": [{"id": "x", "entries": [{"id": "a", "kernel": "k", "title": "Привет"}]}]},
    {"sections": [{"id": "x", "entries": [{"id": "a", "kind": "wimboot"}]}]},
    {"sections": [{"id": "x", "entries": [{"id": "a", "kernel": "k"}, {"id": "a", "kernel": "k"}]}]},
    {"sections": [{"id": "local", "entries": []}]},
])
def test_menu_validation(bad):
    with pytest.raises(ConfigError):
        parse_menu(bad)

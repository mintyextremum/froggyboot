"""froggyboot command line.

  froggyboot check                  validate config.env, menu.yml, hosts.yml
  froggyboot render                 write the static menus into /srv/netboot/http
  froggyboot serve                  run the app (systemd does this)
  froggyboot recipes                list download recipes
  froggyboot add <recipe>...        download + verify images, then re-render the menu
  froggyboot wake <name|mac|room>.. Wake-on-LAN
  froggyboot code <windows|danger> [--minutes N] [--mac MAC]
  froggyboot exam <section/entry|off>
  froggyboot log [--mac MAC] [-n N]
"""
from __future__ import annotations

import argparse
import sys
import time

from . import __version__
from .config import ETC, HTTP_ROOT, VAR, ConfigError, load_hosts, load_settings, norm_mac


def _db():
    from .db import DB
    return DB(VAR / "state.db")


def cmd_check(_a) -> int:
    from .menu import load_menu
    s = load_settings()
    m = load_menu()
    rooms = load_hosts()
    n = sum(len(r.hosts) for r in rooms)
    print(f"config.env ok: server {s.server_ip} on {s.iface}, network {s.net_cidr}, "
          f"{'HTTPS' if s.https else 'HTTP'}, telegram {'on' if s.telegram_token else 'off'}")
    print(f"menu.yml ok: {len(m.sections)} sections, {sum(len(x.entries) for x in m.sections)} entries")
    print(f"hosts.yml ok: {len(rooms)} rooms, {n} PCs")
    return 0


def cmd_render(_a) -> int:
    from .menu import load_menu, visible, write_all
    s, m = load_settings(), load_menu()
    for rel in write_all(s, m):
        print(f"wrote {HTTP_ROOT / rel}")
    hidden = {e.id for x in m.sections for e in x.entries} - {e.id for x in visible(m).sections for e in x.entries}
    if hidden:
        print("hidden (files missing): " + ", ".join(sorted(hidden)))
    return 0


def cmd_serve(_a) -> int:
    from .app import main
    main()
    return 0


def cmd_recipes(_a) -> int:
    from .recipes import list_recipes, load_recipe
    for name in list_recipes():
        print(f"{name:15} {load_recipe(name).get('title', '')}")
    return 0


def cmd_add(a) -> int:
    from .recipes import install
    for name in a.recipe:
        print(f"== {name}")
        for f in install(name):
            print(f"installed {f}")
    return cmd_render(a)


def cmd_wake(a) -> int:
    from .tools import wake
    s, rooms = load_settings(), load_hosts()
    macs = []
    for t in a.target:
        hit = [h.mac for r in rooms for h in r.hosts if t in (h.name, r.name)]
        if not hit:
            try:
                hit = [norm_mac(t)]
            except ConfigError:
                print(f"unknown PC or room: {t}", file=sys.stderr)
                return 1
        macs += hit
    print(f"sent magic packets to {wake(macs, s.broadcast)} PCs via {s.broadcast}")
    db = _db()
    for m in macs:
        db.event(m, "wake", "cli")
    return 0


def cmd_code(a) -> int:
    mac = norm_mac(a.mac) if a.mac else None
    code = _db().new_code(a.zone, a.minutes * 60, mac, "cli")
    print(f"{code}   (zone {a.zone}, {a.minutes} min{', ' + mac if mac else ''}; login 'code')")
    return 0


def cmd_exam(a) -> int:
    from .menu import load_menu
    db = _db()
    if a.entry == "off":
        db.put("exam", None)
        print("exam mode off")
        return 0
    sec, ent = load_menu().find(a.entry)
    if sec.zone != "open":
        print("exam entry must be in an open section", file=sys.stderr)
        return 1
    db.put("exam", a.entry)
    print(f"exam mode: {ent.title}")
    return 0


def cmd_log(a) -> int:
    for e in reversed(_db().events(a.n, norm_mac(a.mac) if a.mac else None)):
        print(f"{time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(e['ts']))}  {e['mac']}  {e['kind']}  {e['detail']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="froggyboot", description=f"Froggyboot {__version__} ({ETC})")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("check").set_defaults(fn=cmd_check)
    sub.add_parser("render").set_defaults(fn=cmd_render)
    sub.add_parser("serve").set_defaults(fn=cmd_serve)
    sub.add_parser("recipes").set_defaults(fn=cmd_recipes)
    x = sub.add_parser("add"); x.add_argument("recipe", nargs="+"); x.set_defaults(fn=cmd_add)
    x = sub.add_parser("wake"); x.add_argument("target", nargs="+"); x.set_defaults(fn=cmd_wake)
    x = sub.add_parser("code"); x.add_argument("zone", choices=["windows", "danger"])
    x.add_argument("--minutes", type=int, default=10); x.add_argument("--mac"); x.set_defaults(fn=cmd_code)
    x = sub.add_parser("exam"); x.add_argument("entry"); x.set_defaults(fn=cmd_exam)
    x = sub.add_parser("log"); x.add_argument("--mac"); x.add_argument("-n", type=int, default=50)
    x.set_defaults(fn=cmd_log)
    a = p.parse_args(argv)
    try:
        return a.fn(a)
    except (ConfigError, KeyError, FileNotFoundError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

"""HTTP app behind nginx: dynamic main menu, zone auth, events, inventory and the admin panel.

nginx serves static files itself and asks this app only for:
  /menu.ipxe            per-PC main menu (host name, exam mode, assignments)
  /api/event/<kind>     menu choices from iPXE
  /api/auth/<zone>      auth_request for /secure/ and /danger/
  /secure/froggy.txt    per-PC settings for WinPE (after auth)
  /api/inventory        hardware reports
  /panel/...            admin panel (nginx checks the admin password first)
If the app is down, nginx falls back to the static menu, and protected zones stay closed.
"""
from __future__ import annotations

import base64
import binascii
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse, Response

from . import __version__
from .config import (ETC, HTTP_ROOT, IMAGES, INCOMING, NGINX_ETC, VAR, ConfigError, MAC_RE, Settings,
                     hosts_by_mac, load_hosts, load_settings, norm_mac)
from .db import DB
from .menu import Menu, load_menu, render_main, visible
from .notify import Notifier
from .tools import ReportWatcher, list_images, wake

log = logging.getLogger("froggyboot")
PANEL_HTML = Path(__file__).parent / "templates" / "panel.html"
KIND_RE = re.compile(r"^[a-z][a-z0-9_-]{0,30}$")
STATUS_WINDOW = 3 * 3600


class Htpasswd:
    """Reloads an htpasswd file when it changes. Supports the formats htpasswd writes."""

    def __init__(self, path: Path):
        self.path, self.mtime, self.file = path, None, None

    def check(self, user: str, password: str) -> bool:
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            return False
        if mtime != self.mtime:
            from passlib.apache import HtpasswdFile
            self.file, self.mtime = HtpasswdFile(str(self.path)), mtime
        try:
            return bool(self.file.check_password(user, password))
        except (ValueError, TypeError):
            return False


class Cached:
    """Re-reads a config file when its mtime changes; keeps the last good version on errors."""

    def __init__(self, path: Path, loader):
        self.path, self.loader, self.mtime, self.value = path, loader, None, None

    def get(self):
        try:
            mtime = self.path.stat().st_mtime
        except OSError:
            mtime = 0
        if mtime != self.mtime or self.value is None:
            try:
                self.value = self.loader(self.path)
            except (ConfigError, OSError) as e:
                log.error("%s: %s", self.path, e)
                if self.value is None:
                    raise
            self.mtime = mtime
        return self.value


def _mac_from_uri(uri: str) -> str | None:
    vals = parse_qs(urlsplit(uri).query).get("mac")
    if not vals:
        return None
    try:
        return norm_mac(vals[0])
    except ConfigError:
        return None


def _basic(request: Request) -> tuple[str, str] | None:
    h = request.headers.get("authorization", "")
    if not h.lower().startswith("basic "):
        return None
    try:
        user, _, pw = base64.b64decode(h[6:]).decode("utf-8").partition(":")
    except (binascii.Error, UnicodeDecodeError):
        return None
    return user, pw


def _ascii(text: str, limit: int = 60) -> str:
    return re.sub(r"[^ -~]", "?", text)[:limit]


def create_app(settings: Settings | None = None, *, etc: Path = ETC, var: Path = VAR,
               http_root: Path = HTTP_ROOT, images: Path = IMAGES, incoming: Path = INCOMING,
               nginx_etc: Path = NGINX_ETC, background: bool = True) -> FastAPI:
    settings = settings or load_settings(etc / "config.env")
    db = DB(var / "state.db")
    menu_c = Cached(etc / "menu.yml", load_menu)
    hosts_c = Cached(etc / "hosts.yml", load_hosts)
    pw = {"windows": [Htpasswd(nginx_etc / "netboot-windows.htpasswd"),
                      Htpasswd(nginx_etc / "netboot-danger.htpasswd")],
          "danger": [Htpasswd(nginx_etc / "netboot-danger.htpasswd")]}

    def hosts() -> dict:
        return hosts_by_mac(hosts_c.get())

    def label(mac: str) -> str:
        h = hosts().get(mac)
        return f"{h.name} ({mac})" if h else mac

    def decide(aid: int, approve: bool, by: str) -> str | None:
        a = db.decide(aid, approve, by)
        if not a:
            return None
        db.event(a["mac"], "approval-" + a["status"], f"{a['zone']} by {by}")
        return "Approved" if approve else "Denied"

    notifier = Notifier(settings.telegram_token, settings.telegram_chat, decide)

    def on_step(mac: str, step: str, detail: str) -> None:
        db.event(mac, "install:" + step, detail)
        if step in ("done", "fail"):
            if db.active_assignment(mac):
                db.set_assignment_status(mac, "done" if step == "done" else "failed")
            notifier.send(f"{'OK' if step == 'done' else 'FAILED'}: Windows install on {label(mac)}"
                          + (f" - {detail}" if detail else ""))
        elif step == "start":
            notifier.send(f"Windows install started on {label(mac)}" + (f": {detail}" if detail else ""))

    watcher = ReportWatcher(incoming / "reports", on_step)

    @asynccontextmanager
    async def lifespan(_app):
        if background:
            watcher.start()
            notifier.start_polling()
            db.prune()
        yield
        watcher.stop()
        notifier.stop()

    app = FastAPI(title="Froggyboot", version=__version__, lifespan=lifespan, docs_url=None, redoc_url=None)
    app.state.db, app.state.notifier, app.state.watcher = db, notifier, watcher

    def menu() -> Menu:
        return visible(menu_c.get(), http_root)

    # ------------------------------------------------------------------ iPXE
    @app.get("/menu.ipxe", response_class=PlainTextResponse)
    def main_menu(mac: str = ""):
        try:
            m = norm_mac(mac)
        except ConfigError:
            m = None
        host = hosts().get(m) if m else None
        assignment = None
        if m:
            db.event(m, "menu")
            a = db.active_assignment(m)
            if a and a["status"] == "pending":
                assignment = {"entry": a["entry"], "token": a["token"], "label": _ascii(a["label"]),
                              "disk": a["disk"]}
        text = render_main(settings, menu(), host=host, exam=db.get("exam"), assignment=assignment)
        return PlainTextResponse(text, headers={"Cache-Control": "no-store"})

    @app.get("/api/event/{kind}", response_class=PlainTextResponse)
    def event(kind: str, mac: str = ""):
        if KIND_RE.match(kind):
            try:
                db.event(norm_mac(mac), kind)
            except ConfigError:
                pass
        return "ok\n"

    def check_auth(zone: str, mac: str | None, creds: tuple[str, str] | None) -> tuple[int, str]:
        """Return (HTTP status, who). 200 = allowed, 401 = ask for credentials, 403 = never."""
        if zone not in pw or not mac:
            return 403, ""
        if zone == "danger":
            h = hosts().get(mac)
            if mac not in settings.danger_macs and not (h and h.danger):
                return 403, ""
        if not creds:
            return 401, ""
        user, password = creds
        if user == "code":
            return (200, "code") if db.check_code(password.strip(), zone, mac) else (401, "")
        if user == "ask":
            a = db.approval(mac, zone)
            if a and a["status"] == "approved":
                return 200, f"ask:{a['decided_by']}"
            if a and a["status"] == "denied":
                return 403, ""
            a, created = db.request_approval(mac, zone)
            if created:
                db.event(mac, "approval-request", zone)
                notifier.send(f"{label(mac)} asks for the {zone} zone.", approval_id=a["id"])
            return 401, ""
        if user == "assign" and zone == "windows":
            a = db.active_assignment(mac)
            if a and password == a["token"]:
                if a["status"] == "pending":
                    db.set_assignment_status(mac, "started")
                    db.event(mac, "assignment-start", a["label"])
                return 200, "assign"
            return 401, ""
        if any(f.check(user, password) for f in pw[zone]):
            return 200, user
        return 401, ""

    @app.get("/api/auth/{zone}")
    def auth(zone: str, request: Request):
        uri = request.headers.get("x-original-uri", "")
        mac = _mac_from_uri(uri)
        status, who = check_auth(zone, mac, _basic(request))
        if status == 200:
            path = urlsplit(uri).path
            if path.endswith(".ipxe") and mac:
                db.event(mac, f"zone-open:{zone}", who)
                notifier.send(f"{label(mac)} opened the {zone} zone as {who}.")
            return Response(status_code=200, headers={"X-Froggy-User": who})
        if status == 401:
            return Response(status_code=401, headers={"WWW-Authenticate": f'Basic realm="froggyboot-{zone}"'})
        return Response(status_code=403)

    @app.get("/api/froggy.txt", response_class=PlainTextResponse)
    def froggy_txt(request: Request):
        """Settings for install.cmd. nginx serves it as /secure/froggy.txt after auth_request."""
        uri = request.headers.get("x-original-uri", "") or str(request.url)
        mac = _mac_from_uri(uri)
        creds = _basic(request)
        status, who = check_auth("windows", mac, creds)
        if status != 200 or not mac:
            raise HTTPException(403)
        h = hosts().get(mac)
        lines = [f"MAC={mac}", f"HOST={h.name if h else 'PC-' + mac.replace('-', '')[-6:].upper()}",
                 f"SRV={settings.server_ip}", f"STAMP={time.strftime('%Y%m%d-%H%M')}", "AUTO=0"]
        a = db.active_assignment(mac)
        if who == "assign" and a:
            lines[-1] = "AUTO=1"
            lines += [f"WIM={a['wim']}", f"IDX={a['idx']}", f"DISK={a['disk']}", f"BACKUP={a['backup']}"]
        db.event(mac, "winpe-start", "auto" if who == "assign" else who)
        return PlainTextResponse("\r\n".join(lines) + "\r\n", headers={"Cache-Control": "no-store"})

    @app.post("/api/inventory")
    async def inventory(request: Request, mac: str = ""):
        try:
            m = norm_mac(mac)
        except ConfigError:
            raise HTTPException(400, "bad mac") from None
        body = await request.body()
        if len(body) > 512 * 1024:
            raise HTTPException(413)
        try:
            import json
            data = json.loads(body)
            if not isinstance(data, dict):
                raise ValueError
        except ValueError:
            raise HTTPException(400, "expected a JSON object") from None
        db.save_inventory(m, data)
        db.event(m, "inventory", str(data.get("product", ""))[:100])
        notifier.send(f"Hardware report received from {label(m)}.")
        return {"ok": True}

    # ------------------------------------------------------------------ panel
    def admin(request: Request) -> str:
        return request.headers.get("x-remote-user", "") or "admin"

    @app.get("/panel/", response_class=HTMLResponse)
    def panel():
        return HTMLResponse(PANEL_HTML.read_text(encoding="utf-8"), headers={"Cache-Control": "no-store"})

    def status_of(ev: dict | None, assign: dict | None) -> str:
        if assign and assign["status"] in ("pending", "started"):
            return "assigned" if assign["status"] == "pending" else "installing"
        if not ev:
            return "off"
        k = ev["kind"]
        if k == "local":
            return "disk"
        if k == "install:done":
            return "installed"
        if k in ("install:fail", "install:cancel"):
            return "error" if k == "install:fail" else "menu"
        if k.startswith("install:") or k in ("winpe-start", "assignment-start"):
            return "installing"
        if k.startswith("zone-open") or k.startswith("approval"):
            return "protected"
        if k == "inventory":
            return "inventory"
        return "menu"

    @app.get("/panel/api/overview")
    def overview():
        rooms = hosts_c.get()
        last = db.last_events(time.time() - STATUS_WINDOW)
        assigns = {a["mac"]: a for a in db.assignments()}
        out_rooms = []
        for r in rooms:
            out_rooms.append({"name": r.name, "cols": r.cols, "hosts": [
                {**asdict(h), "status": status_of(last.get(h.mac), assigns.get(h.mac)),
                 "last": last.get(h.mac), "assignment": assigns.get(h.mac)} for h in r.hosts]})
        known = hosts_by_mac(rooms)
        unknown = [{"mac": mac, "last": ev, "status": status_of(ev, assigns.get(mac))}
                   for mac, ev in db.last_events(time.time() - 7 * 86400).items() if mac not in known]
        m = menu_c.get()
        return {
            "version": __version__, "server": settings.server_ip, "https": settings.https,
            "telegram": notifier.enabled, "rooms": out_rooms, "unknown": unknown,
            "approvals": [{**a, "label": label(a["mac"])} for a in db.pending_approvals()],
            "assignments": [{**a, "label_host": label(a["mac"])} for a in assigns.values()],
            "codes": db.codes(), "exam": db.get("exam"),
            "exam_choices": m.refs(zone="open"),
            "install_choices": [(f"{s.id}/{e.id}", e.title) for s in m.sections for e in s.entries
                                if s.zone == "windows" and e.kind == "wimboot" and e.mode == "install"],
            "events": [{**e, "host": label(e["mac"])} for e in db.events(60)],
        }

    @app.post("/panel/api/approvals/{aid}")
    def approval_decide(aid: int, request: Request, approve: bool = Body(..., embed=True)):
        res = decide(aid, approve, admin(request))
        if not res:
            raise HTTPException(409, "already decided or expired")
        return {"ok": True, "result": res}

    @app.post("/panel/api/codes")
    def make_code(request: Request, zone: str = Body(...), minutes: int = Body(10), mac: str = Body("")):
        if zone not in ("windows", "danger") or not 1 <= minutes <= 24 * 60:
            raise HTTPException(400, "zone is windows or danger, minutes 1..1440")
        m = None
        if mac:
            try:
                m = norm_mac(mac)
            except ConfigError as e:
                raise HTTPException(400, str(e)) from None
        code = db.new_code(zone, minutes * 60, m, admin(request))
        db.event(m or "00-00-00-00-00-00", "code-created", f"{zone} {minutes} min by {admin(request)}")
        return {"code": code, "zone": zone, "minutes": minutes, "mac": m}

    @app.post("/panel/api/wake")
    def wake_hosts(request: Request, macs: list[str] = Body(..., embed=True)):
        try:
            clean = [norm_mac(x) for x in macs]
        except ConfigError as e:
            raise HTTPException(400, str(e)) from None
        n = wake(clean, settings.broadcast)
        for m in clean:
            db.event(m, "wake", admin(request))
        return {"sent": n}

    @app.post("/panel/api/exam")
    def set_exam(request: Request, entry: str | None = Body(None, embed=True)):
        if entry:
            try:
                sec, _ = menu_c.get().find(entry)
            except KeyError:
                raise HTTPException(400, "unknown entry") from None
            if sec.zone != "open":
                raise HTTPException(400, "exam entry must be in an open section")
        db.put("exam", entry or None)
        db.event("00-00-00-00-00-00", "exam", f"{entry or 'off'} by {admin(request)}")
        return {"exam": entry}

    @app.get("/panel/api/images")
    def images_list():
        return list_images(images)

    @app.post("/panel/api/assign")
    def assign(request: Request, macs: list[str] = Body(...), entry: str = Body(...), wim: str = Body(...),
               index: int = Body(...), disk: int = Body(0), backup: bool = Body(False)):
        try:
            sec, ent = menu_c.get().find(entry)
        except KeyError:
            raise HTTPException(400, "unknown entry") from None
        if sec.zone != "windows" or ent.kind != "wimboot" or ent.mode != "install":
            raise HTTPException(400, "entry must be a Windows install entry")
        if not re.fullmatch(r"[A-Za-z0-9._-]+\.(wim|esd)", wim, re.I) or not (images / wim).is_file():
            raise HTTPException(400, "image file not found")
        if not 0 <= disk <= 32 or not 1 <= index <= 64:
            raise HTTPException(400, "bad disk or index")
        eds: dict[int, str] = {}
        for img in list_images(images):
            if img["file"] == wim:
                eds = {e["index"]: e["name"] for e in img["editions"]}
        lbl = _ascii(f"{eds.get(index, wim + ' #' + str(index))}")
        try:
            clean = [norm_mac(x) for x in macs]
        except ConfigError as e:
            raise HTTPException(400, str(e)) from None
        for m in clean:
            db.assign(m, entry, wim, index, disk, backup, lbl, admin(request))
            db.event(m, "assigned", f"{lbl} disk {disk} by {admin(request)}")
        return {"assigned": len(clean), "label": lbl}

    @app.delete("/panel/api/assign/{mac}")
    def unassign(mac: str, request: Request):
        try:
            m = norm_mac(mac)
        except ConfigError as e:
            raise HTTPException(400, str(e)) from None
        db.unassign(m)
        db.event(m, "unassigned", admin(request))
        return {"ok": True}

    @app.get("/panel/api/inventory")
    def inventory_list(mac: str = ""):
        if mac:
            try:
                return db.inventory(norm_mac(mac))
            except ConfigError as e:
                raise HTTPException(400, str(e)) from None
        return db.inventory()

    @app.get("/panel/api/events")
    def events(mac: str = "", limit: int = 200):
        m = None
        if mac:
            try:
                m = norm_mac(mac)
            except ConfigError as e:
                raise HTTPException(400, str(e)) from None
        return [{**e, "host": label(e["mac"])} for e in db.events(min(limit, 2000), m)]

    @app.exception_handler(ConfigError)
    def config_error(_req, exc: ConfigError):
        return JSONResponse({"detail": str(exc)}, status_code=500)

    return app


def main() -> None:  # entry point for systemd: python3 -m froggyboot serve
    import uvicorn
    logging.basicConfig(level=os.environ.get("FROGGYBOOT_LOG", "INFO"))
    s = load_settings()
    uvicorn.run(create_app(s), host="127.0.0.1", port=s.app_port, log_level="warning", proxy_headers=False)

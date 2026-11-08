"""menu.yml model and iPXE rendering."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

import jinja2

from .config import ETC, HTTP_ROOT, ZONE_DIR, ZONES, ConfigError, Host, Settings, load_yaml

ID_RE = re.compile(r"^[a-z][a-z0-9_]{0,30}$")
KINDS = ("linux", "memtest", "wimboot", "shell", "reboot", "poweroff")
RESERVED = {"main", "local", "back", "menu", "failed", "denied", "cancelled", "jump",
            "exam", "assigned", "start"}

_env = jinja2.Environment(
    loader=jinja2.PackageLoader("froggyboot", "templates/ipxe"),
    trim_blocks=True, lstrip_blocks=True, keep_trailing_newline=True,
    undefined=jinja2.StrictUndefined, autoescape=False,
)


@dataclass
class Initrd:
    path: str
    name: str


@dataclass
class Entry:
    id: str
    title: str
    kind: str = "linux"
    kernel: str = ""
    initrds: list[Initrd] = field(default_factory=list)
    args: str = ""
    bios: str = ""
    efi: str = ""
    mode: str = ""
    confirm: str = ""

    def files(self) -> list[str]:
        if self.kind == "linux":
            return [self.kernel] + [i.path for i in self.initrds]
        if self.kind == "memtest":
            return [self.bios, self.efi]
        if self.kind == "wimboot":
            return ["wimboot", "BCD", "boot.sdi", "boot.wim"]
        return []


@dataclass
class Section:
    id: str
    title: str
    zone: str
    entries: list[Entry]
    key: str = ""
    confirm: str = ""
    warning: list[str] = field(default_factory=list)

    @property
    def dir(self) -> str:
        return ZONE_DIR[self.zone]

    @property
    def path(self) -> str:
        """Published path of the section script, relative to the HTTP root."""
        return f"{self.dir}/{self.id}.ipxe"

    def file_path(self, rel: str) -> str:
        return rel if self.zone == "open" else f"{self.dir}/{rel}"


@dataclass
class Menu:
    timeout: int
    hide_missing: bool
    sections: list[Section]

    def find(self, ref: str) -> tuple[Section, Entry]:
        """Look up 'section/entry'."""
        sid, _, eid = ref.partition("/")
        for s in self.sections:
            if s.id == sid:
                for e in s.entries:
                    if e.id == eid:
                        return s, e
        raise KeyError(ref)

    def refs(self, zone: str | None = None, kind: str | None = None) -> list[tuple[str, str]]:
        return [(f"{s.id}/{e.id}", e.title) for s in self.sections for e in s.entries
                if (zone is None or s.zone == zone) and (kind is None or e.kind == kind)]


def _ascii(text: str, where: str) -> str:
    if not text.isascii():
        raise ConfigError(f"menu.yml: {where}: text must be ASCII (iPXE can't show other letters)")
    if any(c in text for c in "\r\n"):
        raise ConfigError(f"menu.yml: {where}: no line breaks")
    return text


def _relpath(p: str, where: str) -> str:
    p = str(p).strip().lstrip("/")
    if not p or ".." in Path(p).parts or not re.fullmatch(r"[A-Za-z0-9._/+-]+", p):
        raise ConfigError(f"menu.yml: {where}: bad path {p!r}")
    return p


def parse_menu(data: dict) -> Menu:
    sections: list[Section] = []
    labels: set[str] = set()
    keys: set[str] = {"d"}
    for s in data.get("sections") or []:
        sid = str(s.get("id", ""))
        if not ID_RE.match(sid) or sid in RESERVED:
            raise ConfigError(f"menu.yml: bad section id {sid!r}")
        zone = s.get("zone", "open")
        if zone not in ZONES:
            raise ConfigError(f"menu.yml: section {sid}: zone must be one of {ZONES}")
        key = str(s.get("key", "") or "")
        if key and zone != "open":
            raise ConfigError(f"menu.yml: section {sid}: protected sections get no hotkey")
        if key and (len(key) != 1 or key in keys):
            raise ConfigError(f"menu.yml: section {sid}: hotkey {key!r} invalid or taken")
        keys.add(key)
        sec = Section(
            id=sid, zone=zone, key=key,
            title=_ascii(str(s.get("title", sid)), f"section {sid}"),
            confirm=_ascii(str(s.get("confirm", "") or ""), f"section {sid} confirm"),
            warning=[_ascii(str(w), f"section {sid} warning") for w in s.get("warning") or []],
            entries=[],
        )
        if sec.confirm and not re.fullmatch(r"[A-Z]{3,12}", sec.confirm):
            raise ConfigError(f"menu.yml: section {sid}: confirm must be 3-12 capital letters")
        for e in s.get("entries") or []:
            eid = str(e.get("id", ""))
            if not ID_RE.match(eid) or eid in RESERVED or eid in labels or eid == sid:
                raise ConfigError(f"menu.yml: bad or duplicate entry id {eid!r}")
            labels.add(eid)
            kind = e.get("kind", "linux")
            if kind not in KINDS:
                raise ConfigError(f"menu.yml: entry {eid}: kind must be one of {KINDS}")
            where = f"entry {eid}"
            ent = Entry(id=eid, kind=kind, title=_ascii(str(e.get("title", eid)), where),
                        args=_ascii(str(e.get("args", "") or ""), where),
                        confirm=_ascii(str(e.get("confirm", "") or ""), where))
            if ent.confirm and not re.fullmatch(r"[A-Z]{3,12}", ent.confirm):
                raise ConfigError(f"menu.yml: {where}: confirm must be 3-12 capital letters")
            if kind == "linux":
                ent.kernel = _relpath(e.get("kernel", ""), where)
                for i in e.get("initrd") or []:
                    if isinstance(i, dict):
                        path, name = _relpath(i["path"], where), str(i.get("name") or "")
                    else:
                        path, name = _relpath(i, where), ""
                    ent.initrds.append(Initrd(path, name or Path(path).name))
            elif kind == "memtest":
                ent.bios = _relpath(e.get("bios", ""), where)
                ent.efi = _relpath(e.get("efi", ""), where)
            elif kind == "wimboot":
                if zone != "windows":
                    raise ConfigError(f"menu.yml: {where}: wimboot entries belong in a windows zone")
                ent.mode = e.get("mode", "install")
                if ent.mode not in ("install", "console"):
                    raise ConfigError(f"menu.yml: {where}: mode is install or console")
            sec.entries.append(ent)
        if sid in labels:
            raise ConfigError(f"menu.yml: section id {sid!r} clashes with an entry id")
        labels.add(sid)
        sections.append(sec)
    if not sections:
        raise ConfigError("menu.yml: no sections")
    return Menu(timeout=int(data.get("timeout", 10)), hide_missing=bool(data.get("hide_missing", True)),
                sections=sections)


def load_menu(path: Path | None = None) -> Menu:
    return parse_menu(load_yaml(path or ETC / "menu.yml", {}))


def visible(menu: Menu, http_root: Path | None = None) -> Menu:
    """Drop entries whose files are missing (if hide_missing) and empty sections."""
    if not menu.hide_missing:
        return menu
    root = http_root or HTTP_ROOT
    out = []
    for s in menu.sections:
        entries = [e for e in s.entries if all((root / s.file_path(f)).exists() for f in e.files())]
        if entries:
            out.append(Section(**{**s.__dict__, "entries": entries}))
    return Menu(menu.timeout, menu.hide_missing, out)


def render_section(settings: Settings, section: Section) -> str:
    return _env.get_template("section.ipxe.j2").render(s=settings, sec=section)


def render_main(settings: Settings, menu: Menu, *, host: Host | None = None, exam: str | None = None,
                assignment: dict | None = None) -> str:
    exam_ref = None
    if exam:
        try:
            sec, ent = menu.find(exam)
            if sec.zone == "open":
                exam_ref = {"section": sec, "entry": ent}
        except KeyError:
            pass
    assign_ref = None
    if assignment:
        try:
            sec, ent = menu.find(assignment["entry"])
            if sec.zone == "windows" and ent.kind == "wimboot":
                assign_ref = {**assignment, "section": sec, "entry_obj": ent}
        except KeyError:
            pass
    return _env.get_template("main.ipxe.j2").render(
        s=settings, menu=menu, host=host, exam=exam_ref, assignment=assign_ref)


def render_all(settings: Settings, menu: Menu, http_root: Path | None = None) -> dict[str, str]:
    """All static scripts: path relative to the HTTP root -> content."""
    shown = visible(menu, http_root)
    files = {"menu.ipxe": render_main(settings, shown)}
    for sec in shown.sections:
        files[sec.path] = render_section(settings, sec)
    return files


def write_all(settings: Settings, menu: Menu, http_root: Path | None = None) -> list[str]:
    root = http_root or HTTP_ROOT
    written = []
    for rel, text in render_all(settings, menu, root).items():
        dst = root / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        tmp = dst.with_suffix(".tmp")
        tmp.write_text(text, encoding="ascii", newline="\n")
        tmp.replace(dst)
        written.append(rel)
    # Remove section scripts that are no longer in the menu.
    keep = set(written)
    for zdir in set(ZONE_DIR.values()):
        for old in (root / zdir).glob("*.ipxe") if (root / zdir).is_dir() else []:
            rel = f"{zdir}/{old.name}"
            if rel not in keep and old.read_text(errors="ignore").startswith("#!ipxe\n# Generated by froggyboot"):
                old.unlink()
    return written

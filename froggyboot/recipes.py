"""Download images described by recipes/*.yml and verify them before they reach the menu.

Checksum sources (source.type):
  sums      - a SHA256SUMS-style file (GNU "hash  name" or BSD "SHA256 (name) = hash")
  alpine    - Alpine's latest-releases.yaml
  treeinfo  - Fedora/RHEL .treeinfo [checksums]
Afterwards files can be extracted from an ISO/tarball with bsdtar.
"""
from __future__ import annotations

import configparser
import hashlib
import re
import shutil
import subprocess
import tempfile
import urllib.request
from dataclasses import dataclass
from pathlib import Path

import yaml

from .config import HTTP_ROOT, ConfigError

RECIPES_DIR = Path(__file__).resolve().parent.parent / "recipes"
UA = {"User-Agent": "froggyboot-recipes"}


@dataclass
class Fetched:
    name: str
    path: Path
    sha256: str


def _get(url: str, timeout: int = 60) -> bytes:
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
        return r.read()


def _download(url: str, dst: Path) -> str:
    h = hashlib.sha256()
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r, dst.open("wb") as f:
        while chunk := r.read(1 << 20):
            h.update(chunk)
            f.write(chunk)
    return h.hexdigest()


def parse_sums(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        m = re.match(r"^([0-9a-fA-F]{64})\s+\*?(.+)$", line.strip())
        if m:
            out[m.group(2).strip().lstrip("./")] = m.group(1).lower()
            continue
        m = re.match(r"^SHA256 \((.+)\) = ([0-9a-fA-F]{64})$", line.strip())
        if m:
            out[m.group(1).lstrip("./")] = m.group(2).lower()
    return out


def load_recipe(name: str, recipes_dir: Path = RECIPES_DIR) -> dict:
    path = recipes_dir / f"{name}.yml"
    if not re.fullmatch(r"[a-z0-9-]+", name) or not path.exists():
        raise ConfigError(f"unknown recipe {name!r}; available: {', '.join(list_recipes(recipes_dir))}")
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def list_recipes(recipes_dir: Path = RECIPES_DIR) -> list[str]:
    return sorted(p.stem for p in recipes_dir.glob("*.yml"))


def _expected(recipe: dict) -> tuple[str, dict[str, str]]:
    """Return (base_url, {file name relative to base: sha256})."""
    src = recipe["source"]
    kind = src["type"]
    if kind == "sums":
        sums = parse_sums(_get(src["sums_url"]).decode("utf-8", "replace"))
        base = src.get("base_url") or src["sums_url"].rsplit("/", 1)[0] + "/"
        return base, sums
    if kind == "alpine":
        rel = yaml.safe_load(_get(src["releases_url"]))
        base = src["releases_url"].rsplit("/", 1)[0] + "/"
        return base, {r["file"]: r["sha256"].lower() for r in rel if r.get("sha256")}
    if kind == "treeinfo":
        cp = configparser.ConfigParser()
        cp.read_string(_get(src["base_url"] + ".treeinfo").decode())
        sums = {k: v.split(":", 1)[1].lower() for k, v in cp["checksums"].items() if v.startswith("sha256:")}
        return src["base_url"], sums
    raise ConfigError(f"recipe: unknown source type {kind!r}")


def _pick(sums: dict[str, str], pattern: str) -> str:
    rx = re.compile(pattern)
    hits = sorted(k for k in sums if rx.fullmatch(k))
    if not hits:
        raise ConfigError(f"recipe: nothing in the checksum list matches {pattern!r}")
    return hits[-1]  # newest by name


def install(name: str, http_root: Path = HTTP_ROOT, recipes_dir: Path = RECIPES_DIR,
            log=print) -> list[str]:
    recipe = load_recipe(name, recipes_dir)
    dest = http_root / recipe["dest"]
    base, sums = _expected(recipe)
    installed: list[str] = []
    with tempfile.TemporaryDirectory(prefix="froggy-") as tmp:
        tmpd = Path(tmp)
        for item in recipe["files"]:
            remote = _pick(sums, item["match"])
            local = tmpd / Path(remote).name
            log(f"downloading {remote}")
            got = _download(base + remote, local)
            if got != sums[remote]:
                raise ConfigError(f"checksum mismatch for {remote}: got {got}, want {sums[remote]}")
            log(f"  sha256 ok {got[:16]}...")
            if "extract" in item:
                if not shutil.which("bsdtar"):
                    raise ConfigError("bsdtar is required (apt install libarchive-tools)")
                out = tmpd / "x"
                out.mkdir(exist_ok=True)
                members = [] if item["extract"] == "all" else list(item["extract"].keys())
                subprocess.run(["bsdtar", "-xf", str(local), "-C", str(out), *members], check=True)
                if item["extract"] == "all":
                    dest.mkdir(parents=True, exist_ok=True)
                    shutil.copytree(out, dest, dirs_exist_ok=True)
                    installed.append(f"{recipe['dest']}/ (whole archive)")
                else:
                    for src_rel, dst_rel in item["extract"].items():
                        _place(out / src_rel, dest / dst_rel)
                        installed.append(f"{recipe['dest']}/{dst_rel}")
                if item.get("keep_as"):
                    _place(local, dest / item["keep_as"])
                    installed.append(f"{recipe['dest']}/{item['keep_as']}")
            else:
                _place(local, dest / item.get("as", Path(remote).name))
                installed.append(f"{recipe['dest']}/{item.get('as', Path(remote).name)}")
    _record_sums(http_root, recipe["dest"])
    return installed


def _place(src: Path, dst: Path) -> None:
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    dst.chmod(0o644)


def _record_sums(http_root: Path, rel_dir: str) -> None:
    """Refresh lines for rel_dir in http_root/SHA256SUMS (used by verify-images.sh)."""
    sums_file = http_root / "SHA256SUMS"
    old = sums_file.read_text().splitlines() if sums_file.exists() else []
    keep = [ln for ln in old if not ln.split("  ", 1)[-1].startswith(rel_dir.rstrip("/") + "/")]
    new = []
    for f in sorted((http_root / rel_dir).rglob("*")):
        if f.is_file():
            h = hashlib.sha256()
            with f.open("rb") as fh:
                while chunk := fh.read(1 << 20):
                    h.update(chunk)
            new.append(f"{h.hexdigest()}  {f.relative_to(http_root).as_posix()}")
    sums_file.write_text("\n".join(keep + new) + "\n")

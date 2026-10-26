#!/usr/bin/env python3
"""
ii-icon-pack manager
====================
Installs, reshapes and updates the ii-icon-pack theme. Standard library only, so it runs on
any Linux desktop with Python 3.10+; Quickshell `ii` drives the same commands from
Settings -> Interface -> Themed icons.

  iipack.py shapes [--json]                     list plate shapes
  iipack.py install [--shape S] [options]       install (or re-render) the theme
  iipack.py status [--remote] [--json]          what is installed, and whether an update exists
  iipack.py update [--check] [--json]           pull the latest pack from GitHub and reinstall
  iipack.py preview --out DIR [--icon NAME]     one sample SVG per shape (for pickers)
  iipack.py uninstall                           remove the installed theme

The theme is rendered from the pack in this repository into
`$XDG_DATA_HOME/icons/ii-icon-pack` (a real copy, never a symlink into the repository, so
reshaping never touches the checkout). Every install remembers its options in
`.ii-icon-pack.json` inside the theme, so `update` and a bare `install` keep the user's shape.
"""
import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import iishape  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE_PACK = REPO_ROOT / "ii-icon-pack"
THEME_NAME = "ii-icon-pack"
STATE_FILE = ".ii-icon-pack.json"
SOURCE_STATE_FILE = ".ii-source.json"
GITHUB_REPO = "P3DROVFX/ii-icon-pack"
GITHUB_URL = f"https://github.com/{GITHUB_REPO}.git"
BRANCH = "main"
RESHAPED_DIRS = ("apps/scalable", "preferences/scalable")

DEFAULTS = {"shape": iishape.DEFAULT_SHAPE, "plateScale": 1.0, "glyphScale": 1.0, "plateColor": "", "glyphColor": ""}

_JSON_OUT = False


def data_home() -> Path:
    return Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")


def default_dest() -> Path:
    return data_home() / "icons" / THEME_NAME


def progress(fraction: float, message: str):
    """Machine-readable progress for the shell (`@progress <0..1> <message>`), plain text otherwise."""
    if _JSON_OUT:
        print(f"@progress {fraction:.3f} {message}", flush=True)
    else:
        print(message, flush=True)


def emit(result: dict, text: str = ""):
    if _JSON_OUT:
        print(json.dumps(result), flush=True)
    elif text:
        print(text)


def fail(message: str, code: int = 1):
    if _JSON_OUT:
        print(json.dumps({"ok": False, "error": message}), flush=True)
    else:
        print(f"error: {message}", file=sys.stderr)
    sys.exit(code)


# ── Versions ────────────────────────────────────────────────────────────────

def _git(*args, cwd=REPO_ROOT, timeout=60) -> subprocess.CompletedProcess:
    return subprocess.run(["git", *args], cwd=cwd, capture_output=True, text=True, timeout=timeout)


def is_git_checkout() -> bool:
    return (REPO_ROOT / ".git").exists() and shutil.which("git") is not None


def source_commit() -> str:
    if is_git_checkout():
        res = _git("rev-parse", "HEAD")
        if res.returncode == 0:
            return res.stdout.strip()
    try:
        return json.loads((REPO_ROOT / SOURCE_STATE_FILE).read_text())["commit"]
    except (OSError, ValueError, KeyError):
        return ""


def source_date(commit: str) -> str:
    if commit and is_git_checkout():
        res = _git("show", "-s", "--format=%cI", commit)
        if res.returncode == 0:
            return res.stdout.strip()
    try:
        return json.loads((REPO_ROOT / SOURCE_STATE_FILE).read_text()).get("date", "")
    except (OSError, ValueError):
        return ""


def remote_commit() -> str:
    """Newest commit on GitHub: `git ls-remote` needs no clone, the REST API needs no git."""
    if shutil.which("git"):
        try:
            res = _git("ls-remote", GITHUB_URL, f"refs/heads/{BRANCH}", cwd=None, timeout=30)
            if res.returncode == 0 and res.stdout.strip():
                return res.stdout.split()[0]
        except subprocess.TimeoutExpired:
            pass
    try:
        req = urllib.request.Request(f"https://api.github.com/repos/{GITHUB_REPO}/commits/{BRANCH}",
                                     headers={"Accept": "application/vnd.github.sha"})
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.read().decode().strip()
    except OSError:
        return ""


# ── Install ─────────────────────────────────────────────────────────────────

def read_state(dest: Path) -> dict:
    try:
        return json.loads((dest / STATE_FILE).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def resolve_options(args, dest: Path) -> dict:
    """Command-line flags win, then what the last install used, then the defaults."""
    saved = read_state(dest)
    opts = {}
    for key, flag in (("shape", "shape"), ("plateScale", "plate_scale"), ("glyphScale", "glyph_scale"),
                      ("plateColor", "plate_color"), ("glyphColor", "glyph_color")):
        value = getattr(args, flag, None)
        opts[key] = value if value is not None else saved.get(key, DEFAULTS[key])
    try:
        opts["shape"] = iishape.normalize_shape(opts["shape"])
    except ValueError as e:
        fail(str(e))
    opts["plateScale"] = min(1.08, max(0.6, float(opts["plateScale"])))
    opts["glyphScale"] = min(1.5, max(0.5, float(opts["glyphScale"])))
    for key in ("plateColor", "glyphColor"):
        if opts[key] and not re.fullmatch(r"#[0-9a-fA-F]{6}", opts[key]):
            fail(f"{key} must look like #rrggbb")
    return opts


def _link_or_copy(src: Path, dst: Path):
    try:
        os.link(src, dst)
    except OSError:
        shutil.copy2(src, dst)


def render_theme(source: Path, dest: Path, opts: dict):
    """Render `source` into `dest` atomically: built next to it, then swapped in."""
    if not (source / "index.theme").is_file():
        fail(f"no icon theme at {source}")
    dest.parent.mkdir(parents=True, exist_ok=True)
    work = Path(tempfile.mkdtemp(prefix=f".{THEME_NAME}-", dir=dest.parent))
    os.chmod(work, 0o755)  # mkdtemp is private; an icon theme has to be readable
    plate_d = iishape.plate_path(opts["shape"], opts["plateScale"])
    try:
        entries = []
        for root, dirs, files in os.walk(source):
            rel = Path(root).relative_to(source)
            for name in dirs:
                p = Path(root) / name
                if p.is_symlink():
                    entries.append((rel / name, "link"))
            dirs[:] = [d for d in dirs if not (Path(root) / d).is_symlink()]
            (work / rel).mkdir(parents=True, exist_ok=True)
            for name in files:
                entries.append((rel / name, "file"))

        total = max(1, len(entries))
        reshaped = 0
        for i, (rel, kind) in enumerate(entries):
            if i % 1500 == 0:
                progress(0.05 + 0.85 * i / total, f"Rendering icons ({i}/{total})")
            src, dst = source / rel, work / rel
            if kind == "link" or src.is_symlink():
                os.symlink(os.readlink(src), dst)
            elif rel.name.endswith("icon-theme.cache"):
                continue
            elif rel.suffix == ".svg" and str(rel.parent) in RESHAPED_DIRS:
                text = src.read_text(encoding="utf-8", errors="ignore")
                out = iishape.reshape_svg(text, opts["shape"], opts["plateScale"], opts["glyphScale"],
                                          opts["plateColor"] or None, opts["glyphColor"] or None, plate_d)
                if out is text:
                    _link_or_copy(src, dst)
                else:
                    dst.write_text(out, encoding="utf-8")
                    reshaped += 1
            else:
                _link_or_copy(src, dst)

        commit = source_commit()
        state = dict(opts, commit=commit, date=source_date(commit), installedAt=int(time.time()),
                     source=str(REPO_ROOT), reshaped=reshaped)
        (work / STATE_FILE).write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

        progress(0.92, "Updating icon cache")
        for tool in ("gtk-update-icon-cache", "gtk4-update-icon-cache"):
            if shutil.which(tool):
                subprocess.run([tool, "-f", "-q", "-t", str(work)], capture_output=True)

        progress(0.97, "Swapping the theme in")
        old = None
        if dest.is_symlink():
            dest.unlink()  # a developer symlink into a checkout: drop the link, never its target
        elif dest.exists():
            old = dest.with_name(f".{THEME_NAME}-old-{os.getpid()}")
            dest.rename(old)
        work.rename(dest)
        os.utime(dest)
        if old:
            shutil.rmtree(old, ignore_errors=True)
        return state
    except BaseException:
        shutil.rmtree(work, ignore_errors=True)
        raise


def cmd_install(args):
    dest = Path(args.dest).expanduser() if args.dest else default_dest()
    opts = resolve_options(args, dest)
    progress(0.0, f"Installing {THEME_NAME} ({opts['shape']}) into {dest}")
    state = render_theme(SOURCE_PACK, dest, opts)
    if args.set_theme:
        set_system_theme()
    emit({"ok": True, "installed": True, **state},
         f"Installed {THEME_NAME} with the '{opts['shape']}' shape ({state['reshaped']} icons) at {dest}")


def set_system_theme():
    """Point GTK and KDE at the pack, for desktops without Quickshell ii."""
    if shutil.which("gsettings"):
        subprocess.run(["gsettings", "set", "org.gnome.desktop.interface", "icon-theme", THEME_NAME], capture_output=True)
    for gtk in ("gtk-3.0", "gtk-4.0"):
        ini = Path.home() / ".config" / gtk / "settings.ini"
        if not ini.is_file():
            continue
        text = ini.read_text(encoding="utf-8")
        if re.search(r"^gtk-icon-theme-name\s*=", text, flags=re.M):
            text = re.sub(r"^gtk-icon-theme-name\s*=.*$", f"gtk-icon-theme-name={THEME_NAME}", text, flags=re.M)
        else:
            text = re.sub(r"^\[Settings\]\s*$", f"[Settings]\ngtk-icon-theme-name={THEME_NAME}", text, count=1, flags=re.M)
        ini.write_text(text, encoding="utf-8")
    for tool in ("kwriteconfig6", "kwriteconfig5"):
        if shutil.which(tool):
            subprocess.run([tool, "--file", "kdeglobals", "--group", "Icons", "--key", "Theme", THEME_NAME], capture_output=True)
            break


def cmd_uninstall(args):
    dest = Path(args.dest).expanduser() if args.dest else default_dest()
    if dest.is_symlink():
        dest.unlink()
    elif dest.exists():
        shutil.rmtree(dest)
    emit({"ok": True, "installed": False}, f"Removed {dest}")


# ── Status & update ─────────────────────────────────────────────────────────

def cmd_status(args):
    dest = Path(args.dest).expanduser() if args.dest else default_dest()
    state = read_state(dest)
    installed = (dest / "index.theme").is_file()
    src = source_commit()
    result = {
        "ok": True,
        "sourcePresent": True,
        "installed": installed,
        "managed": bool(state),
        "dest": str(dest),
        "source": str(REPO_ROOT),
        "sourceCommit": src,
        "sourceDate": source_date(src),
        "installedCommit": state.get("commit", ""),
        "installedDate": state.get("date", ""),
        "options": {k: state.get(k, v) for k, v in DEFAULTS.items()},
    }
    if args.remote:
        remote = remote_commit()
        result["remoteCommit"] = remote
        result["updateAvailable"] = bool(remote and src and remote != src)
    result["renderPending"] = installed and bool(state) and bool(src) and state.get("commit") != src
    lines = [f"Theme      : {'installed at ' + str(dest) if installed else 'not installed'}"]
    if state:
        lines.append(f"Shape      : {state.get('shape')} (plate {state.get('plateScale')}, glyph {state.get('glyphScale')})")
    lines.append(f"Source     : {REPO_ROOT} @ {src[:10] or 'unknown'}")
    if args.remote:
        lines.append(f"GitHub     : {result['remoteCommit'][:10] or 'unreachable'}"
                     + (" (update available)" if result["updateAvailable"] else ""))
    emit(result, "\n".join(lines))


def _download_tarball(commit: str):
    """Refresh a non-git source tree from the GitHub tarball."""
    url = f"https://codeload.github.com/{GITHUB_REPO}/tar.gz/refs/heads/{BRANCH}"
    tmp = Path(tempfile.mkdtemp(prefix="ii-icon-pack-dl-"))
    try:
        archive = tmp / "pack.tar.gz"
        progress(0.1, "Downloading the pack")
        with urllib.request.urlopen(url, timeout=120) as resp, open(archive, "wb") as fh:
            shutil.copyfileobj(resp, fh)
        progress(0.35, "Unpacking")
        if sys.version_info >= (3, 12):
            shutil.unpack_archive(str(archive), str(tmp / "x"), filter="tar")
        else:
            shutil.unpack_archive(str(archive), str(tmp / "x"))
        top = next((tmp / "x").iterdir())
        for name in ("ii-icon-pack", "scripts", "sources", "README.md", "LICENSE", "install.sh"):
            src, dst = top / name, REPO_ROOT / name
            if not src.exists():
                continue
            if dst.is_dir() and not dst.is_symlink():
                shutil.rmtree(dst)
            elif dst.exists() or dst.is_symlink():
                dst.unlink()
            shutil.move(str(src), str(dst))
        (REPO_ROOT / SOURCE_STATE_FILE).write_text(json.dumps({"commit": commit, "date": ""}) + "\n")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def cmd_update(args):
    dest = Path(args.dest).expanduser() if args.dest else default_dest()
    progress(0.02, "Checking GitHub for a newer pack")
    remote = remote_commit()
    before = source_commit()
    if not remote:
        fail("could not reach GitHub")
    available = remote != before
    if args.check:
        emit({"ok": True, "updateAvailable": available, "sourceCommit": before, "remoteCommit": remote},
             "Update available" if available else "Already up to date")
        return
    if available:
        if is_git_checkout():
            progress(0.1, "Pulling the latest pack")
            res = _git("pull", "--ff-only", "origin", BRANCH, timeout=600)
            if res.returncode != 0:
                fail("git pull failed: " + (res.stderr.strip().splitlines() or ["unknown error"])[-1])
        else:
            _download_tarball(remote)
        if args.source_only:
            emit({"ok": True, "updated": True, "sourceCommit": source_commit()}, "Pack source updated")
            return
        # The renderer may have changed too: rerun from the new checkout.
        rerun = [sys.executable, str(Path(__file__).resolve()), "install", "--dest", str(dest)]
        if _JSON_OUT:
            rerun.append("--json")
        os.execv(sys.executable, rerun)
    if (dest / "index.theme").is_file() and read_state(dest).get("commit") == before and not args.force:
        emit({"ok": True, "updated": False, **read_state(dest)}, "Already up to date")
        return
    args.shape = args.plate_scale = args.glyph_scale = args.plate_color = args.glyph_color = None
    args.set_theme = False
    cmd_install(args)


# ── Shapes & previews ───────────────────────────────────────────────────────

def cmd_shapes(args):
    out = [dict(iishape.preset(k), path=iishape.plate_path(k)) for k in iishape.SHAPES]
    emit({"ok": True, "shapes": out}, "\n".join(f"{s['key']:16s} {s['name']}" for s in out))


def cmd_preview(args):
    """Write `<shape>.svg` for every shape into --out, all drawn from one sample icon."""
    out_dir = Path(args.out).expanduser()
    out_dir.mkdir(parents=True, exist_ok=True)
    source = SOURCE_PACK if (SOURCE_PACK / "apps/scalable").is_dir() else default_dest()
    sample = None
    for name in (args.icon, "firefox", "spotify", "org.gnome.Nautilus"):
        if not name:
            continue
        p = source / "apps" / "scalable" / f"{name}.svg"
        if p.exists():
            text = p.resolve().read_text(encoding="utf-8", errors="ignore")
            if iishape.is_plate_icon(text):
                sample = text
                break
    if sample is None:
        fail("no sample icon found")
    plate_scale = args.plate_scale if args.plate_scale is not None else 1.0
    glyph_scale = args.glyph_scale if args.glyph_scale is not None else 1.0
    files = {}
    for key in iishape.SHAPES:
        svg = iishape.reshape_svg(sample, key, plate_scale, glyph_scale, args.plate_color, args.glyph_color)
        target = out_dir / f"{key}.svg"
        target.write_text(svg, encoding="utf-8")
        files[key] = str(target)
    emit({"ok": True, "previews": files}, f"Wrote {len(files)} previews to {out_dir}")


def main():
    global _JSON_OUT
    parser = argparse.ArgumentParser(prog="iipack", description="Install, reshape and update the ii-icon-pack theme.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    def common(p, shape_opts=False):
        p.add_argument("--json", action="store_true", help="machine-readable output (progress lines + one JSON result)")
        p.add_argument("--dest", help=f"theme directory (default: {default_dest()})")
        if shape_opts:
            p.add_argument("--shape", help="plate shape (see `shapes`); default: the installed one, else circle")
            p.add_argument("--plate-scale", type=float, help="icon size inside its canvas, 0.6-1.08 (1 = original)")
            p.add_argument("--glyph-scale", type=float, help="logo size on the plate, 0.5-1.5 (1 = shape default)")
            p.add_argument("--plate-color", help="plate colour #rrggbb (standalone use; ii recolors on its own)")
            p.add_argument("--glyph-color", help="logo colour #rrggbb (standalone use; ii recolors on its own)")

    p = sub.add_parser("install", help="install or re-render the theme")
    common(p, True)
    p.add_argument("--set-theme", action="store_true", help="also make it the GTK/KDE icon theme")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("apply", help="alias of install")
    common(p, True)
    p.add_argument("--set-theme", action="store_true")
    p.set_defaults(func=cmd_install)

    p = sub.add_parser("status", help="installed version, options and update state")
    common(p)
    p.add_argument("--remote", action="store_true", help="also ask GitHub for the newest commit")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("update", help="pull the latest pack and reinstall with the same options")
    common(p)
    p.add_argument("--check", action="store_true", help="only report whether an update exists")
    p.add_argument("--force", action="store_true", help="reinstall even when nothing changed")
    p.add_argument("--source-only", action="store_true", help="refresh the checkout without reinstalling")
    p.set_defaults(func=cmd_update)

    p = sub.add_parser("uninstall", help="remove the installed theme")
    common(p)
    p.set_defaults(func=cmd_uninstall)

    p = sub.add_parser("shapes", help="list plate shapes")
    p.add_argument("--json", action="store_true")
    p.set_defaults(func=cmd_shapes)

    p = sub.add_parser("preview", help="render one sample icon in every shape")
    p.add_argument("--json", action="store_true")
    p.add_argument("--out", required=True)
    p.add_argument("--icon", help="app icon name to sample")
    p.add_argument("--plate-scale", type=float)
    p.add_argument("--glyph-scale", type=float)
    p.add_argument("--plate-color")
    p.add_argument("--glyph-color")
    p.set_defaults(func=cmd_preview)

    args = parser.parse_args()
    _JSON_OUT = bool(getattr(args, "json", False))
    args.func(args)


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""
OneYou Icon Theme Builder
=========================
Builds a Material You / Android 16 style monochrome circular icon pack for Linux
using a strict 5-stage priority pipeline:

  Priority 1: Craft App Suite (`sources/craft/*.svg`) — Bicolor Woodcut / Engraving style
  Priority 2: YAMIS (`~/.local/share/icons/YAMIS`)    — Filled monochrome silhouettes (apps + preferences)
  Priority 3: Lawnicons (`svgs/*.svg` + `appfilter.xml`) — 10,200+ Android 16 icons for remaining apps
  Priority 4: Linux Freedesktop Aliases (Papirus symlink map + .desktop Name/WMClass resolution)
  Priority 5: Auto-Silhouette Extractor (`sources/auto/*.svg`) — Automatically strips square/cut-corner/squircle
              plates from any remaining unmapped system icons (e.g. Quickshell, OpenTabletDriver, Qt tools,
              AppImages) and vectorizes their inner logo into a uniform circular OneYou icon.

Key colors (`PLATE_HEX` and `GLYPH_HEX`) are calibrated for 100% native compatibility
with Quickshell `ii`'s `recolor_icons.py` (`ToneMap` classifies every app icon as a
non-inverted `plate` at tone 30.0 with a primary-tinted glyph at tone 92.0).
"""
import argparse
import configparser
import glob
import io
import os
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

import cv2
import numpy as np
from PIL import Image

# Calibrated Material You base tones for Quickshell `ii` (`recolor_icons.py`):
# - PLATE_HEX has L* ~ 15 (dark container -> mapped to ToneMap.PLATE_TONE = 30.0)
# - GLYPH_HEX has L* ~ 82, Chroma > 35 (bright chromatic -> mapped to ToneMap.y_hi = 92.0, weight = 1.0)
PLATE_HEX = "#1a2636"
GLYPH_HEX = "#7dd3fc"

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CRAFT_DIR = REPO_ROOT / "sources" / "craft"
DEFAULT_AUTO_DIR = REPO_ROOT / "sources" / "auto"
DEFAULT_YAMIS_DIR = Path(os.path.expanduser("~/.local/share/icons/YAMIS"))
DEFAULT_PAPIRUS_DIR = Path("/usr/share/icons/Papirus/64x64/apps")
DEFAULT_OUT_DIR = REPO_ROOT / "OneYou"


def wrap_in_plate(inner_svg_body: str, transform: str, clip: bool = False) -> str:
    """Wrap a monochrome vector glyph inside a 192x192 Material You circular plate."""
    defs = '  <defs><clipPath id="c"><circle cx="96" cy="96" r="88"/></clipPath></defs>\n' if clip else ''
    g_open = f'  <g clip-path="url(#c)"><g transform="{transform}">' if clip else f'  <g transform="{transform}">'
    g_close = '  </g></g>' if clip else '  </g>'
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192" fill="none">\n'
        f'{defs}'
        f'  <circle cx="96" cy="96" r="88" fill="{PLATE_HEX}"/>\n'
        f'{g_open}\n'
        f'    {inner_svg_body}\n'
        f'{g_close}\n'
        '</svg>\n'
    )


def convert_craft_woodcut_svg(svg_path: Path) -> str:
    """Convert a Storyteller *Craft SVG into a Bicolor Woodcut circular icon."""
    raw = svg_path.read_text(encoding="utf-8", errors="ignore")
    if "artcraft-launcher" in svg_path.name:
        m = re.search(r"<path\b[^>]*>", raw)
        body = m.group(0).replace("#4e7bfb", GLYPH_HEX) if m else ""
        return wrap_in_plate(body, "translate(46, 52) scale(0.86)")

    body = re.sub(r"^.*?<svg[^>]*>", "", raw, count=1, flags=re.S)
    body = re.sub(r"</svg\s*>\s*$", "", body, flags=re.S)
    body = re.sub(r"<!--.*?-->", "", body, flags=re.S)
    body = re.sub(r"<(?:defs|title)\b.*?</(?:defs|title)\s*>", "", body, flags=re.S)
    body = re.sub(r'<g\s+clip-path="[^"]*"\s*>', "<g>", body)
    body = re.sub(r'<rect\b[^>]*width="(?:512|480)"[^>]*/\s*>', "", body)
    body = re.sub(r"#efe9dc", GLYPH_HEX, body, flags=re.I)
    body = re.sub(
        r"#0b0b0c|#f26b1d|#1f9d55|#3b5bdb|#14a9c4|#2f7bf5|#f2a516|"
        r"#02da96|#12a58a|#e8573f|#8b5cf6|#e0368f|#7bb51c|#14a3c7",
        PLATE_HEX,
        body,
        flags=re.I,
    )
    wrapped = wrap_in_plate(body.strip(), "translate(34.56, 34.56) scale(0.24)", clip=True)
    if len(body) <= 50000:
        return wrapped

    # QtSvg (QSvgRenderer, used by Quickshell) truncates single <path> elements that exceed
    # its internal path-element complexity limit (~2,000 subpaths / >300KB in Storyteller's raw
    # woodcut SVGs), which caused the dark woodcut grooves layer to be dropped in Qt apps.
    # Simplify the composite woodcut into a single QtSvg-safe evenodd path (<37KB).
    res = subprocess.run(["resvg", "-w", "512", "-h", "512", "-", "-c"], input=wrapped.encode(), capture_output=True)
    if res.returncode != 0 or not res.stdout:
        return wrapped
    img = Image.open(io.BytesIO(res.stdout)).convert("RGBA")
    arr = np.array(img)
    fg = ((arr[:, :, 2] > 140) & (arr[:, :, 3] > 128)).astype(np.uint8) * 255
    contours, _ = cv2.findContours(fg, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
    parts = []
    for c in contours:
        if cv2.contourArea(c) < 2.5:
            continue
        approx = cv2.approxPolyDP(c, 0.4, True)
        pts = approx.reshape(-1, 2)
        if len(pts) >= 3:
            parts.append("M" + "L".join(f"{x},{y}" for x, y in pts) + "Z")
    if not parts:
        return wrapped
    d_str = "".join(parts)
    return wrap_in_plate(f'<path fill="{GLYPH_HEX}" fill-rule="evenodd" d="{d_str}"/>', "scale(0.375)")


def convert_yamis_app_svg(svg_path: Path) -> str:
    """Convert a YAMIS filled monochrome SVG into a Material You circular plate icon."""
    raw = svg_path.read_text(encoding="utf-8", errors="ignore")
    svg_tag = re.search(r"<svg\b[^>]*>", raw, flags=re.S)
    vb_w, vb_h = 16.933, 16.933
    vb_x, vb_y = 0.0, 0.0
    if svg_tag:
        vb_m = re.search(
            r'viewBox\s*=\s*["\']\s*([-\d.]+)[,\s]+([-\d.]+)[,\s]+([\d.]+)[,\s]+([\d.]+)',
            svg_tag.group(0),
        )
        if vb_m:
            vb_x, vb_y, vb_w, vb_h = (float(x) for x in vb_m.groups())
        else:
            w_m = re.search(r'\bwidth\s*=\s*["\']([\d.]+)', svg_tag.group(0))
            h_m = re.search(r'\bheight\s*=\s*["\']([\d.]+)', svg_tag.group(0))
            if w_m and h_m:
                vb_w, vb_h = float(w_m.group(1)), float(h_m.group(1))

    body = re.sub(r"^.*?<svg[^>]*>", "", raw, count=1, flags=re.S)
    body = re.sub(r"</svg\s*>\s*$", "", body, flags=re.S)
    body = re.sub(
        r"<(?:sodipodi:namedview|defs|metadata)\b.*?</(?:sodipodi:namedview|defs|metadata)\s*>",
        "",
        body,
        flags=re.S,
    )
    body = re.sub(r"<(?:sodipodi:namedview|defs|metadata)\b[^>]*/\s*>", "", body, flags=re.S)
    body = re.sub(r"currentColor|#d8dee9|#eceff4|#e5e9f0|#ffffff", GLYPH_HEX, body, flags=re.I)
    body = re.sub(r"#3b4252|#2e3440|#4c566a", PLATE_HEX, body, flags=re.I)

    target_box = 102.0
    scale = target_box / max(vb_w, vb_h, 0.001)
    tx = 96.0 - (vb_x + vb_w / 2.0) * scale
    ty = 96.0 - (vb_y + vb_h / 2.0) * scale
    return wrap_in_plate(body.strip(), f"translate({tx:.2f}, {ty:.2f}) scale({scale:.4f})")


def convert_yamis_ui_svg(svg_path: Path) -> str:
    """Normalize non-app YAMIS SVGs (places, actions, status, etc.) to use GLYPH_HEX."""
    raw = svg_path.read_text(encoding="utf-8", errors="ignore")
    return re.sub(r"#d8dee9|#eceff4|#e5e9f0", GLYPH_HEX, raw, flags=re.I)


def convert_lawnicon_svg(svg_path: Path) -> str:
    """Convert a 192x192 Lawnicons SVG into a Material You circular plate icon."""
    raw = svg_path.read_text(encoding="utf-8", errors="ignore")
    body = re.sub(r"^.*?<svg[^>]*>", "", raw, count=1, flags=re.S)
    body = re.sub(r"</svg\s*>\s*$", "", body, flags=re.S).strip()

    body = re.sub(r"#[0]{3,6}\b", GLYPH_HEX, body)
    body = re.sub(r"\bblack\b", GLYPH_HEX, body)

    def ensure_paint(m):
        tag = m.group(0)
        if "fill=" not in tag and "stroke=" not in tag and "style=" not in tag:
            if tag.endswith("/>"):
                return tag[:-2] + f' fill="{GLYPH_HEX}"/>'
            return tag[:-1] + f' fill="{GLYPH_HEX}">'
        return tag

    body = re.sub(r"<(?:path|circle|rect|polygon|ellipse)\b[^>]*>", ensure_paint, body)
    return wrap_in_plate(body, "translate(42, 42) scale(0.5625)")


def load_any_icon_rgba(path: str, size: int = 256) -> Image.Image:
    """Render SVG or raster icon to a centered RGBA PIL image."""
    with open(path, "rb") as f:
        head = f.read(1024)
    if path.lower().endswith(".svg") or b"<svg" in head.lower():
        res = subprocess.run(["resvg", "-w", str(size), "-h", str(size), path, "-c"], capture_output=True)
        if res.returncode == 0 and res.stdout:
            return Image.open(io.BytesIO(res.stdout)).convert("RGBA")
    im = Image.open(path).convert("RGBA")
    im.thumbnail((size, size), Image.Resampling.LANCZOS)
    canvas = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    canvas.paste(im, ((size - im.width) // 2, (size - im.height) // 2))
    return canvas


def auto_extract_silhouette_svg(path: str) -> str:
    """
    Automatically strip any non-circular plate (square, squircle, cut-corner Qt tile,
    two-tone diagonal split, etc.) and vectorize the inner foreground glyph into a
    circular OneYou SVG.
    """
    try:
        im = load_any_icon_rgba(path, 256)
    except Exception:
        return ""
    arr = np.array(im)
    alpha = arr[..., 3]
    vis = alpha > 40
    if vis.sum() < 32:
        return ""

    lab = cv2.cvtColor(arr[..., :3], cv2.COLOR_RGB2Lab).astype(np.float32)
    ys, xs = np.where(vis)
    y0, y1, x0, x1 = ys.min(), ys.max(), xs.min(), xs.max()
    bbox_vis = vis[y0 : y1 + 1, x0 : x1 + 1]
    coverage = bbox_vis.mean()

    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (15, 15))
    eroded = cv2.erode(vis.astype(np.uint8), kernel) > 0
    ring = vis & (~eroded)

    mask = None
    if coverage > 0.55 and ring.sum() > 20:
        ring_pts = lab[ring]
        step = max(1, len(ring_pts) // 48)
        palette_ring = ring_pts[::step]
        dists = np.linalg.norm(lab[:, :, None, :] - palette_ring[None, None, :, :], axis=-1).min(axis=-1)
        fg_mask = eroded & (dists > 22.0)
        fg_ratio = fg_mask.sum() / max(1, vis.sum())
        if 0.02 <= fg_ratio <= 0.75:
            fg_L = lab[..., 0][fg_mask]
            if fg_L.std() > 25.0:
                med_ring_L = np.median(ring_pts[:, 0])
                if np.median(fg_L) > med_ring_L:
                    thresh = np.percentile(fg_L, 25)
                    fg_mask = fg_mask & (lab[..., 0] >= thresh)
                else:
                    thresh = np.percentile(fg_L, 75)
                    fg_mask = fg_mask & (lab[..., 0] <= thresh)
            mask = (fg_mask.astype(np.uint8)) * 255

    if mask is None or (mask > 127).sum() < 30:
        vis_L = lab[..., 0][vis].astype(np.uint8)
        if vis_L.std() > 22.0:
            t_val, _ = cv2.threshold(vis_L, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            bright = vis & (lab[..., 0] >= t_val)
            dark = vis & (lab[..., 0] < t_val)
            chosen = bright if bright.sum() >= dark.sum() * 0.6 else dark
            mask = (chosen.astype(np.uint8)) * 255
        else:
            mask = (vis.astype(np.uint8)) * 255

    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (3, 3)))
    mys, mxs = np.where(mask > 127)
    if len(mys) < 10:
        return ""
    my0, my1, mx0, mx1 = mys.min(), mys.max(), mxs.min(), mxs.max()
    crop = mask[my0 : my1 + 1, mx0 : mx1 + 1]
    ch, cw = crop.shape
    target = 96.0
    scale = target / max(ch, cw)
    nw, nh = max(1, int(round(cw * scale))), max(1, int(round(ch * scale)))
    resized = cv2.resize(crop, (nw, nh), interpolation=cv2.INTER_AREA)
    canvas192 = np.zeros((192, 192), dtype=np.uint8)
    ox, oy = (192 - nw) // 2, (192 - nh) // 2
    canvas192[oy : oy + nh, ox : ox + nw] = (resized > 110).astype(np.uint8) * 255

    contours, _ = cv2.findContours(canvas192, cv2.RETR_CCOMP, cv2.CHAIN_APPROX_TC89_KCOS)
    parts = []
    for c in contours:
        if cv2.contourArea(c) < 3:
            continue
        pts = c.reshape(-1, 2)
        parts.append("M" + "L".join(f"{x},{y}" for x, y in pts) + "Z")
    if not parts:
        return ""
    d_str = "".join(parts)
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 192 192" width="192" height="192" fill="none">\n'
        f'  <circle cx="96" cy="96" r="88" fill="{PLATE_HEX}"/>\n'
        f'  <path fill="{GLYPH_HEX}" fill-rule="evenodd" d="{d_str}"/>\n'
        "</svg>\n"
    )


def safe_symlink(target_name: str, link_path: Path) -> bool:
    """Create a relative symlink in the same folder if `link_path` does not exist yet."""
    if os.path.lexists(link_path) or link_path.name == target_name:
        return False
    try:
        os.symlink(target_name, link_path)
        return True
    except OSError:
        return False


# High-value Linux desktop aliases (AppImages, IDEs, Flatpaks, Qt tools, Waydroid, etc.)
EXTRA_LINUX_ALIASES = {
    "antigravity-ide": "antigravity",
    "google-antigravity": "antigravity",
    "figma-linux-next": "figma",
    "photoshop": "adobe-photoshop",
    "photoshop-cc": "adobe-photoshop",
    "jetbrains-studio": "android-studio",
    "jetbrains-idea": "intellij-idea",
    "prism_launcher": "prismlauncher",
    "org.prismlauncher.prismlauncher": "prismlauncher",
    "org.kde.konsole": "konsole",
    "org.gnome.ptyxis": "utilities-terminal",
    "org.dosbox-staging.dosbox-staging": "dosbox",
    "linguist-qt6": "linguist",
    "designer-qt6": "QtProject-designer",
    "assistant-qt6": "QtProject-assistant",
    "qdbusviewer-qt6": "QtProject-qdbusviewer",
    "java-25-openjdk": "java-21-openjdk",
    "droidcam-icon": "droidcam",
    "regedit": "wine",
    "winefile": "wine",
    "winemine": "wine",
    "winhelp": "wine",
    "wordpad": "wine",
    "com.android.vending": "google_play_store",
    "com.google.android.apps.messaging": "google_messages",
    "com.google.android.contacts": "google_contacts",
}


_IMAGE_EXTS = {".svg", ".png", ".xpm", ".jpg", ".jpeg", ".bmp", ".gif"}


def strip_image_ext(name: str) -> str:
    """Strip image extension only, preserving reverse-domain IDs like org.quickshell."""
    stem, ext = os.path.splitext(name)
    return stem if ext.lower() in _IMAGE_EXTS else name


def _find_system_icon_sources() -> list[tuple[str, str]]:
    """Use the same icon discovery rules as `recolor_icons.py` to locate unmapped .desktop icons."""
    desktop_dirs = [
        "/usr/share/applications",
        "/usr/local/share/applications",
        os.path.expanduser("~/.local/share/applications"),
        "/var/lib/flatpak/exports/share/applications",
        os.path.expanduser("~/.local/share/flatpak/exports/share/applications"),
        "/var/lib/snapd/desktop/applications",
    ]
    icon_roots = [
        os.path.expanduser("~/.local/share/icons/hicolor"),
        "/var/lib/flatpak/exports/share/icons/hicolor",
        os.path.expanduser("~/.local/share/flatpak/exports/share/icons/hicolor"),
        "/usr/share/icons/hicolor",
        "/usr/share/icons/Papirus",
        "/usr/share/icons/breeze",
        os.path.expanduser("~/.local/share/icons/WhiteSur"),
        os.path.expanduser("~/.local/share/icons/kora"),
        os.path.expanduser("~/.icons/Deepin2022"),
    ]
    pixmap_dirs = ["/usr/share/pixmaps", "/usr/local/share/pixmaps", "/usr/share/icons"]

    icon_index = {}
    for priority_idx, root in enumerate(icon_roots):
        if not os.path.isdir(root):
            continue
        base_bonus = (len(icon_roots) - priority_idx) * 10000
        for r, _, files in os.walk(root):
            if "apps" not in r.lower():
                continue
            rank = base_bonus + (1000 if "scalable" in r.lower() else (512 if "512" in r else (256 if "256" in r else 128)))
            for f in files:
                if f.lower().endswith((".svg", ".png")):
                    stem = strip_image_ext(f).lower()
                    if stem not in icon_index or rank > icon_index[stem][1]:
                        icon_index[stem] = (os.path.join(r, f), rank)

    for pd in pixmap_dirs:
        if not os.path.isdir(pd):
            continue
        for f in os.listdir(pd):
            p = os.path.join(pd, f)
            if os.path.isfile(p) and f.lower().endswith((".svg", ".png")):
                stem = strip_image_ext(f).lower()
                if stem not in icon_index:
                    icon_index[stem] = (p, 10)

    out = []
    for d in desktop_dirs:
        if not os.path.isdir(d):
            continue
        for df in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(df)
                ic = cp.get("Desktop Entry", "Icon", fallback="").strip()
            except Exception:
                continue
            if not ic:
                continue
            if ic.startswith("/"):
                df_stem = os.path.splitext(os.path.basename(df))[0]
                ic_stem = strip_image_ext(os.path.basename(ic))
                src = ic if os.path.isfile(ic) else None
                if not src:
                    for ext in (".svg", ".png"):
                        if os.path.isfile(ic + ext):
                            src = ic + ext
                            break
                if src:
                    out.append((df_stem, src))
                    if ic_stem.lower() != df_stem.lower():
                        out.append((ic_stem, src))
            else:
                ic_stem = strip_image_ext(os.path.basename(ic))
                low_stem = ic_stem.lower()
                for cand in (low_stem, low_stem.replace("_", "-"), low_stem.replace("-", "_"),
                             low_stem.replace("_", "").replace("-", ""), low_stem.split(".")[-1]):
                    hit = icon_index.get(cand)
                    if hit:
                        out.append((ic_stem, hit[0]))
                        break
    return out


def build(out_dir: Path, craft_dir: Path, auto_dir: Path, yamis_dir: Path, lawn_dir: Path | None, papirus_dir: Path):
    if out_dir.exists():
        shutil.rmtree(out_dir)
    apps_out = out_dir / "apps" / "scalable"
    prefs_out = out_dir / "preferences" / "scalable"
    apps_out.mkdir(parents=True, exist_ok=True)
    prefs_out.mkdir(parents=True, exist_ok=True)
    auto_dir.mkdir(parents=True, exist_ok=True)

    written_lower = {}  # lower_stem -> actual filename (e.g. "firefox.svg")
    written_exact = set()  # exact stem (case-sensitive)
    counts = {"craft": 0, "yamis": 0, "lawnicons": 0, "auto": 0, "symlinks": 0}

    def register(fname: str):
        stem = fname[:-4]
        written_exact.add(stem)
        low = stem.lower()
        if low not in written_lower:
            written_lower[low] = fname
        if f"{low}.svg" != fname and low not in written_exact:
            if safe_symlink(fname, apps_out / f"{low}.svg"):
                written_exact.add(low)
                counts["symlinks"] += 1

    # ── Priority 1: Storyteller *Craft Suite (Woodcut Bicolor) ───────────────
    if craft_dir.is_dir():
        for src in sorted(craft_dir.glob("*.svg")):
            svg_text = convert_craft_woodcut_svg(src)
            dst_name = src.name
            (apps_out / dst_name).write_text(svg_text, encoding="utf-8")
            register(dst_name)
            counts["craft"] += 1

            stem = src.stem
            if stem.startswith("ai.storyteller."):
                short = stem.replace("ai.storyteller.", "")
                for alias in (short, short.replace("-launcher", "")):
                    if alias and safe_symlink(dst_name, apps_out / f"{alias}.svg"):
                        register(f"{alias}.svg")
                        counts["symlinks"] += 1

    # ── Priority 2: YAMIS (Filled Monochrome Silhouettes: apps + preferences) ─
    for yamis_sub, also_in_prefs in (("apps/scalable", False), ("preferences/scalable", True)):
        src_folder = yamis_dir / yamis_sub
        if not src_folder.is_dir():
            continue
        # Real SVG files
        for entry in sorted(src_folder.iterdir()):
            if not entry.name.endswith(".svg") or entry.is_symlink():
                continue
            converted = None
            try:
                converted = convert_yamis_app_svg(entry)
            except Exception:
                continue
            if also_in_prefs:
                (prefs_out / entry.name).write_text(converted, encoding="utf-8")
            if entry.stem.lower() in written_lower:
                if entry.stem not in written_exact:
                    if safe_symlink(written_lower[entry.stem.lower()], apps_out / entry.name):
                        register(entry.name)
                        counts["symlinks"] += 1
                continue
            (apps_out / entry.name).write_text(converted, encoding="utf-8")
            register(entry.name)
            counts["yamis"] += 1

        # Symlinks
        for entry in sorted(src_folder.iterdir()):
            if not entry.name.endswith(".svg") or not entry.is_symlink():
                continue
            target_name = os.path.basename(os.readlink(entry))
            if also_in_prefs:
                safe_symlink(target_name, prefs_out / entry.name)
            if entry.stem.lower() in written_lower:
                if entry.stem not in written_exact:
                    if safe_symlink(written_lower[entry.stem.lower()], apps_out / entry.name):
                        register(entry.name)
                        counts["symlinks"] += 1
                continue
            target_stem = os.path.splitext(target_name)[0].lower()
            if target_stem in written_lower:
                if safe_symlink(written_lower[target_stem], apps_out / entry.name):
                    register(entry.name)
                    counts["symlinks"] += 1

    # Copy non-app YAMIS folders (places, status, actions, devices, categories, mimetypes, emblems)
    for sub in ("actions/16", "actions/scalable", "categories/scalable", "devices/scalable",
                "emblems/scalable", "places/16", "places/scalable", "mimetypes/scalable", "status/scalable"):
        src_sub = yamis_dir / sub
        if not src_sub.is_dir():
            continue
        dst_sub = out_dir / sub
        dst_sub.mkdir(parents=True, exist_ok=True)
        for entry in os.listdir(src_sub):
            sp = src_sub / entry
            dp = dst_sub / entry
            if sp.is_symlink():
                safe_symlink(os.readlink(sp), dp)
            elif sp.is_file() and entry.endswith(".svg"):
                dp.write_text(convert_yamis_ui_svg(sp), encoding="utf-8")

    # ── Priority 3: Lawnicons (10,200+ Android 16 icons) ─────────────────────
    if lawn_dir and (lawn_dir / "svgs").is_dir():
        svgs_dir = lawn_dir / "svgs"
        for src in sorted(svgs_dir.glob("*.svg")):
            stem_lower = src.stem.lower()
            if stem_lower in written_lower:
                continue
            hyphen_stem = stem_lower.replace("_", "-")
            try:
                svg_text = convert_lawnicon_svg(src)
                (apps_out / src.name).write_text(svg_text, encoding="utf-8")
                register(src.name)
                counts["lawnicons"] += 1
                if hyphen_stem != stem_lower and hyphen_stem not in written_lower:
                    if safe_symlink(src.name, apps_out / f"{hyphen_stem}.svg"):
                        register(f"{hyphen_stem}.svg")
                        counts["symlinks"] += 1
            except Exception:
                pass

        appfilter = lawn_dir / "app" / "assets" / "appfilter.xml"
        if appfilter.is_file():
            try:
                root = ET.parse(appfilter).getroot()
                for item in root.findall("item"):
                    comp = item.get("component", "")
                    drawable = item.get("drawable", "")
                    m = re.match(r"ComponentInfo\{([^/]+)/", comp)
                    if m and drawable and drawable.lower() in written_lower:
                        pkg = m.group(1).lower()
                        target_file = written_lower[drawable.lower()]
                        if pkg not in written_lower:
                            if safe_symlink(target_file, apps_out / f"{pkg}.svg"):
                                register(f"{pkg}.svg")
                                counts["symlinks"] += 1
            except Exception:
                pass

    # ── Priority 4: Linux Freedesktop Aliases (Papirus + .desktop Metadata) ──
    if papirus_dir.is_dir():
        for entry in sorted(os.listdir(papirus_dir)):
            if not entry.endswith(".svg"):
                continue
            p = papirus_dir / entry
            if not p.is_symlink():
                continue
            alias_stem = entry[:-4].lower()
            if alias_stem in written_lower:
                if entry[:-4] not in written_exact:
                    if safe_symlink(written_lower[alias_stem], apps_out / entry):
                        register(entry)
                        counts["symlinks"] += 1
                continue
            target_stem = os.path.splitext(os.path.basename(os.readlink(p)))[0].lower()
            for cand in (target_stem, target_stem.replace("-", "_"), target_stem.split(".")[-1]):
                if cand in written_lower:
                    if safe_symlink(written_lower[cand], apps_out / entry):
                        register(entry)
                        counts["symlinks"] += 1
                    break

    for alias_stem, target_stem in EXTRA_LINUX_ALIASES.items():
        if alias_stem.lower() not in written_lower and target_stem.lower() in written_lower:
            if safe_symlink(written_lower[target_stem.lower()], apps_out / f"{alias_stem}.svg"):
                register(f"{alias_stem}.svg")
                counts["symlinks"] += 1

    # Match .desktop Icon/Name/StartupWMClass (e.g. Steam games, JetBrains UUIDs, AppImages)
    for d in ("/usr/share/applications", "/usr/local/share/applications",
              os.path.expanduser("~/.local/share/applications"),
              "/var/lib/flatpak/exports/share/applications",
              os.path.expanduser("~/.local/share/flatpak/exports/share/applications")):
        if not os.path.isdir(d):
            continue
        for df in sorted(glob.glob(os.path.join(d, "*.desktop"))):
            cp = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                cp.read(df)
                ic = cp.get("Desktop Entry", "Icon", fallback="").strip()
                app_name = cp.get("Desktop Entry", "Name", fallback="").strip()
                wm_class = cp.get("Desktop Entry", "StartupWMClass", fallback="").strip()
            except Exception:
                continue
            if not ic:
                continue
            df_stem = os.path.splitext(os.path.basename(df))[0]
            ic_stem = strip_image_ext(os.path.basename(ic))
            clean_name = re.sub(r"\s*\([^)]*\)|\s+\d+(?:\.\d+)*$|[™®]", "", app_name).strip().lower()
            for name in (df_stem, ic_stem):
                low = name.lower()
                if low in written_lower:
                    if name not in written_exact:
                        if safe_symlink(written_lower[low], apps_out / f"{name}.svg"):
                            register(f"{name}.svg")
                            counts["symlinks"] += 1
                    continue
                tail = low.split("_")[-1] if low.startswith("appimagekit_") else low
                if low.startswith("jetbrains-idea-"):
                    tail = "intellij-idea"
                cands = [
                    tail,
                    tail.replace("-", "_"),
                    tail.replace("_", "-"),
                    tail.replace("_", "").replace("-", ""),
                    tail.split(".")[-1],
                    clean_name.replace(" ", "_"),
                    clean_name.replace(" ", "-"),
                    clean_name.replace(" ", ""),
                    wm_class.lower(),
                    wm_class.lower().split(".")[-1],
                ]
                for cand in cands:
                    if cand and cand in written_lower:
                        if safe_symlink(written_lower[cand], apps_out / f"{name}.svg"):
                            register(f"{name}.svg")
                            counts["symlinks"] += 1
                        break

    # ── Priority 5: Auto-Silhouette Extractor (`sources/auto` + live scan) ───
    def register_auto_aliases(dst_name: str):
        stem = dst_name[:-4]
        low = stem.lower()
        short_cands = []
        if low.startswith("appimagekit_") and "_" in low[12:]:
            short_cands.append(low.split("_", 2)[2])
        if "." in low:
            tail = low.split(".")[-1]
            short_cands.append(tail)
            if tail.endswith("communityedition"):
                short_cands.append(tail[:-16])
        for sc in short_cands:
            if sc and sc not in written_lower:
                if safe_symlink(dst_name, apps_out / f"{sc}.svg"):
                    register(f"{sc}.svg")
                    counts["symlinks"] += 1

    # First install any pre-extracted SVGs already stored in `sources/auto/`
    for src in sorted(auto_dir.glob("*.svg")):
        if src.stem.lower() not in written_lower:
            shutil.copy2(src, apps_out / src.name)
            register(src.name)
            register_auto_aliases(src.name)
            counts["auto"] += 1

    # Then scan the system for any remaining .desktop icons and auto-extract their silhouette
    for icon_name, src_path in _find_system_icon_sources():
        low = icon_name.lower()
        if low in written_lower:
            if icon_name not in written_exact:
                if safe_symlink(written_lower[low], apps_out / f"{icon_name}.svg"):
                    register(f"{icon_name}.svg")
                    counts["symlinks"] += 1
            continue
        svg_text = auto_extract_silhouette_svg(src_path)
        if svg_text:
            dst_name = f"{icon_name}.svg"
            (auto_dir / dst_name).write_text(svg_text, encoding="utf-8")
            (apps_out / dst_name).write_text(svg_text, encoding="utf-8")
            register(dst_name)
            register_auto_aliases(dst_name)
            counts["auto"] += 1

    _write_index_theme(out_dir)

    print(
        f"Built OneYou theme at {out_dir}:\n"
        f"  Priority 1 (*Craft Woodcut)  : {counts['craft']} icons\n"
        f"  Priority 2 (YAMIS Filled)    : {counts['yamis']} icons\n"
        f"  Priority 3 (Lawnicons)       : {counts['lawnicons']} icons\n"
        f"  Priority 4 (Linux Symlinks)  : {counts['symlinks']} aliases\n"
        f"  Priority 5 (Auto-Silhouette) : {counts['auto']} extracted icons\n"
        f"  Total app entries            : {sum(counts.values())}"
    )


def _write_index_theme(out_dir: Path):
    subdirs = []
    for sub in ("apps/scalable", "preferences/scalable", "places/scalable", "places/16",
                "actions/16", "actions/scalable", "categories/scalable", "devices/scalable",
                "emblems/scalable", "mimetypes/scalable", "status/scalable"):
        if (out_dir / sub).is_dir():
            subdirs.append(sub)

    ctx_map = {
        "apps": "Applications",
        "preferences": "Applications",
        "places": "Places",
        "actions": "Actions",
        "categories": "Categories",
        "devices": "Devices",
        "emblems": "Emblems",
        "mimetypes": "MimeTypes",
        "status": "Status",
    }

    lines = [
        "[Icon Theme]",
        "Name=OneYou",
        "Comment=Material You / Android 16 Monochrome Icon Pack (Craft + YAMIS + Lawnicons)",
        "Inherits=YAMIS,Papirus-Dark,breeze-dark,Adwaita,hicolor",
        "DisplayDepth=32",
        "FollowsColorScheme=true",
        "Example=folder",
        f"Directories={','.join(subdirs)}",
        "",
    ]
    for sub in subdirs:
        cat = sub.split("/")[0]
        context = ctx_map.get(cat, "Applications")
        if sub.endswith("/16"):
            lines += [f"[{sub}]", f"Context={context}", "Size=24", "MinSize=8", "MaxSize=28", "Type=Scalable", ""]
        else:
            lines += [f"[{sub}]", f"Context={context}", "Size=64", "MinSize=16", "MaxSize=512", "Type=Scalable", ""]

    (out_dir / "index.theme").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Build the OneYou Material You icon theme.")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="Output theme directory")
    parser.add_argument("--craft-dir", type=Path, default=DEFAULT_CRAFT_DIR, help="Directory with *Craft SVGs")
    parser.add_argument("--auto-dir", type=Path, default=DEFAULT_AUTO_DIR, help="Directory for auto-extracted SVGs")
    parser.add_argument("--yamis-dir", type=Path, default=DEFAULT_YAMIS_DIR, help="Path to YAMIS icon theme")
    parser.add_argument("--lawnicons-dir", type=Path, default=None, help="Path to Lawnicons repo (cloned on demand if omitted)")
    parser.add_argument("--papirus-dir", type=Path, default=DEFAULT_PAPIRUS_DIR, help="Path to Papirus 64x64/apps for Linux aliases")
    args = parser.parse_args()

    lawn_path = args.lawnicons_dir
    tmp_lawn = None
    if lawn_path is None:
        tmp_lawn = tempfile.mkdtemp(prefix="lawnicons-")
        print("Cloning Lawnicons SVGs (shallow sparse checkout)...")
        subprocess.run(
            ["git", "clone", "--depth", "1", "--filter=blob:none", "--sparse",
             "https://github.com/LawnchairLauncher/lawnicons.git", tmp_lawn],
            check=True,
        )
        subprocess.run(["git", "-C", tmp_lawn, "sparse-checkout", "set", "svgs", "app/assets"], check=True)
        lawn_path = Path(tmp_lawn)

    try:
        build(args.out, args.craft_dir, args.auto_dir, args.yamis_dir, lawn_path, args.papirus_dir)
    finally:
        if tmp_lawn and os.path.isdir(tmp_lawn):
            shutil.rmtree(tmp_lawn, ignore_errors=True)

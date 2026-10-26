#!/usr/bin/env python3
"""
ii-icon-pack plate shapes
=========================
Every app icon in the pack is a 192x192 SVG drawn as a *plate* (the container) with a
monochrome *glyph* on top. This module owns the plate geometry, so the same icon can be
rendered as a circle, an Android squircle or any Material 3 Expressive shape.

The Material shapes come from `material_shapes.json`, exported from the exact shape library
Quickshell `ii` draws its UI with (see `tools/export_material_shapes.js`), so an icon plate and
a `MaterialShape` in the shell with the same name are the same outline.

`reshape_svg()` works on any icon this pack has ever produced: the original
`<circle cx="96" cy="96" r="88">` plates as well as plates written by a previous reshape, so a
pack can be reshaped from whatever shape it currently ships in. Only the standard library is
used, so the installer runs on any machine with Python 3.
"""
import json
import re
from pathlib import Path

# The base tones every converter in `build_theme.py` paints with (see the note there on why
# these two values are calibrated for `recolor_icons.py`).
PLATE_HEX = "#1a2636"
GLYPH_HEX = "#7dd3fc"

CANVAS = 192.0
CENTER = 96.0
PLATE_BOX = 176.0  # the original circle: r=88 inside the 192 canvas

_MATERIAL = json.loads((Path(__file__).resolve().parent / "material_shapes.json").read_text(encoding="utf-8"))

# The adaptive-icon masks Android launchers ship besides the plain circle (AOSP `config_icon_mask`).
_AOSP = {
    "squircle": "M0.5 0C0.1 0 0 0.1 0 0.5S0.1 1 0.5 1S1 0.9 1 0.5S0.9 0 0.5 0Z",
    "teardrop": "M0.5 0A0.5 0.5 0 0 1 1 0.5L1 0.85A0.15 0.15 0 0 1 0.85 1L0.5 1A0.5 0.5 0 0 1 0.5 0Z",
    "rounded-square": "M0.3 0L0.7 0A0.3 0.3 0 0 1 1 0.3L1 0.7A0.3 0.3 0 0 1 0.7 1L0.3 1A0.3 0.3 0 0 1 0 0.7L0 0.3A0.3 0.3 0 0 1 0.3 0Z",
}

# key -> (path source, display name, glyph factor, Material shape name in the shell or "")
#
# The glyph factor shrinks the logo on shapes whose outline cuts deep into the plate (cookies,
# clovers, bursts) so it never touches a scallop. Shapes whose area would drop under the 40%
# canvas share `recolor_icons.py` needs to recognise a plate (Boom, Arrow, SemiCircle,
# Triangle, PixelTriangle, Heart's tip) are left out of the catalog on purpose.
SHAPES = {
    "circle":         (_MATERIAL["Circle"], "Circle", 1.00, "Circle"),
    "squircle":       (_AOSP["squircle"], "Squircle", 1.00, ""),
    "rounded-square": (_AOSP["rounded-square"], "Rounded", 1.00, ""),
    "square":         (_MATERIAL["Square"], "Square", 1.00, "Square"),
    "teardrop":       (_AOSP["teardrop"], "Teardrop", 1.00, ""),
    "slanted":        (_MATERIAL["Slanted"], "Slanted", 0.95, "Slanted"),
    "arch":           (_MATERIAL["Arch"], "Arch", 0.95, "Arch"),
    "fan":            (_MATERIAL["Fan"], "Fan", 0.90, "Fan"),
    "bun":            (_MATERIAL["Bun"], "Bun", 0.90, "Bun"),
    "ghostish":       (_MATERIAL["Ghostish"], "Ghost-ish", 0.92, "Ghostish"),
    "pill":           (_MATERIAL["Pill"], "Pill", 0.85, "Pill"),
    "pentagon":       (_MATERIAL["Pentagon"], "Pentagon", 0.88, "Pentagon"),
    "gem":            (_MATERIAL["Gem"], "Gem", 0.92, "Gem"),
    "diamond":        (_MATERIAL["Diamond"], "Diamond", 0.78, "Diamond"),
    "clamshell":      (_MATERIAL["ClamShell"], "Clamshell", 0.85, "ClamShell"),
    "pixel-circle":   (_MATERIAL["PixelCircle"], "Pixel circle", 0.95, "PixelCircle"),
    "sunny":          (_MATERIAL["Sunny"], "Sunny", 0.88, "Sunny"),
    "very-sunny":     (_MATERIAL["VerySunny"], "Very sunny", 0.84, "VerySunny"),
    "cookie-4":       (_MATERIAL["Cookie4Sided"], "Cookie 4", 0.90, "Cookie4Sided"),
    "cookie-6":       (_MATERIAL["Cookie6Sided"], "Cookie 6", 0.90, "Cookie6Sided"),
    "cookie-7":       (_MATERIAL["Cookie7Sided"], "Cookie 7", 0.90, "Cookie7Sided"),
    "cookie-9":       (_MATERIAL["Cookie9Sided"], "Cookie 9", 0.90, "Cookie9Sided"),
    "cookie-12":      (_MATERIAL["Cookie12Sided"], "Cookie 12", 0.90, "Cookie12Sided"),
    "clover-4":       (_MATERIAL["Clover4Leaf"], "Clover 4", 0.86, "Clover4Leaf"),
    "clover-8":       (_MATERIAL["Clover8Leaf"], "Clover 8", 0.86, "Clover8Leaf"),
    "soft-burst":     (_MATERIAL["SoftBurst"], "Soft burst", 0.80, "SoftBurst"),
    "soft-boom":      (_MATERIAL["SoftBoom"], "Soft boom", 0.80, "SoftBoom"),
    "flower":         (_MATERIAL["Flower"], "Flower", 0.78, "Flower"),
    "puffy":          (_MATERIAL["Puffy"], "Puffy", 0.84, "Puffy"),
    "puffy-diamond":  (_MATERIAL["PuffyDiamond"], "Puffy diamond", 0.80, "PuffyDiamond"),
}

DEFAULT_SHAPE = "circle"

_TOKEN_RE = re.compile(r"[MLCSQAZmlcsqaz]|-?(?:\d+\.?\d*|\.\d+)(?:[eE][-+]?\d+)?")
_ARGS = {"M": 2, "L": 2, "C": 6, "S": 4, "Q": 4, "A": 7, "Z": 0}


def normalize_shape(name: str) -> str:
    """Accept `Cookie7Sided`, `cookie_7`, `Cookie 7` ... and return the catalog key."""
    key = re.sub(r"[\s_]+", "-", str(name or "").strip()).lower()
    if key in SHAPES:
        return key
    for k, (_, label, _, material) in SHAPES.items():
        if key in (material.lower(), label.lower().replace(" ", "-")):
            return k
    raise ValueError(f"unknown shape '{name}' (see `iipack.py shapes`)")


def _fmt(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s == "-0" else s


def plate_path(shape: str, plate_scale: float = 1.0) -> str:
    """The plate outline for `shape`, centred on the canvas, as absolute SVG path data."""
    unit = SHAPES[normalize_shape(shape)][0]
    size = PLATE_BOX * plate_scale
    origin = CENTER - size / 2.0
    out, cmd, args = [], None, []
    tokens = _TOKEN_RE.findall(unit)
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        if tok.isalpha():
            cmd = tok.upper()
            i += 1
            if cmd == "Z":
                out.append("Z")
            continue
        n = _ARGS[cmd]
        args = [float(t) for t in tokens[i:i + n]]
        i += n
        if cmd == "A":
            rx, ry, rot, large, sweep, x, y = args
            out.append(f"A{_fmt(rx * size)} {_fmt(ry * size)} {_fmt(rot)} {int(large)} {int(sweep)} "
                       f"{_fmt(origin + x * size)} {_fmt(origin + y * size)}")
        else:
            pts = [_fmt(origin + v * size) for v in args]
            out.append(cmd + " ".join(pts))
    return "".join(out)


def preset(shape: str) -> dict:
    key = normalize_shape(shape)
    _, label, glyph, material = SHAPES[key]
    return {"key": key, "name": label, "glyphFactor": glyph, "materialShape": material}


_PLATE_RE = re.compile(
    r'<circle\s+cx="96"\s+cy="96"\s+r="88"(?P<a>[^>]*?)\s*/>'
    r'|<path\s+class="ii-plate"\s+d="[^"]*"(?P<b>[^>]*?)\s*/>'
)
_CLIP_GROUP_RE = re.compile(r'^\s*<g\s+clip-path="url\(#c\)"\s*>(?P<inner>.*)</g>\s*$', re.S)
_GLYPH_GROUP_RE = re.compile(r'^\s*<g\s+class="ii-glyph"\s+transform="[^"]*"\s*>(?P<inner>.*)</g>\s*$', re.S)


def is_plate_icon(svg_text: str) -> bool:
    return _PLATE_RE.search(svg_text) is not None


def reshape_svg(svg_text: str, shape: str = DEFAULT_SHAPE, plate_scale: float = 1.0, glyph_scale: float = 1.0,
                plate_color: str | None = None, glyph_color: str | None = None, plate_d: str | None = None) -> str:
    """
    Redraw an ii-icon-pack plate icon with another plate outline.

    `plate_scale` resizes the whole icon inside its canvas (1.0 = the original r=88 plate),
    `glyph_scale` resizes the logo on top of the plate, on top of the shape's own glyph factor.
    Icons that do not carry an ii-icon-pack plate are returned unchanged.
    """
    d = plate_d or plate_path(shape, plate_scale)
    drawn = None

    def swap_plate(m):
        nonlocal drawn
        attrs = m.group("a") if m.group("a") is not None else (m.group("b") or "")
        if drawn is None and "fill=" in attrs:
            drawn = True
        return f'<path class="ii-plate" d="{d}"{attrs}/>'

    # Two passes: replace every plate copy (the drawn one and the clipPath one), then find the
    # end of the drawn plate in the rewritten text - everything after it is the glyph.
    text, count = _PLATE_RE.subn(swap_plate, svg_text)
    if not count:
        return svg_text
    plate_end = None
    for m in re.finditer(r'<path class="ii-plate" d="[^"]*"([^>]*?)/>', text):
        if "fill=" in m.group(1):
            plate_end = m.end()
            break
    close = text.rfind("</svg>")
    if plate_end is not None and close > plate_end:
        glyph = text[plate_end:close]
        clip = _CLIP_GROUP_RE.match(glyph)
        if clip:
            # Full-bleed artwork (the *Craft woodcuts) is clipped to the plate: it follows the
            # plate size but never the glyph factor, or it would stop covering the plate.
            glyph = clip.group("inner")
            scale = plate_scale
        else:
            scale = SHAPES[normalize_shape(shape)][2] * glyph_scale * plate_scale
        inner = glyph
        while True:
            m = _GLYPH_GROUP_RE.match(inner)
            if not m:
                break
            inner = m.group("inner")
        inner = inner.strip()
        if abs(scale - 1.0) > 1e-4:
            off = _fmt(CENTER * (1.0 - scale))
            body = f'  <g class="ii-glyph" transform="matrix({scale:.4f} 0 0 {scale:.4f} {off} {off})">\n{inner}\n  </g>'
        else:
            body = inner
        if clip:
            body = f'  <g clip-path="url(#c)">\n{body}\n  </g>'
        text = text[:plate_end] + "\n" + body + "\n" + text[close:]

    colors = {PLATE_HEX: plate_color or PLATE_HEX, GLYPH_HEX: glyph_color or GLYPH_HEX}
    if any(src != dst.lower() for src, dst in colors.items()):
        # One pass, so a plate painted in the glyph's base colour is not repainted again.
        text = re.sub(f"{PLATE_HEX}|{GLYPH_HEX}", lambda m: colors[m.group(0).lower()], text, flags=re.I)
    return text

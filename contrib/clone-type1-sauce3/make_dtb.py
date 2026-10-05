#!/usr/bin/env python3
"""Regenerate the "clone type1 sauce3 spk" device tree.

The board is a Clone Type 1 (R36S_V20_2025_05_18 family) fitted with the panel
ArkOS4Clone otherwise only ships for Soy Sauce boards, and it gates the speaker
with GPIO3_A7. Starting from the upstream `clone type1 panel3` DTB this script:

  * replaces the panel init sequence, power-sequencing delays and display
    timings with the values from the unit's stock DTB;
  * adds `spk-ctl-gpios` / `spk-mute-delay-ms` to the rk817 codec node so the
    kernel raises GPIO3_A7 while the speaker path is active.

Run it again after an upstream change to the base DTB:

  ./make_dtb.py                 # rewrite the console DTB from the current base
  ./make_dtb.py --check         # only compare the result with the committed DTB
"""
import argparse
import os
import struct
import sys

FDT_MAGIC = 0xD00DFEED
BEGIN_NODE, END_NODE, PROP, NOP, END = 1, 2, 3, 4, 9

HERE = os.path.dirname(os.path.abspath(__file__))
CONSOLES = os.path.join(HERE, "..", "..", "boot", "dArkOS", "consoles")
DTB_NAME = "rk3326-r36s-type1-panel3-linux.dtb"
DEFAULT_BASE = os.path.join(CONSOLES, "clone type1 panel3", DTB_NAME)
DEFAULT_STOCK = os.path.join(HERE, "stock", "rf3536k3ka.dtb")
DEFAULT_OUT = os.path.join(CONSOLES, "clone type1 sauce3 spk", DTB_NAME)

PANEL = "/dsi@ff450000/panel@0"
CODEC = "/i2c@ff180000/pmic@20/codec"
SPK_GPIO_CTRL = "/pinctrl/gpio3@ff270000"
SPK_GPIO_PIN = 7  # GPIO3_A7, active high
DELAYS = ("prepare-delay-ms", "reset-delay-ms", "init-delay-ms",
          "enable-delay-ms", "disable-delay-ms", "unprepare-delay-ms")
TIMING = ("clock-frequency", "hactive", "vactive", "hfront-porch", "hsync-len",
          "hback-porch", "vfront-porch", "vsync-len", "vback-porch",
          "hsync-active", "vsync-active", "de-active", "pixelclk-active")
# Wiring the base and the stock tree must already agree on.
PANEL_MUST_MATCH = ("panel-exit-sequence", "dsi,flags", "dsi,format",
                    "dsi,lanes", "width-mm", "height-mm")


def header(blob):
    names = ("magic", "totalsize", "off_dt_struct", "off_dt_strings",
             "off_mem_rsvmap", "version", "last_comp_version",
             "boot_cpuid_phys", "size_dt_strings", "size_dt_struct")
    h = dict(zip(names, struct.unpack(">10I", blob[:40])))
    if h["magic"] != FDT_MAGIC:
        sys.exit("not a DTB")
    return h


def tokens(blob):
    """Yield (kind, path, name, nameoff, value) for each struct-block token."""
    h = header(blob)
    strings = h["off_dt_strings"]
    p = h["off_dt_struct"]
    path = []
    while True:
        tok, = struct.unpack(">I", blob[p:p + 4])
        p += 4
        if tok == BEGIN_NODE:
            end = blob.index(b"\0", p)
            name = blob[p:end].decode()
            p = (end + 4) & ~3
            path.append(name)
            yield BEGIN_NODE, "/".join(path) or "/", name, None, None
        elif tok == END_NODE:
            yield END_NODE, "/".join(path) or "/", None, None, None
            path.pop()
        elif tok == PROP:
            length, nameoff = struct.unpack(">2I", blob[p:p + 8])
            p += 8
            s = strings + nameoff
            name = blob[s:blob.index(b"\0", s)].decode()
            yield PROP, "/".join(path) or "/", name, nameoff, blob[p:p + length]
            p = (p + length + 3) & ~3
        elif tok == NOP:
            yield NOP, None, None, None, None
        elif tok == END:
            yield END, None, None, None, None
            return
        else:
            sys.exit(f"bad token {tok:#x} at {p - 4:#x}")


def props(blob):
    return {(path, name): val for kind, path, name, _, val in tokens(blob)
            if kind == PROP}


def rebuild(blob, replace, add):
    """Re-serialise `blob`, swapping values per `replace` ({(path, name): value})
    and appending the properties in `add` ({path: [(name, value), ...]})."""
    h = header(blob)
    strings = bytearray(blob[h["off_dt_strings"]:h["off_dt_strings"] + h["size_dt_strings"]])

    def name_offset(name):
        raw = name.encode() + b"\0"
        at = 0 if strings.startswith(raw) else strings.find(b"\0" + raw) + 1
        if at == 0 and not strings.startswith(raw):
            at = len(strings)
            strings.extend(raw)
        return at

    def prop(nameoff, val):
        return struct.pack(">3I", PROP, len(val), nameoff) + val + b"\0" * (-len(val) % 4)

    out = bytearray()
    replaced, added = set(), set()
    depth_path = []
    for kind, path, name, nameoff, val in tokens(blob):
        # Properties must precede subnodes: flush additions for the enclosing
        # node before its first child opens or before it closes.
        closing = path if kind == END_NODE else None
        opening_parent = depth_path[-1] if kind == BEGIN_NODE and depth_path else None
        for node in (closing, opening_parent):
            if node in add and node not in added:
                for new_name, new_val in add[node]:
                    out += prop(name_offset(new_name), new_val)
                added.add(node)
        if kind == BEGIN_NODE:
            depth_path.append(path)
            raw = name.encode() + b"\0"
            out += struct.pack(">I", BEGIN_NODE) + raw + b"\0" * (-len(raw) % 4)
        elif kind == PROP:
            key = (path, name)
            if key in replace:
                val = replace[key]
                replaced.add(key)
            out += prop(nameoff, val)
        else:
            if kind == END_NODE:
                depth_path.pop()
            out += struct.pack(">I", kind)
    if set(replace) - replaced or set(add) - added:
        sys.exit(f"base DTB lacks: {sorted(set(replace) - replaced)} {sorted(set(add) - added)}")

    rsv_off = h["off_mem_rsvmap"]
    rsv_end = rsv_off
    while blob[rsv_end:rsv_end + 16] != b"\0" * 16:
        rsv_end += 16
    rsvmap = blob[rsv_off:rsv_end + 16]

    off_struct = 40 + len(rsvmap)
    off_strings = off_struct + len(out)
    head = struct.pack(">10I", FDT_MAGIC, off_strings + len(strings), off_struct,
                       off_strings, 40, h["version"], h["last_comp_version"],
                       h["boot_cpuid_phys"], len(strings), len(out))
    return head + rsvmap + bytes(out) + bytes(strings)


def build(base, stock):
    bp, sp = props(base), props(stock)

    stock_modes = [p for (p, n) in sp
                   if p.startswith(PANEL + "/display-timings/") and n == "hactive"]
    if len(stock_modes) != 1:
        sys.exit(f"expected one stock timing node, found {stock_modes}")
    for name in PANEL_MUST_MATCH:
        if bp[(PANEL, name)] != sp[(PANEL, name)]:
            sys.exit(f"base and stock disagree on panel {name}; pick another base")

    replace = {(PANEL, "panel-init-sequence"): sp[(PANEL, "panel-init-sequence")]}
    for name in DELAYS:
        replace[(PANEL, name)] = sp[(PANEL, name)]
    base_modes = sorted({p for (p, n) in bp
                         if p.startswith(PANEL + "/display-timings/") and n == "hactive"})
    for mode in base_modes:
        for name in TIMING:
            replace[(mode, name)] = sp[(stock_modes[0], name)]

    for name in ("spk-ctl-gpios", "spk-mute-delay-ms", "use-ext-amplifier"):
        if (CODEC, name) in bp:
            sys.exit(f"base codec node already has {name}; pick a non-amp base")
    gpio3, = struct.unpack(">I", bp[(SPK_GPIO_CTRL, "phandle")])
    add = {CODEC: [("spk-ctl-gpios", struct.pack(">3I", gpio3, SPK_GPIO_PIN, 0)),
                   ("spk-mute-delay-ms", struct.pack(">I", 50))]}

    new = rebuild(base, replace, add)

    # Re-parse: nothing but the requested properties may differ from the base.
    np_ = props(new)
    expected_new = {(CODEC, n) for n, _ in add[CODEC]}
    if set(np_) - set(bp) != expected_new or set(bp) - set(np_):
        sys.exit("property set changed unexpectedly")
    unexpected = [k for k in bp if bp[k] != np_[k] and k not in replace]
    if unexpected:
        sys.exit(f"unexpected changes: {unexpected}")
    return new


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--base", default=DEFAULT_BASE)
    ap.add_argument("--stock", default=DEFAULT_STOCK)
    ap.add_argument("--out", default=DEFAULT_OUT)
    ap.add_argument("--check", action="store_true",
                    help="compare with the existing --out file instead of writing it")
    args = ap.parse_args()

    new = build(open(args.base, "rb").read(), open(args.stock, "rb").read())
    out = os.path.normpath(args.out)
    if args.check:
        have = props(open(out, "rb").read())
        want = props(new)
        diff = sorted(k for k in set(have) | set(want) if have.get(k) != want.get(k))
        if diff:
            for path, name in diff:
                print(f"  differs: {path}:{name}")
            sys.exit(f"{out} is out of date with the base; re-run without --check")
        print(f"{out} matches the base ({len(want)} properties)")
    else:
        with open(out, "wb") as f:
            f.write(new)
        print(f"wrote {out} ({len(new)} bytes)")


if __name__ == "__main__":
    main()

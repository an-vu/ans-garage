"""Evaluate one shader's pixel program at source defaults (+ optional overrides).

usage: analyze_ps.py <parsed.json> <programs.json> <asm dir> <shader asset> <PS guid> [Name=x,y,z,w ...]
"""
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import dxil_eval as dx

ASM = None


def constants_for(parsed, programs, shader, ps):
    s = next(s for s in programs[shader]["Solutions"] if s["PS"] == ps)
    return parsed["Constants"][s["PSConstants"]], s


def external_cbuffer(text, consts, overrides=None, unknown=()):
    """One 16-byte register per external value, register = Index - 1 - ValueStart (validated against cbuffer size)."""
    sizes = [int(x) for x in re.findall(r"^;\s+\[(\d+) x i8\]", text.split("define void")[0], re.M)]
    binds = re.findall(r"^;\s+cbuffer\s+NA\s+NA\s+CB\d+\s+cb(\d+)", text, re.M)
    regs = {}
    overrides = {k.casefold(): v for k, v in (overrides or {}).items()}
    for v in consts["ExternalValues"]:
        if v["ArraySize"] != 1:
            raise ValueError("Array external not handled: " + v["Name"])
        value = overrides.get(v["Name"].casefold(), v["Value"])
        if v["Type"] == 1:
            value = [dx.as_int_bits(x) if isinstance(x, float) else int(x) for x in value]
        row = [value[i] if i < v["Width"] else 0.0 for i in range(4)]
        if v["Name"].casefold() in {u.casefold() for u in unknown}:
            row = [None] * 4
        regs[v["Index"] - 1 - consts.get("ValueStart", 0)] = row
    need = 16 * (max(regs) + 1) if regs else 0
    candidates = [b for b, s in zip(binds, sizes) if s == need]
    # Convention measured over the v293 database: in all 909 programs whose external cbuffer is identified uniquely by
    # size it is bound at cb1. It breaks size ties; without cb1 (or without parameters) the program reads none.
    if len(candidates) > 1 and "1" in candidates:
        candidates = ["1"]
    if not candidates and (need == 0 or "1" not in binds):
        return None, regs
    if len(candidates) != 1:
        raise ValueError("Cannot identify external cbuffer: sizes %s binds %s need %d" % (sizes, binds, need))
    return int(candidates[0]), regs


def texture_names(consts):
    names = {t["Index"]: "default#%d" % t["Hash"] for t in consts["Textures"]}
    for t in consts["ExternalTextures"]:
        names[t["Index"]] = t["Name"] + (("(default#%d)" % next(x["Hash"] for x in consts["Textures"] if x["Index"] == t["Index"]))
                                         if any(x["Index"] == t["Index"] for x in consts["Textures"]) else "")
    return names


def run(parsed, programs, asmdir, shader, ps, overrides=None, unknown=(), extra_cb=None):
    text = (Path(asmdir) / (ps + ".asm")).read_text()
    consts, sol = constants_for(parsed, programs, shader, ps)
    bind, regs = external_cbuffer(text, consts, overrides, unknown)
    cbs = {bind: regs}
    if extra_cb:
        for b, r in extra_cb.items():
            cbs.setdefault(b, {}).update(r)
    prog, ev = dx.evaluate_ps(text, cbs)
    return prog, ev, consts, sol, bind

"""Numeric evaluation, randomized constant proof and rewriting for dxil_eval DAGs (research tool)."""
import math
import numpy as np

import dxil_eval as dx
from dxil_eval import E, is_num

INT_OPS = {"iadd", "isub", "imul", "iand", "ior", "ixor", "ishl", "ilshr", "iashr", "iudiv", "iurem", "isrem"}


def children(x):
    if not isinstance(x, E):
        return []
    out = []
    for a in x.args:
        if isinstance(a, tuple):
            for b in a:
                if isinstance(b, tuple):
                    out.extend(c for c in b if isinstance(c, E))
                elif isinstance(b, E):
                    out.append(b)
        elif isinstance(a, E):
            out.append(a)
    return out


def topo(roots):
    order, seen = [], set()
    stack = [(r, False) for r in roots if isinstance(r, E)]
    while stack:
        node, done = stack.pop()
        if done:
            order.append(node)
            continue
        if node in seen:
            continue
        seen.add(node)
        stack.append((node, True))
        for c in children(node):
            if c not in seen:
                stack.append((c, False))
    return order


def _f(v, n):
    if isinstance(v, (bool, np.bool_)):
        return np.full(n, bool(v))
    if is_num(v):
        return np.full(n, float(v)) if isinstance(v, float) else np.full(n, int(v), dtype=np.int64)
    return v


def evaluate(roots, leaf, n, overrides=None):
    """leaf(node) -> array for leaves. overrides: {node: array}."""
    val = dict(overrides or {})
    with np.errstate(all="ignore"):
        for x in topo(roots):
            if x in val:
                continue
            val[x] = _eval(x, val, leaf, n)
    return val


def _get(a, val, n):
    return val[a] if isinstance(a, E) else _f(a, n)


def _eval(x, val, leaf, n):
    o, A = x.op, x.args
    g = lambda i: _get(A[i], val, n)
    if o == "ch" and A[0].op == "tex":
        return leaf(x, [_get(c, val, n) for c in A[0].args[2]])
    if o in ("in", "input", "cb", "undef", "status", "memload", "loopcarried", "backedge"):
        return leaf(x, None)
    if o == "tex":
        return np.zeros(n)  # samples are represented by their channel leaves
    if o == "frame":
        if len(A) == 4:
            vec, k, sig, r0 = A
            return sum(leaf(E("in", sig, r0 + k, c), None) * _get(vec[c], val, n) for c in range(3))
        vec, k = A
        cols = [leaf(E("input", name + "." + "xyz"[k]), None) for name in ("WorldTangent", "WorldBitangent", "WorldNormal")]
        return sum(cols[c] * _get(vec[c], val, n) for c in range(3))
    if o == "rowdot":
        sig, row, vec = A
        return sum(leaf(E("in", sig, row, c), None) * _get(vec[c], val, n) for c in range(3))
    if o == "add": return g(0) + g(1)
    if o == "sub": return g(0) - g(1)
    if o == "mul": return g(0) * g(1)
    if o == "div": return g(0) / g(1)
    if o == "neg": return -g(0)
    if o == "fmod": return np.fmod(g(0), g(1))
    if o == "max": return np.maximum(g(0), g(1))
    if o == "min": return np.minimum(g(0), g(1))
    if o == "abs": return np.abs(g(0))
    if o == "saturate": return np.clip(g(0), 0, 1)
    if o == "sqrt": return np.sqrt(g(0))
    if o == "rsqrt": return 1 / np.sqrt(g(0))
    if o == "exp2": return np.exp2(g(0))
    if o == "log2": return np.log2(g(0))
    if o == "frac": return g(0) - np.floor(g(0))
    if o == "floor": return np.floor(g(0))
    if o == "ceil": return np.ceil(g(0))
    if o == "trunc": return np.trunc(g(0))
    if o == "round_ne": return np.round(g(0))
    if o in ("sin", "cos", "tan", "acos", "asin", "atan"): return getattr(np, {"acos": "arccos", "asin": "arcsin", "atan": "arctan"}.get(o, o))(g(0))
    if o in ("ddx", "ddy", "ddx_fine", "ddy_fine"): return np.zeros(n)
    if o == "select": return np.where(g(0), g(1), g(2))
    if o == "and": return np.logical_and(g(0), g(1))
    if o == "or": return np.logical_or(g(0), g(1))
    if o == "not": return np.logical_not(g(0))
    if o == "xor": return np.logical_xor(g(0), g(1))
    if o.startswith("fcmp_"):
        p = o[5:]
        a, b = g(0), g(1)
        return {"oeq": a == b, "ueq": a == b, "one": a != b, "une": a != b, "olt": a < b, "ult": a < b,
                "ole": a <= b, "ule": a <= b, "ogt": a > b, "ugt": a > b, "oge": a >= b, "uge": a >= b,
                "ord": ~(np.isnan(a) | np.isnan(b)), "uno": np.isnan(a) | np.isnan(b)}[p]
    if o.startswith("icmp_"):
        p = o[5:]
        a, b = g(0).astype(np.int64), g(1).astype(np.int64)
        sa, sb = _s32(a), _s32(b)
        ua, ub = a & 0xffffffff, b & 0xffffffff
        return {"eq": ua == ub, "ne": ua != ub, "ugt": ua > ub, "uge": ua >= ub, "ult": ua < ub, "ule": ua <= ub,
                "sgt": sa > sb, "sge": sa >= sb, "slt": sa < sb, "sle": sa <= sb}[p]
    if o in ("fptoui_i32", "fptosi_i32"):
        a = g(0)
        a = np.where(np.isfinite(a), a, 0)
        return np.trunc(a).astype(np.int64) & 0xffffffff
    if o in ("uitofp_float",): return (g(0).astype(np.int64) & 0xffffffff).astype(float)
    if o in ("sitofp_float",): return _s32(g(0).astype(np.int64)).astype(float)
    if o == "zext_i32": return g(0).astype(np.int64)
    if o == "bits31":  # countbits
        a = g(0).astype(np.int64) & 0xffffffff
        return np.array([bin(int(x)).count("1") for x in a], dtype=np.int64)
    if o in ("bits32", "bits33", "bits34"):  # firstbitlo / firstbithi / firstbitshi (-1 if none)
        a = g(0).astype(np.int64) & 0xffffffff
        if o == "bits32":
            return np.array([(int(x) & -int(x)).bit_length() - 1 if x else 0xffffffff for x in a], dtype=np.int64)
        return np.array([31 - (int(x).bit_length() - 1) if x else 0xffffffff for x in a], dtype=np.int64)
    if o == "bitcast_i32": return np.asarray(g(0), dtype=np.float32).view(np.uint32).astype(np.int64)
    if o == "bitcast_float": return (np.asarray(g(0)).astype(np.int64) & 0xffffffff).astype(np.uint32).view(np.float32).astype(float)
    if o in INT_OPS:
        a, b = g(0).astype(np.int64) & 0xffffffff, g(1).astype(np.int64) & 0xffffffff
        r = {"iadd": lambda: a + b, "isub": lambda: a - b, "imul": lambda: a * b, "iand": lambda: a & b,
             "ior": lambda: a | b, "ixor": lambda: a ^ b, "ishl": lambda: a << (b & 31), "ilshr": lambda: a >> (b & 31),
             "iashr": lambda: _s32(a) >> (b & 31), "isrem": lambda: np.fmod(_s32(a), np.where(b == 0, 1, _s32(b))),
             "iudiv": lambda: a // np.where(b == 0, 1, b), "iurem": lambda: a % np.where(b == 0, 1, b)}[o]()
        return r & 0xffffffff
    if o == "binop39": return np.maximum(g(0).astype(np.int64) & 0xffffffff, g(1).astype(np.int64) & 0xffffffff)  # UMax
    if o == "binop40": return np.minimum(g(0).astype(np.int64) & 0xffffffff, g(1).astype(np.int64) & 0xffffffff)  # UMin
    if o == "binop37": return np.maximum(_s32(g(0)), _s32(g(1))) & 0xffffffff
    if o == "binop38": return np.minimum(_s32(g(0)), _s32(g(1))) & 0xffffffff
    if o == "lookup":
        arr = np.array(LOOKUPS[A[0]])
        idx = np.clip(g(1).astype(np.int64), 0, len(arr) - 1)
        return arr[idx]
    raise ValueError("cannot evaluate " + o)


LOOKUPS = {}


def _s32(a):
    a = np.asarray(a).astype(np.int64) & 0xffffffff
    return np.where(a & 0x80000000, a - (1 << 32), a)


# ------------------------------------------------------------------ rewriting
CTOR = {"add": dx.add, "sub": dx.sub, "mul": dx.mul, "div": dx.div, "neg": dx.neg, "max": dx.fmax, "min": dx.fmin,
        "select": dx.select, "and": dx.band, "or": dx.bor, "not": dx.bnot}


def rebuild(x, subst, memo):
    if not isinstance(x, E):
        return x
    if x in memo:
        return memo[x]
    if x in subst:
        r = subst[x]
        memo[x] = r
        return r
    o = x.op
    args = []
    for a in x.args:
        if isinstance(a, tuple):
            args.append(tuple(tuple(rebuild(c, subst, memo) for c in b) if isinstance(b, tuple)
                              else rebuild(b, subst, memo) for b in a))
        else:
            args.append(rebuild(a, subst, memo))
    if o in CTOR:
        r = CTOR[o](*args)
    elif o in dx.UNARY.values():
        code = {v: k for k, v in dx.UNARY.items()}[o]
        r = dx.unary(code, args[0])
    elif o.startswith("fcmp_") or o.startswith("icmp_"):
        r = dx.cmp(o[:4], o[5:], args[0], args[1])
    elif o in INT_OPS:
        r = dx.intop(o[1:], args[0], args[1], "i32")
    elif o in ("fptoui_i32", "fptosi_i32", "uitofp_float", "sitofp_float", "zext_i32") and all(is_num(a) or isinstance(a, bool) for a in args):
        v = int(args[0]) if isinstance(args[0], bool) else args[0]
        r = {"fptoui_i32": lambda: int(math.trunc(v)) & 0xffffffff, "fptosi_i32": lambda: int(math.trunc(v)) & 0xffffffff,
             "uitofp_float": lambda: float(int(v) & 0xffffffff), "sitofp_float": lambda: float(dx.s32(int(v))),
             "zext_i32": lambda: int(v)}[o]()
    elif o == "ch" and isinstance(args[0], E) is False:
        r = args[0]
    else:
        r = E(o, *args)
    memo[x] = r
    return r


def random_leaf_factory(n, rng, fixed=None, continuous=False):
    """Random leaves with branch-covering mixtures. fixed: {predicate(node)->value or array}."""
    cache = {}

    def leaf(x, coords=None):
        if x.op == "ch":
            # Texture = deterministic function of (slot, channel, coordinates): rewritten samples stay comparable.
            s = x.args[0]
            h = np.full(n, 12.9898 * (s.args[1] + 1) + 78.233 * (x.args[1] + 1) + (hash(s.args[0]) % 97))
            for i, c in enumerate(coords):
                c = np.asarray(c, dtype=float)
                h = h + np.where(np.isfinite(c), c, 0.0) * (37.719 + 11.13 * i)
            r = np.sin(h) * 43758.5453
            r = r - np.floor(r)
            # Mixture keeps rare thresholds (e.g. > 0.99) and exact 0/1 covered.
            if not continuous:
                r = np.where(r < 0.05, 0.0, np.where(r > 0.95, 1.0, (r - 0.05) / 0.9))
            if fixed:
                for pred, value in fixed:
                    if pred(x):
                        return _f(value(x) if callable(value) else value, n)
            return r
        if x in cache:
            return cache[x]
        if fixed:
            for pred, value in fixed:
                if pred(x):
                    v = value(x) if callable(value) else value
                    cache[x] = _f(v, n) if not isinstance(v, np.ndarray) else v
                    return cache[x]
        if x.op == "cb" and x.args[3] == "i32":
            v = rng.integers(0, 3, n)
        else:
            kind = rng.random(n)
            v = np.where(kind < 0.6, rng.random(n), np.where(kind < 0.85, rng.uniform(-1, 1, n),
                         np.where(kind < 0.93, rng.uniform(-30, 30, n), rng.integers(0, 2, n).astype(float))))
        cache[x] = v
        return v
    return leaf


def prove_constants(roots, n=6000, seed=1, fixed=None, keep=lambda node: False, rounds=3):
    """Replace every node whose value is identical over all random samples (several seeds) by that constant."""
    candidates = None
    for r in range(rounds):
        rng = np.random.default_rng(seed + r)
        leaf = random_leaf_factory(n, rng, fixed)
        val = evaluate(roots, leaf, n)
        found = {}
        for x, v in val.items():
            if not isinstance(x, E) or keep(x) or x.op in ("in", "input", "cb", "undef", "tex", "status"):
                continue
            v = np.asarray(v)
            if v.dtype == bool:
                if v.all() or not v.any():
                    found[x] = bool(v[0])
            elif np.issubdtype(v.dtype, np.integer):
                if (v == v[0]).all():
                    found[x] = int(v[0])
            else:
                if np.isfinite(v[0]) and np.all(v == v[0]):
                    found[x] = float(v[0])
        candidates = found if candidates is None else {k: v for k, v in candidates.items() if k in found and found[k] == v}
    return candidates


def simplify(roots, fixed_subst=None, fixed_leaves=None, keep=lambda node: False, n=6000):
    """Exact substitutions first, then randomized constant proof, iterated to a fixed point."""
    labels = [l for l, _ in roots]
    values = [v for _, v in roots]
    if fixed_subst:
        memo = {}
        values = [rebuild(v, fixed_subst, memo) for v in values]
    for _ in range(4):
        consts = prove_constants(values, n=n, fixed=fixed_leaves, keep=keep)
        if not consts:
            break
        memo = {}
        new = [rebuild(v, consts, memo) for v in values]
        if all(a is b for a, b in zip(new, values)):
            break
        values = new
    return list(zip(labels, values))


def compare(roots_a, roots_b, n=20000, seed=99, fixed=None, continuous=True):
    """Max abs difference per output between two DAG versions over shared random leaves.

    Continuous texture values by default: exact channel ties sit on discontinuities of the game's own
    RGB->HSV branches, where float rounding (not simplification) decides the branch."""
    rng = np.random.default_rng(seed)
    leaf = random_leaf_factory(n, rng, fixed, continuous)
    va = evaluate([v for _, v in roots_a], leaf, n)
    vb = evaluate([v for _, v in roots_b], leaf, n)
    out = {}
    for (la, a), (lb, b) in zip(roots_a, roots_b):
        x = np.asarray(_get(a, va, n), dtype=float)
        y = np.asarray(_get(b, vb, n), dtype=float)
        ok = np.isfinite(x) & np.isfinite(y)
        out[la] = (float(np.max(np.abs(x[ok] - y[ok]))) if ok.any() else 0.0, int((~ok).sum()))
    return out


def count(roots):
    return len(topo([v for _, v in roots]))


def transform(values, fn):
    """Bottom-up rewrite. fn(node, new_node_with_mapped_children) -> replacement or None."""
    mapped = {}
    def m(v):
        return mapped.get(v, v) if isinstance(v, E) else v
    for x in topo([v for v in values if isinstance(v, E)]):
        kids = children(x)
        if any(mapped.get(c, c) is not c for c in kids):
            y = rebuild(x, {c: mapped[c] for c in kids if c in mapped and mapped[c] is not c}, {})
        else:
            y = x
        r = fn(x, y) if isinstance(y, E) else None
        mapped[x] = y if r is None else r
    return [m(v) for v in values]

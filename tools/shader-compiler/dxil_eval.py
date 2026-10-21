"""Symbolic partial evaluator for DXC-disassembled DXIL pixel programs (research tool).

Substitutes known constant-buffer values, folds constants, resolves branches whose
conditions become constant, and expresses every SV_Target component as a DAG over
texture samples, interpolants and unknown constants. Loops are rejected.
Read-only: it never writes game data. Not a general LLVM interpreter.
"""
import math
import re
import struct

XYZW = "xyzw"
ROWDOT = False  # emit structured dot3(vector, interpolant row) nodes
OPAQUE_LOOPS = False  # loop-carried values become opaque symbols instead of an error


class E:
    """Hash-consed symbolic node."""
    __slots__ = ("op", "args", "id")
    _table = {}
    _count = 0

    def __new__(cls, op, *args):
        key = (op, args)
        node = cls._table.get(key)
        if node is None:
            node = object.__new__(cls)
            node.op, node.args = op, args
            E._count += 1
            node.id = E._count
            cls._table[key] = node
        return node

    def __repr__(self):
        return "E%d" % self.id


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def f32(x):
    try:
        return struct.unpack("<f", struct.pack("<f", x))[0]
    except OverflowError:
        return math.copysign(math.inf, x)


def as_float_bits(i):
    return struct.unpack("<f", struct.pack("<I", i & 0xffffffff))[0]


def as_int_bits(f):
    return struct.unpack("<I", struct.pack("<f", f))[0]


def literal(tok, ty):
    tok = tok.strip()
    if tok in ("undef", "poison"):
        return E("undef")
    if ty == "i1":
        return {"true": True, "false": False}[tok]
    if tok.startswith("0x"):
        if ty in ("float", "half", "double"):
            return f32(struct.unpack(">d", bytes.fromhex(tok[2:].rjust(16, "0")))[0])
        return int(tok, 16)
    if ty in ("float", "half", "double"):
        return f32(float(tok))
    return int(tok)


# ---------------------------------------------------------------- simplifier
def add(a, b):
    if is_num(a) and is_num(b): return f32(a + b)
    if a == 0: return b
    if b == 0: return a
    if is_num(a): a, b = b, a
    return E("add", *sorted((a, b), key=_order))


def mul(a, b):
    if is_num(a) and is_num(b): return f32(a * b)
    if a == 0 or b == 0: return 0.0
    if a == 1: return b
    if b == 1: return a
    if a == -1: return neg(b)
    if b == -1: return neg(a)
    return E("mul", *sorted((a, b), key=_order))


def neg(a):
    if is_num(a): return -a
    if isinstance(a, E) and a.op == "neg": return a.args[0]
    return E("neg", a)


def sub(a, b):
    if is_num(a) and is_num(b): return f32(a - b)
    if b == 0: return a
    if a is b: return 0.0
    if a == 0: return neg(b)
    return E("sub", a, b)


def div(a, b):
    if is_num(a) and is_num(b):
        if b == 0: return math.copysign(math.inf, a) if a else math.nan
        return f32(a / b)
    if a == 0: return 0.0
    if b == 1: return a
    if is_num(b): return mul(a, f32(1.0 / b))
    return E("div", a, b)


def _order(x):
    return (0, x) if is_num(x) else (1, x.id) if isinstance(x, E) else (2, str(x))


UNARY = {6: "abs", 7: "saturate", 12: "cos", 13: "sin", 14: "tan", 15: "acos", 16: "asin", 17: "atan",
         21: "exp2", 22: "frac", 23: "log2", 24: "sqrt", 25: "rsqrt", 26: "round_ne", 27: "floor",
         28: "ceil", 29: "trunc", 83: "ddx", 84: "ddy", 85: "ddx_fine", 86: "ddy_fine"}


def unary(op, a):
    name = UNARY[op]
    if is_num(a):
        try:
            return f32({"abs": abs, "saturate": lambda x: min(max(x, 0.0), 1.0),
                        "cos": math.cos, "sin": math.sin, "tan": math.tan, "acos": math.acos,
                        "asin": math.asin, "atan": math.atan, "exp2": lambda x: 2.0 ** x,
                        "frac": lambda x: x - math.floor(x), "log2": lambda x: math.log2(x) if x > 0 else -math.inf,
                        "sqrt": lambda x: math.sqrt(x) if x >= 0 else math.nan,
                        "rsqrt": lambda x: 1 / math.sqrt(x) if x > 0 else math.inf,
                        "round_ne": lambda x: float(round(x)), "floor": math.floor, "ceil": math.ceil,
                        "trunc": math.trunc, "ddx": lambda x: 0.0, "ddy": lambda x: 0.0,
                        "ddx_fine": lambda x: 0.0, "ddy_fine": lambda x: 0.0}[name](a))
        except (ValueError, OverflowError):
            return math.nan
    if name == "saturate" and isinstance(a, E) and a.op == "saturate":
        return a
    return E(name, a)


def fmax(a, b):
    if is_num(a) and is_num(b): return max(a, b)
    if a is b: return a
    return E("max", *sorted((a, b), key=_order))


def fmin(a, b):
    if is_num(a) and is_num(b): return min(a, b)
    if a is b: return a
    return E("min", *sorted((a, b), key=_order))


def select(c, a, b):
    if c is True: return a
    if c is False: return b
    if a is b or (is_num(a) and is_num(b) and a == b): return a
    if a is True and b is False: return c
    if a is False and b is True: return bnot(c)
    return E("select", c, a, b)


def band(a, b):
    if a is False or b is False: return False
    if a is True: return b
    if b is True: return a
    if a is b: return a
    return E("and", *sorted((a, b), key=_order))


def bor(a, b):
    if a is True or b is True: return True
    if a is False: return b
    if b is False: return a
    if a is b: return a
    return E("or", *sorted((a, b), key=_order))


def bnot(a):
    if isinstance(a, bool): return not a
    if isinstance(a, E) and a.op == "not": return a.args[0]
    return E("not", a)


FCMP = {"oeq": lambda a, b: a == b, "ueq": lambda a, b: a == b, "one": lambda a, b: a != b,
        "une": lambda a, b: a != b, "olt": lambda a, b: a < b, "ult": lambda a, b: a < b,
        "ole": lambda a, b: a <= b, "ule": lambda a, b: a <= b, "ogt": lambda a, b: a > b,
        "ugt": lambda a, b: a > b, "oge": lambda a, b: a >= b, "uge": lambda a, b: a >= b,
        "ord": lambda a, b: True, "uno": lambda a, b: False}


def s32(x):
    x &= 0xffffffff
    return x - (1 << 32) if x & 0x80000000 else x


ICMP = {"eq": lambda a, b: a == b, "ne": lambda a, b: a != b,
        "ugt": lambda a, b: (a & 0xffffffff) > (b & 0xffffffff), "uge": lambda a, b: (a & 0xffffffff) >= (b & 0xffffffff),
        "ult": lambda a, b: (a & 0xffffffff) < (b & 0xffffffff), "ule": lambda a, b: (a & 0xffffffff) <= (b & 0xffffffff),
        "sgt": lambda a, b: s32(a) > s32(b), "sge": lambda a, b: s32(a) >= s32(b),
        "slt": lambda a, b: s32(a) < s32(b), "sle": lambda a, b: s32(a) <= s32(b)}


def cmp(kind, pred, a, b):
    if (is_num(a) or isinstance(a, bool)) and (is_num(b) or isinstance(b, bool)):
        if kind == "fcmp" and (isinstance(a, float) and math.isnan(a) or isinstance(b, float) and math.isnan(b)):
            return pred.startswith("u") or pred == "one" and False
        return (FCMP if kind == "fcmp" else ICMP)[pred](a, b)
    if a is b and pred in ("oeq", "ueq", "eq", "ole", "oge", "ule", "uge", "sle", "sge"):
        return True
    return E(kind + "_" + pred, a, b)


INT_OPS = {"add": lambda a, b: a + b, "sub": lambda a, b: a - b, "mul": lambda a, b: a * b,
           "and": lambda a, b: a & b, "or": lambda a, b: a | b, "xor": lambda a, b: a ^ b,
           "shl": lambda a, b: a << (b & 31), "lshr": lambda a, b: (a & 0xffffffff) >> (b & 31),
           "ashr": lambda a, b: s32(a) >> (b & 31), "udiv": lambda a, b: (a & 0xffffffff) // (b & 0xffffffff),
           "urem": lambda a, b: (a & 0xffffffff) % (b & 0xffffffff), "srem": lambda a, b: int(math.fmod(s32(a), s32(b)))}


def intop(op, a, b, ty):
    if ty == "i1":
        if op == "and": return band(a, b)
        if op == "or": return bor(a, b)
        if op == "xor":
            if b is True: return bnot(a)
            if a is True: return bnot(b)
            if isinstance(a, bool) and isinstance(b, bool): return a != b
            return E("xor", a, b)
    if is_num(a) and is_num(b):
        return INT_OPS[op](int(a), int(b)) & 0xffffffff
    if op == "and" and (a == 0 or b == 0): return 0
    if op in ("or", "add", "xor") and b == 0: return a
    if op in ("or", "add", "xor") and a == 0: return b
    if op in ("shl", "lshr", "ashr") and b == 0: return a
    if op == "mul" and (a == 0 or b == 0): return 0
    return E("i" + op, a, b)


# ---------------------------------------------------------------- parser/executor
OPERAND = r"(?:%\d+|[-+]?[0-9.]+(?:e[-+]?\d+)?|0x[0-9A-Fa-f]+|true|false|undef|null|zeroinitializer)"


class Program:
    def __init__(self, text):
        self.text = text
        head, _, rest = text.partition("define void @main() {")
        self.head = head
        body = rest.split("\n}\n", 1)[0]
        self.globals = {}
        for m in re.finditer(r'^(@"[^"]+"|@\S+) = [^\[]*constant \[(\d+) x (\w+)\] \[([^\]]*)\]', text, re.M):
            ty = m.group(3)
            self.globals[m.group(1)] = [literal(x.strip().split(" ", 1)[1], ty) for x in m.group(4).split(",")]
        self.blocks, order, current = {}, [], "0"
        self.blocks[current] = []
        order.append(current)
        for line in body.splitlines():
            s = line.strip()
            m = re.match(r"; <label>:(\d+)", s) or re.match(r"(\d+):", s)
            if m:
                current = m.group(1)
                self.blocks[current] = []
                order.append(current)
                continue
            if not s or s.startswith(";"):
                continue
            s = re.sub(r"\s+;.*$", "", s)
            self.blocks[current].append(s.split(", !dx.controlflow")[0].split(", !")[0] if s.startswith(("br ", "switch")) else s)
        self.order = order
        # switch cases are on separate lines; reattach
        for b in order:
            lines, merged, buf = self.blocks[b], [], None
            for s in lines:
                if s.startswith("switch "):
                    buf = s
                    if s.endswith("]"):
                        merged.append(buf); buf = None
                elif buf is not None:
                    buf += " " + s
                    if s.startswith("]"):
                        merged.append(buf); buf = None
                else:
                    merged.append(s)
            self.blocks[b] = merged
        self.texture_dims = {}
        for m in re.finditer(r"^;\s+texture\s+\S+\s+(\w+)\s+T\d+\s+t(\d+)", head, re.M):
            self.texture_dims[int(m.group(2))] = m.group(1)


class Evaluator:
    def __init__(self, program, cbuffers, inputs_named=True):
        """cbuffers: {bind_index: {register: [x,y,z,w] with None for unknown}}"""
        self.p, self.cb = program, cbuffers
        self.v = {}
        self.outputs = {}
        self.outputs_rows = {}
        self.discards = []
        self.handles = {}
        self.memory = {}

    def val(self, tok, ty="float"):
        tok = tok.strip()
        if tok.startswith("%"):
            if tok not in self.v:
                raise KeyError("Undefined value " + tok)
            return self.v[tok]
        return literal(tok, ty)

    def args(self, s):
        """Split call args 'i32 5, float %3, ...' into (type, token) pairs."""
        out, depth, cur = [], 0, ""
        for ch in s:
            if ch == "," and depth == 0:
                out.append(cur); cur = ""
                continue
            depth += ch in "([{"
            depth -= ch in ")]}"
            cur += ch
        if cur.strip():
            out.append(cur)
        result = []
        for a in out:
            a = a.strip()
            ty, _, tok = a.rpartition(" ")
            result.append((ty, tok))
        return result

    def cbload(self, handle, reg, kind):
        _, cls, bind = handle
        if is_num(reg):
            row = self.cb.get(bind, {}).get(int(reg))
            if row is not None:
                return ("cbrow", [(c if c is not None else E("cb", bind, int(reg), i, kind)) for i, c in enumerate(row)])
        return ("cbrow", [E("cb", bind, reg, i, kind) for i in range(4)])

    def run(self):
        reach = {self.p.order[0]: True}
        edge = {}  # (pred, succ) -> condition
        position = {b: i for i, b in enumerate(self.p.order)}
        for block in self.p.order:
            r = reach.get(block, False)
            if r is False:
                continue
            self.block = block
            self.reach = r
            for line in self.p.blocks[block]:
                if line.startswith("br "):
                    m = re.match(r"br i1 (\S+), label %(\d+), label %(\d+)", line)
                    if m:
                        c = self.val(m.group(1), "i1")
                        targets = [(m.group(2), c), (m.group(3), bnot(c))]
                    else:
                        targets = [(re.match(r"br label %(\d+)", line).group(1), True)]
                    for t, c in targets:
                        if position[t] <= position[block]:
                            if not OPAQUE_LOOPS:
                                raise ValueError("Loop/back edge not supported: %s -> %s" % (block, t))
                            continue  # loop-carried values are opaque at the header phi

                        ec = band(r, c)
                        edge[(block, t)] = bor(edge.get((block, t), False), ec)
                        reach[t] = bor(reach.get(t, False), ec)
                    continue
                if line.startswith("switch "):
                    m = re.match(r"switch i32 (\S+), label %(\d+) \[(.*)\]", line)
                    x = self.val(m.group(1), "i32")
                    cases = re.findall(r"i32 (-?\d+), label %(\d+)", m.group(3))
                    default = True
                    for value, t in cases:
                        c = cmp("icmp", "eq", x, int(value) & 0xffffffff)
                        default = band(default, bnot(c))
                        ec = band(r, c)
                        edge[(block, t)] = bor(edge.get((block, t), False), ec)
                        reach[t] = bor(reach.get(t, False), ec)
                    t = m.group(2)
                    ec = band(r, default)
                    edge[(block, t)] = bor(edge.get((block, t), False), ec)
                    reach[t] = bor(reach.get(t, False), ec)
                    continue
                if line.startswith("ret "):
                    continue
                self.step(line, edge, r)
        return self

    def step(self, line, edge, reach):
        m = re.match(r"(%\d+) = (.*)", line)
        dest, expr = (m.group(1), m.group(2)) if m else (None, line)
        op = expr.split(" ", 1)[0]
        if op == "phi":
            ty = expr.split(" ")[1]
            incoming = re.findall(r"\[ ([^,]+), %(\d+) \]", expr)
            result = None
            items = []
            position = {b: i for i, b in enumerate(self.p.order)}
            for tok, pred in incoming:
                if OPAQUE_LOOPS and position.get(pred, -1) >= position[self.block]:
                    items.append((E("backedge", pred, self.block), E("loopcarried", dest)))
                    continue
                c = edge.get((pred, self.block), False)
                if c is False:
                    continue
                items.append((c, self.val(tok, ty)))
            if not items:
                raise ValueError("phi without reachable incoming edge: " + line)
            result = items[-1][1]
            for c, v in reversed(items[:-1]):
                result = select(c, v, result)
            self.v[dest] = result
            return
        if op == "call":
            return self.call(dest, expr)
        if op in ("fadd", "fsub", "fmul", "fdiv", "frem"):
            m = re.match(r"\w+(?: fast| nnan| ninf| nsz| arcp| contract| afn| reassoc)* (\w+) (\S+), (\S+)$", expr)
            ty, a, b = m.group(1), self.val(m.group(2), m.group(1)), self.val(m.group(3), m.group(1))
            if op == "frem":
                self.v[dest] = f32(math.fmod(a, b)) if is_num(a) and is_num(b) else E("fmod", a, b)
            else:
                self.v[dest] = {"fadd": add, "fsub": sub, "fmul": mul, "fdiv": div}[op](a, b)
            return
        if op in ("fcmp", "icmp"):
            m = re.match(r"\w+(?: fast)? (\w+) (\w+) (\S+), (\S+)$", expr)
            ty = m.group(2)
            self.v[dest] = cmp(op, m.group(1), self.val(m.group(3), ty), self.val(m.group(4), ty))
            return
        if op == "select":
            m = re.match(r"select i1 (\S+), (\w+) (\S+), \w+ (\S+)$", expr)
            ty = m.group(2)
            self.v[dest] = select(self.val(m.group(1), "i1"), self.val(m.group(3), ty), self.val(m.group(4), ty))
            return
        if op in INT_OPS or op in ("udiv", "urem", "srem", "ashr"):
            m = re.match(r"\w+(?: nuw| nsw| exact)* (\w+) (\S+), (\S+)$", expr)
            ty = m.group(1)
            self.v[dest] = intop(op, self.val(m.group(2), ty), self.val(m.group(3), ty), ty)
            return
        if op in ("fptoui", "fptosi", "uitofp", "sitofp", "bitcast", "zext", "sext", "trunc", "fpext", "fptrunc"):
            m = re.match(r"\w+ (\w+) (\S+) to (\w+)", expr)
            a = self.val(m.group(2), m.group(1))
            src, dst = m.group(1), m.group(3)
            if isinstance(a, bool):
                a = int(a)
            if is_num(a):
                if op in ("fptoui", "fptosi"):
                    r = 0 if math.isnan(a) or math.isinf(a) else int(math.trunc(a)) & 0xffffffff
                elif op == "uitofp": r = f32(float(int(a) & 0xffffffff))
                elif op == "sitofp": r = f32(float(s32(int(a))))
                elif op == "bitcast":
                    r = as_float_bits(int(a)) if dst == "float" else as_int_bits(a)
                elif op == "trunc" and dst == "i1": r = bool(int(a) & 1)
                else: r = a
                self.v[dest] = r
            else:
                self.v[dest] = E(op + "_" + dst, a)
            return
        if op == "extractvalue":
            m = re.match(r"extractvalue \S+ (%\d+), (\d+)", expr)
            agg = self.v[m.group(1)]
            k = int(m.group(2))
            if isinstance(agg, tuple) and agg[0] in ("cbrow", "res"):
                self.v[dest] = agg[1][k]
            else:
                self.v[dest] = E("extract", agg, k)
            return
        if op == "alloca":
            m = re.match(r"alloca \[(\d+) x \w+\]", expr)
            self.v[dest] = ("mem", dest)
            self.alloc_size = getattr(self, "alloc_size", {})
            self.alloc_size[dest] = int(m.group(1)) if m else None
            return
        if op == "getelementptr":
            m = re.match(r"getelementptr (?:inbounds )?\[\d+ x \w+\], \[\d+ x \w+\]\* (\S+), i32 0, i32 (\S+)", expr)
            base = m.group(1)
            idx = self.val(m.group(2), "i32")
            self.v[dest] = ("ptr", base, idx)
            return
        if op == "load":
            m = re.match(r"load (\w+), \w+\* (%\d+)", expr)
            ptr = self.v[m.group(2)]
            _, base, idx = ptr
            if base.startswith("@"):
                arr = self.p.globals[base]
                self.v[dest] = arr[int(idx)] if is_num(idx) else E("lookup", base.split("?")[1].split("@")[0], idx)
            else:
                size = getattr(self, "alloc_size", {}).get(base)
                if is_num(idx):
                    self.v[dest] = self.memory.get((base, idx), E("memload", base, idx))
                elif size and all((base, k) in self.memory for k in range(size)):
                    # Symbolic index into a fully written local array: explicit selection.
                    r = self.memory[(base, size - 1)]
                    for k in range(size - 2, -1, -1):
                        r = select(cmp("icmp", "eq", idx, k), self.memory[(base, k)], r)
                    self.v[dest] = r
                else:
                    self.v[dest] = E("memload", base, idx)
            return
        if op == "store":
            m = re.match(r"store (\w+) (\S+), \w+\* (%\d+)", expr)
            _, base, idx = self.v[m.group(3)]
            value = self.val(m.group(2), m.group(1))
            if is_num(idx):
                old = self.memory.get((base, idx))
                self.memory[(base, idx)] = value if reach is True or old is None else select(reach, value, old)
            else:
                self.memory = {}  # unknown index write: forget
            return
        raise ValueError("Unhandled instruction: " + line)

    def call(self, dest, expr):
        m = re.match(r"call (?:\S+ )?(?:%\S+|\w+) @dx\.op\.(\w+)(?:\.(\w+))?\((.*)\)\s*(?:;.*)?$", expr)
        if not m:
            m = re.match(r"call void @dx\.op\.(\w+)(?:\.(\w+))?\((.*)\)", expr)
        name, args = m.group(1), self.args(m.group(3))
        ty = {"f32": "float", "i32": "i32", "f16": "half", "i1": "i1"}.get(m.group(2) or "", "float")
        vals = [self.val(t, a.split(" ")[0] if a else "i32") for a, t in args]
        opcode = vals[0]
        if name == "createHandle":
            self.v[dest] = ("handle", vals[1], vals[3])  # class (0 SRV, 1 UAV, 2 CBV, 3 sampler), bind slot
            return
        if name == "loadInput":
            sig, row, col = vals[1], vals[2], vals[3]
            self.v[dest] = E("in", int(sig), int(row) if is_num(row) else row, int(col))
            return
        if name == "storeOutput":
            self.outputs[(int(vals[1]), int(vals[3]))] = vals[4]
            self.outputs_rows[(int(vals[1]), int(vals[2]) if is_num(vals[2]) else vals[2], int(vals[3]))] = vals[4]
            return
        if name == "cbufferLoadLegacy":
            self.v[dest] = self.cbload(self.v[args[1][1]], vals[2], ty)
            return
        if name in ("sample", "sampleBias", "sampleLevel", "sampleGrad", "sampleCmp", "sampleCmpLevelZero",
                    "textureLoad", "textureGather", "textureGatherCmp", "bufferLoad"):
            h = self.v[args[1][1]]
            coords = tuple(v for v in vals[3:7] if not (isinstance(v, E) and v.op == "undef")) if name != "textureLoad" and name != "bufferLoad" \
                else tuple(v for v in vals[2:6] if not (isinstance(v, E) and v.op == "undef"))
            extra = ()
            if name == "sampleLevel": extra = (("lod", vals[10]),)
            if name == "sampleBias": extra = (("bias", vals[10]),)
            sample = E("tex", name, h[2], coords, extra)
            self.v[dest] = ("res", [E("ch", sample, i) for i in range(4)] + [E("status", sample)])
            return
        if name == "unary":
            self.v[dest] = unary(opcode, vals[1]); return
        if name == "unaryBits":
            self.v[dest] = E("bits%d" % opcode, vals[1]); return
        if name == "binary":
            a, b = vals[1], vals[2]
            if opcode == 35: self.v[dest] = fmax(a, b)
            elif opcode == 36: self.v[dest] = fmin(a, b)
            elif is_num(a) and is_num(b) and opcode in (37, 38, 39, 40):
                self.v[dest] = {37: lambda: max(s32(a), s32(b)) & 0xffffffff, 38: lambda: min(s32(a), s32(b)) & 0xffffffff,
                                39: lambda: max(a, b), 40: lambda: min(a, b)}[opcode]()
            else: self.v[dest] = E("binop%d" % opcode, a, b)
            return
        if name == "tertiary":
            a, b, c = vals[1], vals[2], vals[3]
            if opcode in (46, 47): self.v[dest] = add(mul(a, b), c)
            elif opcode in (48, 49) and is_num(a) and is_num(b) and is_num(c): self.v[dest] = (a * b + c) & 0xffffffff
            else: self.v[dest] = E("terop%d" % opcode, a, b, c)
            return
        if name == "dot3" and ROWDOT:
            a, b = tuple(vals[1:4]), tuple(vals[4:7])
            for row, other in ((a, b), (b, a)):
                if all(isinstance(v, E) and v.op == "in" for v in row) and len({(v.args[0], v.args[1]) for v in row}) == 1                         and [v.args[2] for v in row] == [0, 1, 2] and not all(isinstance(v, E) and v.op == "in" for v in other):
                    self.v[dest] = E("rowdot", row[0].args[0], row[0].args[1], other)
                    return
        if name in ("dot2", "dot3", "dot4"):
            n = int(name[-1])
            r = 0.0
            for i in range(n):
                r = add(r, mul(vals[1 + i], vals[1 + n + i]))
            self.v[dest] = r
            return
        if name == "discard":
            self.discards.append(band(self.reach, vals[1]))
            return
        if name == "legacyF16ToF32":
            self.v[dest] = E("f16tof32", vals[1]); return
        raise ValueError("Unhandled dx.op " + name)

    def reach_of_block(self):
        return True


# ---------------------------------------------------------------- printing
def render(roots, names=None, inline_limit=1):
    """Render a list of (label, value) as let-bound DAG text, sharing nodes used more than once."""
    names = names or {}
    uses = {}

    def visit(x):
        if isinstance(x, E):
            uses[x] = uses.get(x, 0) + 1
            if uses[x] == 1:
                for a in x.args:
                    if isinstance(a, tuple):
                        for b in a:
                            if isinstance(b, tuple):
                                for c in b: visit(c)
                            else: visit(b)
                    else:
                        visit(a)
    for _, v in roots:
        visit(v)
    lines, done = [], {}

    def fmt(x, top=False):
        if isinstance(x, bool): return str(x).lower()
        if isinstance(x, float): return ("%.7g" % x)
        if isinstance(x, int): return str(x)
        if isinstance(x, tuple): return "(" + ", ".join(fmt(a) for a in x) + ")"
        if not isinstance(x, E): return str(x)
        if x in done: return done[x]
        s = leaf(x)
        if s is None:
            a = [fmt(y) for y in x.args]
            o = x.op
            s = {"add": lambda: "(%s + %s)" % tuple(a), "sub": lambda: "(%s - %s)" % tuple(a),
                 "mul": lambda: "%s*%s" % tuple(a), "div": lambda: "(%s / %s)" % tuple(a),
                 "neg": lambda: "-" + a[0], "select": lambda: "(%s ? %s : %s)" % tuple(a),
                 "ch": lambda: "%s.%s" % (a[0], XYZW[x.args[1]] if x.args[1] < 4 else "status"),
                 }.get(o, lambda: "%s(%s)" % (o, ", ".join(a)))()
        if uses.get(x, 0) > inline_limit and not top and len(s) > 12:
            name = names.get(x) or "v%d" % x.id
            lines.append("%s = %s" % (name, s))
            done[x] = name
            return name
        return s

    def leaf(x):
        if x.op == "in":
            return "IN%d[%s].%s" % (x.args[0], x.args[1], XYZW[x.args[2]])
        if x.op == "cb":
            return "cb%d[%s].%s" % (x.args[0], x.args[1] if not isinstance(x.args[1], E) else fmt(x.args[1]), XYZW[x.args[2]])
        if x.op == "tex":
            kind, slot, coords, extra = x.args
            s = "%s(t%d, %s%s)" % (kind, slot, ", ".join(fmt(c) for c in coords),
                                    "".join(", %s=%s" % (k, fmt(v)) for k, v in extra))
            if x not in done:
                name = names.get(x) or "s%d" % x.id
                lines.append("%s = %s" % (name, s))
                done[x] = name
            return done[x]
        return None
    out = []
    for label, v in roots:
        out.append("%s = %s" % (label, fmt(v, top=True)))
    return "\n".join(lines + [""] + out)


def evaluate_ps(text, cbuffers):
    prog = Program(text)
    ev = Evaluator(prog, cbuffers).run()
    return prog, ev

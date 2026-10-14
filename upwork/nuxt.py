"""Upwork's pages are Nuxt apps that ship their whole data model in the HTML,
so no page needs JavaScript to scrape — this module turns the two embedding
formats back into plain Python.

  Nuxt 3 (job search, talent search, job details, agency, hire/*,
  freelance-jobs/*):  <script id="__NUXT_DATA__" type="application/json">
  holds a `devalue` array: index 0 is the root, every other value is either
  a primitive or a dict/list whose children are INDEXES into the array, and
  tagged pairs mark special values (["Reactive", i], ["EmptyRef", "json"],
  ["Date", iso], ["Map", ...]). decode_nuxt3() rebuilds the object graph.

  Nuxt 2 (freelancer profiles, project catalog):  window.__NUXT__ =
  (function(a,b,c,…){K.name="Newest";aR[0]={…};return {…}}("v1", "v2", …))
  — the state object with every repeated value hoisted into a function
  parameter, plus a few hoisted assignments before the `return`. There is no
  node in the scrapers image, so decode_nuxt2() runs that function with a
  small interpreter for exactly the JavaScript this format uses: object /
  array literals, strings, numbers, booleans, null, void 0, parameter
  references and `ident(.prop|[index])* = expr;` statements.

Both decoders raise NuxtStateError when the markup is not what they expect
(a Cloudflare interstitial, a layout change) so the caller can classify it.
"""
import json
import re

_NUXT3_RE = re.compile(r'<script[^>]+id="__NUXT_DATA__"[^>]*>(.*?)</script>', re.S)
_NUXT2_RE = re.compile(r"window\.__NUXT__\s*=\s*\(function\s*\(([^)]*)\)\s*\{")


class NuxtStateError(ValueError):
    """The page carries no decodable Nuxt state."""


# ---- Nuxt 3 / devalue ---------------------------------------------------------------------------

_UNDEFINED = object()
_SPECIAL = {-1: _UNDEFINED, -2: None, -3: float("nan"), -4: float("inf"), -5: float("-inf"), -6: -0.0}
_WRAPPERS = ("Reactive", "ShallowReactive", "Ref", "ShallowRef", "Island", "NuxtError")


def decode_nuxt3(html):
    """The dehydrated Nuxt 3 state of a page as a plain dict."""
    match = _NUXT3_RE.search(html or "")
    if not match:
        raise NuxtStateError("no __NUXT_DATA__ script in the page")
    try:
        values = json.loads(match.group(1))
    except ValueError as e:
        raise NuxtStateError(f"__NUXT_DATA__ is not JSON: {e}")
    if not isinstance(values, list) or not values:
        raise NuxtStateError("__NUXT_DATA__ is not a devalue array")
    memo = {}

    def hydrate(index):
        if not isinstance(index, int) or isinstance(index, bool):
            return index
        if index < 0:
            value = _SPECIAL.get(index)
            return None if value is _UNDEFINED else value
        if index in memo:
            return memo[index]
        if not 0 <= index < len(values):
            return None
        raw = values[index]
        if isinstance(raw, list):
            if len(raw) == 2 and isinstance(raw[0], str):
                tag = raw[0]
                if tag in _WRAPPERS:
                    out = hydrate(raw[1])
                    memo[index] = out
                    return out
                if tag in ("EmptyRef", "EmptyShallowRef"):
                    # Nuxt's reviver: "_" is undefined, "0n" BigInt(0), else JSON
                    try:
                        out = None if raw[1] == "_" else json.loads(raw[1]) if isinstance(raw[1], str) else raw[1]
                    except ValueError:
                        out = raw[1]
                    memo[index] = out
                    return out
                if tag in ("Date", "RegExp", "BigInt"):
                    memo[index] = raw[1]
                    return raw[1]
            if raw and isinstance(raw[0], str) and raw[0] in ("Map", "Set", "Object", "null"):
                items = [hydrate(i) for i in raw[1:]]
                if raw[0] in ("Map", "null"):     # ["null", k, v, …] is an Object.create(null) dict
                    out = {str(items[i]): items[i + 1] for i in range(0, len(items) - 1, 2)}
                else:
                    out = items
                memo[index] = out
                return out
            out = []
            memo[index] = out
            out.extend(hydrate(i) for i in raw)
            return out
        if isinstance(raw, dict):
            out = {}
            memo[index] = out
            for key, i in raw.items():
                out[key] = hydrate(i)
            return out
        memo[index] = raw
        return raw

    root = hydrate(0)
    if not isinstance(root, dict):
        raise NuxtStateError("__NUXT_DATA__ root is not an object")
    return root


# ---- Nuxt 2 / hoisted function ---------------------------------------------------------------

class _Parser:
    """Recursive-descent reader for the JavaScript subset Nuxt 2 emits."""

    def __init__(self, src, env):
        self.s = src
        self.n = len(src)
        self.i = 0
        self.env = env

    # -- helpers -------------------------------------------------------------------------
    def error(self, what):
        snippet = self.s[self.i:self.i + 40]
        raise NuxtStateError(f"__NUXT__ parse error: {what} at {self.i}: {snippet!r}")

    def skip_ws(self):
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c in " \t\r\n":
                self.i += 1
            elif c == "/" and self.i + 1 < n and s[self.i + 1] == "*":
                end = s.find("*/", self.i + 2)
                self.i = n if end < 0 else end + 2
            else:
                break

    def peek(self):
        self.skip_ws()
        return self.s[self.i] if self.i < self.n else ""

    def expect(self, ch):
        if self.peek() != ch:
            self.error(f"expected {ch!r}")
        self.i += 1

    def ident(self):
        self.skip_ws()
        j = self.i
        s = self.s
        while j < self.n and (s[j].isalnum() or s[j] in "_$"):
            j += 1
        if j == self.i:
            self.error("expected an identifier")
        name = s[self.i:j]
        self.i = j
        return name

    # -- values ----------------------------------------------------------------------------
    def string(self):
        quote = self.s[self.i]
        self.i += 1
        out = []
        s, n = self.s, self.n
        while self.i < n:
            c = s[self.i]
            if c == quote:
                self.i += 1
                return "".join(out)
            if c == "\\":
                self.i += 1
                e = s[self.i]
                if e == "u":
                    code = int(s[self.i + 1:self.i + 5], 16)
                    self.i += 5
                    if 0xD800 <= code < 0xDC00 and s[self.i:self.i + 2] == "\\u":
                        low = int(s[self.i + 2:self.i + 6], 16)
                        if 0xDC00 <= low < 0xE000:
                            code = 0x10000 + ((code - 0xD800) << 10) + (low - 0xDC00)
                            self.i += 6
                    out.append(chr(code))
                    continue
                if e == "x":
                    out.append(chr(int(s[self.i + 1:self.i + 3], 16)))
                    self.i += 3
                    continue
                out.append({"n": "\n", "r": "\r", "t": "\t", "b": "\b", "f": "\f", "v": "\v", "0": "\0",
                            "\n": ""}.get(e, e))
                self.i += 1
                continue
            out.append(c)
            self.i += 1
        self.error("unterminated string")

    _NUMBER_RE = re.compile(r"-?(?:0[xX][0-9a-fA-F]+|(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?)")

    def number(self):
        m = self._NUMBER_RE.match(self.s, self.i)
        if not m:
            self.error("expected a number")
        self.i = m.end()
        text = m.group(0)
        if text[-1:] == "." :
            text = text[:-1]
        if "x" in text.lower():
            return int(text, 16)
        if any(c in text for c in ".eE"):
            value = float(text)
            return int(value) if value.is_integer() and abs(value) < 1e15 else value
        return int(text)

    def value(self):
        c = self.peek()
        if c == "":
            self.error("unexpected end")
        if c in "\"'":
            return self.string()
        if c == "{":
            return self.obj()
        if c == "[":
            return self.arr()
        if c == "-" or c == "." or c.isdigit():
            if c == "-" and self.s.startswith("-Infinity", self.i):
                self.i += 9
                return None
            return self.number()
        if c == "!":
            self.i += 1
            return not self.value()
        name = self.ident()
        if name == "true":
            return True
        if name == "false":
            return False
        if name in ("null", "undefined", "NaN", "Infinity"):
            return None
        if name == "void":
            self.value()
            return None
        if name == "Array":
            # Array(n): a sparse array of n empty slots
            self.expect("(")
            size = 0 if self.peek() == ")" else self.value()
            self.expect(")")
            return [None] * int(size or 0)
        if name == "new":
            # new Date("…") / new Map([...]) — keep the argument as-is
            self.ident()
            self.expect("(")
            arg = None if self.peek() == ")" else self.value()
            self.expect(")")
            return arg
        if name not in self.env:
            self.error(f"unknown identifier {name!r}")
        return self.env[name]

    def key(self):
        c = self.peek()
        if c in "\"'":
            return self.string()
        if c == "[":
            self.i += 1
            k = self.value()
            self.expect("]")
            return str(k)
        if c.isdigit() or c == "-" or c == ".":
            return str(self.number())
        return self.ident()

    def obj(self):
        self.expect("{")
        out = {}
        while True:
            if self.peek() == "}":
                self.i += 1
                return out
            k = self.key()
            self.expect(":")
            out[k] = self.value()
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "}":
                self.error("expected ',' or '}'")

    def arr(self):
        self.expect("[")
        out = []
        while True:
            c = self.peek()
            if c == "]":
                self.i += 1
                return out
            if c == ",":
                self.i += 1
                out.append(None)
                continue
            out.append(self.value())
            c = self.peek()
            if c == ",":
                self.i += 1
            elif c != "]":
                self.error("expected ',' or ']'")

    # -- statements --------------------------------------------------------------------------
    def body(self):
        """Run the hoisted assignments and return the `return` expression."""
        while True:
            self.skip_ws()
            if self.s.startswith("return", self.i) and not (self.s[self.i + 6].isalnum() or self.s[self.i + 6] in "_$"):
                self.i += 6
                return self.value()
            target = self.env.get(self.ident())
            # ident(.prop | [index])* = value ;
            path = []
            while True:
                c = self.peek()
                if c == ".":
                    self.i += 1
                    path.append(self.ident())
                elif c == "[":
                    self.i += 1
                    path.append(self.value())
                    self.expect("]")
                else:
                    break
            self.expect("=")
            rhs = self.value()
            if self.peek() == ";":
                self.i += 1
            if not path:
                continue
            container = target
            for step in path[:-1]:
                container = _descend(container, step)
                if container is None:
                    break
            if container is not None:
                _assign(container, path[-1], rhs)


def _descend(container, step):
    if isinstance(container, dict):
        return container.get(str(step))
    if isinstance(container, list) and isinstance(step, int) and 0 <= step < len(container):
        return container[step]
    return None


def _assign(container, step, value):
    if isinstance(container, dict):
        container[str(step)] = value
    elif isinstance(container, list) and isinstance(step, int):
        while len(container) <= step:
            container.append(None)
        container[step] = value


def decode_nuxt2(html):
    """The `window.__NUXT__` state of a Nuxt 2 page as a plain dict."""
    match = _NUXT2_RE.search(html or "")
    if not match:
        raise NuxtStateError("no window.__NUXT__ function in the page")
    params = [p.strip() for p in match.group(1).split(",") if p.strip()]
    start = match.end()
    end = (html or "").find("</script>", start)
    src = html[start:end]
    # the function body ends at the matching "}(" that opens the argument list
    close = src.rfind("}(")
    if close < 0:
        raise NuxtStateError("__NUXT__ function has no argument list")
    body_src, args_src = src[:close], src[close + 2:]
    args_src = args_src.rstrip().rstrip(";").rstrip()
    if args_src.endswith("))"):
        args_src = args_src[:-2]
    elif args_src.endswith(")"):
        args_src = args_src[:-1]
    arg_parser = _Parser("[" + args_src + "]", {})
    args = arg_parser.arr()
    env = {name: (args[i] if i < len(args) else None) for i, name in enumerate(params)}
    state = _Parser(body_src, env).body()
    if not isinstance(state, dict):
        raise NuxtStateError("__NUXT__ state is not an object")
    return state


def decode(html):
    """Whichever state the page carries (Nuxt 3 first, then Nuxt 2)."""
    if "__NUXT_DATA__" in (html or ""):
        return decode_nuxt3(html)
    return decode_nuxt2(html)


_LD_JSON_RE = re.compile(r'<script[^>]+type="application/ld\+json"[^>]*>(.*?)</script>', re.S)


def ld_json(html):
    """Every schema.org JSON-LD block in the page (bad ones skipped)."""
    out = []
    for raw in _LD_JSON_RE.findall(html or ""):
        try:
            out.append(json.loads(raw))
        except ValueError:
            continue
    return out

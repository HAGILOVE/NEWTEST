"""
Value parsing and re-serialisation for ``.aedt`` property statements.

Statement shapes handled::

    Key='text'                     -> str
    Key=12.5                       -> float / int
    Key=true                       -> bool
    Key=[1, 2, 3]                  -> list
    Key(arg, 'arg', 3)             -> Call(name, args)
    Key[3: 'a', 'b', 'c']          -> Indexed list (HFSS's counted-array form)

Round-trip fidelity is the point: :func:`format_value` reproduces HFSS's own
spelling (single quotes, ``true``/``false``, no space after commas inside
brackets) so a re-written file diffs cleanly against the original.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple

from ...core.logging import get_logger

log = get_logger("io.aedt.values")

KEY_RE = re.compile(r"^([A-Za-z_$][\w \-./%]*)")


@dataclass
class Call:
    """``Name(arg, ...)`` -- HFSS's function-style property."""
    name: str
    args: List[Any] = field(default_factory=list)

    def __repr__(self):
        return f"{self.name}({', '.join(map(str, self.args))})"


@dataclass
class Counted:
    """``Name[n: v1, v2, ...]`` -- HFSS's length-prefixed array."""
    name: str
    items: List[Any] = field(default_factory=list)

    def __repr__(self):
        return f"{self.name}[{len(self.items)}: ...]"


class ParseError(ValueError):
    pass


def parse_statement(text: str) -> Tuple[Optional[str], Any]:
    """
    Return ``(key, value)`` for a property statement, or ``(None, raw)``.

    A statement that cannot be parsed is **never** an error: the whole point of
    reading someone else's project file is that it may contain things this
    parser has not seen -- an embedded blob, a quote convention from a
    different release, a value split in a way the joiner did not expect. Those
    come back as an unparsed statement carrying its exact text, so the tree
    still holds it, the round trip is still byte-exact, and the one statement
    is simply not available as a value. Losing a whole project to one odd line
    is the failure this prevents (it read, from the outside, as
    "unterminated string near offset 0" and an empty screen).
    """
    s = text.strip()
    if not s:
        return None, ""
    m = KEY_RE.match(s)
    if not m:
        return None, s
    key = m.group(1).strip()
    rest = s[m.end():].lstrip()
    try:
        if rest.startswith("="):
            val, _ = _parse_value(rest[1:].strip(), 0)
            return key, val
        if rest.startswith("("):
            args, _ = _parse_seq(rest, 0, "(", ")")
            return key, Call(key, args)
        if rest.startswith("["):
            items, _ = _parse_counted(rest, 0)
            return key, Counted(key, items)
    except ParseError as exc:
        log.debug("keeping %s verbatim: %s", key, exc)
        return None, s
    except RecursionError:                                  # pragma: no cover
        return None, s
    if not rest:
        return key, None
    return None, s


def _parse_value(s: str, i: int) -> Tuple[Any, int]:
    s_ = s[i:].lstrip()
    i += len(s[i:]) - len(s_)
    if not s_:
        return "", i
    c = s_[0]
    if c == "'":
        return _parse_string(s, i)
    if c == "[":
        return _parse_seq(s, i, "[", "]")
    if c == "(":
        return _parse_seq(s, i, "(", ")")
    j = i
    depth = 0
    while j < len(s):
        ch = s[j]
        if ch in "([":
            depth += 1
        elif ch in ")]":
            if depth == 0:
                break
            depth -= 1
        elif ch == "," and depth == 0:
            break
        j += 1
    tok = s[i:j].strip()
    return _atom(tok), j


def _parse_string(s: str, i: int) -> Tuple[str, int]:
    assert s[i] == "'"
    out = []
    j = i + 1
    while j < len(s):
        ch = s[j]
        if ch == "\\" and j + 1 < len(s):
            out.append(s[j + 1])
            j += 2
            continue
        if ch == "'":
            return "".join(out), j + 1
        out.append(ch)
        j += 1
    raise ParseError(f"unterminated string near offset {i}")


def _parse_seq(s: str, i: int, op: str, cl: str) -> Tuple[List[Any], int]:
    assert s[i] == op
    i += 1
    out: List[Any] = []
    while i < len(s):
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == cl:
            return out, i + 1
        v, i = _parse_value(s, i)
        out.append(v)
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
    return out, i


def _parse_counted(s: str, i: int) -> Tuple[List[Any], int]:
    assert s[i] == "["
    j = s.index(":", i) if ":" in s[i:i + 24] else -1
    if j < 0:
        seq, k = _parse_seq(s, i, "[", "]")
        return seq, k
    i = j + 1
    out: List[Any] = []
    while i < len(s):
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == "]":
            return out, i + 1
        v, i = _parse_value(s, i)
        out.append(v)
        while i < len(s) and s[i] in " \t":
            i += 1
        if i < len(s) and s[i] == ",":
            i += 1
    return out, i


def _atom(tok: str) -> Any:
    t = tok.strip()
    if t == "":
        return ""
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    try:
        if re.fullmatch(r"[+-]?\d+", t):
            return int(t)
        return float(t)
    except ValueError:
        return t


# --------------------------------------------------------------------------
# serialisation
# --------------------------------------------------------------------------


def format_value(v: Any) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if v is None:
        return ""
    if isinstance(v, str):
        return "'" + v.replace("\\", "\\\\").replace("'", "\\'") + "'"
    if isinstance(v, int):
        return str(v)
    if isinstance(v, float):
        return _fmt_float(v)
    if isinstance(v, Call):
        return f"{v.name}({', '.join(format_value(a) for a in v.args)})"
    if isinstance(v, Counted):
        inner = ", ".join(format_value(a) for a in v.items)
        return f"{v.name}[{len(v.items)}: {inner}]"
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(format_value(a) for a in v) + "]"
    return str(v)


def _fmt_float(x: float) -> str:
    if x == int(x) and abs(x) < 1e15:
        return f"{int(x)}"
    s = repr(float(x))
    return s


def format_statement(key: str, value: Any) -> str:
    if isinstance(value, (Call, Counted)) and value.name == key:
        return format_value(value)
    if value is None:
        return key
    return f"{key}={format_value(value)}"


__all__ = ["parse_statement", "format_statement", "format_value", "Call",
           "Counted", "ParseError"]

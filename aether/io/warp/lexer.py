"""
Lexer for the ``.warp`` project-tree text format.

An ``.warp`` file is a nested, tab-indented block tree::

    $begin 'WarpsProject'
        Created='Tue Sep 02 09:11:04 2025'
        $begin 'Desktop'
            Version(2024, 2)
        $end 'Desktop'
    $end 'WarpsProject'

Two rules drive this implementation:

* **quote awareness** -- ``$begin`` / ``$end`` and separators are only
  recognised outside single-quoted strings, so a property whose value happens
  to contain ``$end`` never truncates the file;
* **raw preservation** -- every logical line keeps its exact original text.
  The writer re-emits that text verbatim unless the value was modified, which
  is what makes an untouched round trip byte-for-byte identical.

Logical lines may span several physical lines when brackets, parentheses or
quotes are still open -- Warps wraps long dataset and expression entries this
way -- so the lexer joins them before handing anything to the parser.
"""
from __future__ import annotations

import io
import os
import re
from dataclasses import dataclass
from typing import Iterator, List, Optional, Tuple

BEGIN_RE = re.compile(r"^\s*\$begin\s+'((?:[^'\\]|\\.)*)'\s*$")
END_RE = re.compile(r"^\s*\$end\s+'((?:[^'\\]|\\.)*)'\s*$")
# A length-prefixed binary payload: "BIN" then a fixed-width byte count, then
# exactly that many bytes of raw data on the following lines. Warps uses it to
# carry Parasolid (.x_b) bodies, thumbnails and other attachments inside the
# text tree, and the bytes contain quotes, brackets and even literal "$end"
# sequences -- so they must be consumed by length, never scanned as lines.
BIN_RE = re.compile(r"^BIN(\d{6,20})$")

ENCODINGS = ("utf-8-sig", "utf-8", "cp1252", "latin-1")


@dataclass
class LogicalLine:
    """One complete statement plus the exact bytes it came from."""
    text: str                 # joined, newline-free
    raw: str                  # original text including internal newlines
    indent: str               # leading whitespace of the first physical line
    lineno: int
    binary: bool = False      # a BIN<count> header plus its raw payload

    @property
    def kind(self) -> str:
        if self.binary:
            return "binary"
        if BEGIN_RE.match(self.text):
            return "begin"
        if END_RE.match(self.text):
            return "end"
        return "prop"

    @property
    def block_name(self) -> Optional[str]:
        m = BEGIN_RE.match(self.text) or END_RE.match(self.text)
        return _unescape(m.group(1)) if m else None


def _unescape(s: str) -> str:
    return s.replace("\\'", "'").replace("\\\\", "\\")


def read_text(path: str) -> Tuple[str, str, str]:
    """
    Read an ``.warp`` (or ``.warpz``) file.

    Returns ``(text, encoding, newline)`` so the writer can reproduce the exact
    original byte conventions.
    """
    if path.lower().endswith(".warpz"):
        from .archive import read_warpz
        return read_warpz(path)
    with open(path, "rb") as fh:
        data = fh.read()
    return decode_bytes(data)


def decode_bytes(data: bytes) -> Tuple[str, str, str]:
    """Decode project bytes, preserving BOM presence and newline style."""
    import codecs
    # UTF-16 projects otherwise decode as Latin-1 with embedded NULs and
    # silently appear to contain zero Warps designs.
    if data.startswith((codecs.BOM_UTF16_LE, codecs.BOM_UTF16_BE)):
        text=data.decode("utf-16")
        return text,"utf-16","\r\n" if "\r\n" in text[:65536] else "\n"
    newline = "\r\n" if b"\r\n" in data[:65536] else "\n"
    order = ENCODINGS if data.startswith(codecs.BOM_UTF8) \
        else tuple(e for e in ENCODINGS if e != "utf-8-sig")
    for enc in order:
        try:
            return data.decode(enc), enc, newline
        except UnicodeDecodeError:
            continue
    return data.decode("latin-1", errors="replace"), "latin-1", newline


def split_logical(text: str) -> List[LogicalLine]:
    """
    Group physical lines into complete, bracket-balanced statements.

    Two things make this more than a line split: statements wrap across
    physical lines while brackets or quotes are open, and a ``BIN<count>``
    header is followed by exactly *count* bytes of binary payload that must be
    taken verbatim. Walking into such a payload line by line is what used to
    end in ``unterminated block 'x_b'`` on any project saved with native
    (Parasolid) bodies -- which is most projects built in the Warps modeller.
    """
    lines = text.split("\n")
    out: List[LogicalLine] = []
    i = 0
    n = len(lines)
    # Character offset of the start of line i, so a payload can be taken from
    # the text directly rather than from the split lines.
    offsets = [0] * (n + 1)
    for k, ln in enumerate(lines):
        offsets[k + 1] = offsets[k] + len(ln) + 1
    while i < n:
        first = lines[i].rstrip("\r")
        if not first.strip():
            out.append(LogicalLine("", first, "", i + 1))
            i += 1
            continue

        m = BIN_RE.match(first.strip())
        if m:
            size = int(m.group(1))
            start = offsets[i] + len(lines[i]) + 1          # just past the \n
            payload = text[start:start + size]
            raw = first + "\n" + payload
            out.append(LogicalLine(first.strip(), raw, "", i + 1,
                                   binary=True))
            # Resume at the line the payload ends in: what follows it on that
            # same line (typically "$end 'x_b'") is the next statement.
            consumed = payload.count("\n")
            i += 1 + consumed
            if i < n:
                tail_start = offsets[i]
                cut = start + size - tail_start
                if cut > 0:
                    lines[i] = lines[i][cut:]
                    offsets[i] += cut
            continue

        buf = [first]
        depth, in_str = _scan(first, 0, False)
        # A quoted value continues onto the next line only when the line ends
        # with a backslash -- the continuation Warps actually writes, in the
        # base64 blocks. Without that rule one stray apostrophe swallows the
        # entire rest of the file, and the parse dies at the far end with
        # "unterminated string near offset 0": the damage is one character
        # long and the report points thousands of lines away from it.
        cont = in_str and first.endswith("\\")
        j = i
        while (depth > 0 or cont) and j + 1 < n:
            j += 1
            nxt = lines[j].rstrip("\r")
            buf.append(nxt)
            depth, in_str = _scan(nxt, depth, in_str if cont else False)
            cont = in_str and nxt.endswith("\\")
        raw = "\n".join(buf)
        joined = "".join(b.strip() if k else b for k, b in enumerate(buf))
        indent = first[:len(first) - len(first.lstrip())]
        out.append(LogicalLine(joined.strip(), raw, indent, i + 1))
        i = j + 1
    return out


def _scan(s: str, depth: int, in_str: bool) -> Tuple[int, bool]:
    """Track bracket depth and string state across one physical line."""
    esc = False
    for ch in s:
        if in_str:
            if esc:
                esc = False
            elif ch == "\\":
                esc = True
            elif ch == "'":
                in_str = False
            continue
        if ch == "'":
            in_str = True
        elif ch in "([{":
            depth += 1
        elif ch in ")]}":
            depth -= 1
    return max(depth, 0), in_str


__all__ = ["LogicalLine", "split_logical", "read_text", "BEGIN_RE",
           "END_RE", "BIN_RE"]

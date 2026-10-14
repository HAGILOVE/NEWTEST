"""
The ``.aedt`` document object model.

``AedtDocument`` owns an ordered tree of :class:`AedtBlock` and
:class:`AedtProp` nodes.  Every node caches the exact source text it was
parsed from; serialising a node that has not been modified re-emits that text
untouched, so

    write(parse(f)) == f      (byte for byte)

Editing a property flips a dirty flag and only that one statement is
re-rendered.  Blocks can be created, moved and deleted; new nodes are rendered
with HFSS's own conventions (tab indentation, single-quoted strings).
"""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Iterator, List, Optional, Union

from ...core.logging import get_logger
from .lexer import LogicalLine, read_text, split_logical
from .values import Call, Counted, format_statement, parse_statement

log = get_logger("io.aedt.tree")

INDENT = "\t"


class AedtNode:
    parent: Optional["AedtBlock"] = None

    def render(self, depth: int) -> List[str]:  # pragma: no cover
        raise NotImplementedError


@dataclass
class AedtProp(AedtNode):
    """A single ``Key=value`` (or ``Key(...)``) statement."""
    key: Optional[str]
    value: Any = None
    raw: Optional[str] = None
    dirty: bool = False
    blank: bool = False
    parent: Optional["AedtBlock"] = field(default=None, repr=False, compare=False)

    def set(self, value: Any) -> "AedtProp":
        self.value = value
        self.dirty = True
        return self

    def render(self, depth: int) -> List[str]:
        if self.blank:
            return [self.raw if self.raw is not None else ""]
        if not self.dirty and self.raw is not None:
            return self.raw.split("\n")
        if self.key is None:
            return [INDENT * depth + str(self.value)]
        return [INDENT * depth + format_statement(self.key, self.value)]

    def __repr__(self):
        return f"<Prop {self.key}={self.value!r}>"


@dataclass
class AedtBinary(AedtNode):
    """
    A ``BIN<count>`` header and the raw bytes that follow it.

    HFSS carries Parasolid bodies, thumbnails and other attachments this way,
    inside the otherwise textual tree. The payload is opaque: it is never
    re-indented, re-quoted or line-split, and it renders as one unit so the
    bytes come back exactly as they went in.
    """
    header: str                       # e.g. "BIN000000006179"
    payload: str                      # exactly <count> characters, verbatim
    # HFSS writes the closing "$end" immediately after the last payload byte,
    # with no newline between them. That is part of the framing, so it has to
    # be reproduced: the statement after the payload is merged onto its line.
    merge_next: bool = True
    parent: Optional["AedtBlock"] = field(default=None, repr=False, compare=False)

    @property
    def size(self) -> int:
        return len(self.payload)

    def data(self, encoding: str = "latin-1") -> bytes:
        """The payload as bytes, for writing the attachment out."""
        return self.payload.encode(encoding, errors="replace")

    def render(self, depth: int) -> List[str]:
        # One element: any newline inside the payload is data, not a line
        # separator, and must not be rewritten to the document's newline style.
        return [self.header + "\n" + self.payload]

    def __repr__(self):
        return f"<Binary {self.size} bytes>"


@dataclass
class AedtBlock(AedtNode):
    """``$begin 'Name' ... $end 'Name'``."""
    name: str
    children: List[AedtNode] = field(default_factory=list)
    raw_begin: Optional[str] = None
    raw_end: Optional[str] = None
    parent: Optional["AedtBlock"] = field(default=None, repr=False, compare=False)

    # ---- construction ----------------------------------------------------
    def add(self, node: AedtNode, index: Optional[int] = None) -> AedtNode:
        node.parent = self
        if index is None:
            self.children.append(node)
        else:
            self.children.insert(index, node)
        return node

    def add_block(self, name: str, index: Optional[int] = None) -> "AedtBlock":
        return self.add(AedtBlock(name), index)          # type: ignore

    def add_prop(self, key: str, value: Any,
                 index: Optional[int] = None) -> AedtProp:
        return self.add(AedtProp(key, value, dirty=True), index)  # type: ignore

    def remove(self, node: AedtNode) -> None:
        self.children.remove(node)

    # ---- queries ---------------------------------------------------------
    @property
    def blocks(self) -> List["AedtBlock"]:
        return [c for c in self.children if isinstance(c, AedtBlock)]

    @property
    def props(self) -> List[AedtProp]:
        return [c for c in self.children if isinstance(c, AedtProp)
                and not c.blank]

    def block(self, name: str) -> Optional["AedtBlock"]:
        for c in self.children:
            if isinstance(c, AedtBlock) and c.name == name:
                return c
        return None

    def all_blocks(self, name: str) -> List["AedtBlock"]:
        return [c for c in self.children
                if isinstance(c, AedtBlock) and c.name == name]

    def find(self, name: str, recursive: bool = True) -> List["AedtBlock"]:
        out: List["AedtBlock"] = []
        for c in self.children:
            if isinstance(c, AedtBlock):
                if c.name == name:
                    out.append(c)
                if recursive:
                    out.extend(c.find(name, True))
        return out

    def path(self, *names: str) -> Optional["AedtBlock"]:
        node: Optional[AedtBlock] = self
        for n in names:
            if node is None:
                return None
            node = node.block(n)
        return node

    def prop(self, key: str) -> Optional[AedtProp]:
        for c in self.children:
            if isinstance(c, AedtProp) and c.key == key:
                return c
        return None

    def get(self, key: str, default: Any = None) -> Any:
        p = self.prop(key)
        return default if p is None else p.value

    def set(self, key: str, value: Any) -> AedtProp:
        p = self.prop(key)
        if p is None:
            return self.add_prop(key, value)
        return p.set(value)

    def __getitem__(self, key: Union[str, int]):
        if isinstance(key, int):
            return self.children[key]
        b = self.block(key)
        if b is not None:
            return b
        p = self.prop(key)
        if p is not None:
            return p.value
        raise KeyError(key)

    def __contains__(self, key: str) -> bool:
        return self.block(key) is not None or self.prop(key) is not None

    def walk(self) -> Iterator["AedtBlock"]:
        yield self
        for c in self.children:
            if isinstance(c, AedtBlock):
                yield from c.walk()

    # ---- rendering -------------------------------------------------------
    def render(self, depth: int) -> List[str]:
        pad = INDENT * depth
        begin = self.raw_begin if self.raw_begin is not None \
            else f"{pad}$begin '{_esc(self.name)}'"
        end = self.raw_end if self.raw_end is not None \
            else f"{pad}$end '{_esc(self.name)}'"
        out = [begin]
        merge = False
        for c in self.children:
            for k, line in enumerate(c.render(depth + 1)):
                if merge:
                    out[-1] += line
                    merge = False
                else:
                    out.append(line)
            merge = isinstance(c, AedtBinary) and c.merge_next
        if merge:
            out[-1] += end
        else:
            out.append(end)
        return out

    def __repr__(self):
        return (f"<Block {self.name!r} blocks={len(self.blocks)} "
                f"props={len(self.props)}>")


def _esc(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'")


class AedtDocument:
    """A parsed ``.aedt`` project file."""

    def __init__(self, roots: List[AedtNode], encoding: str = "utf-8",
                 newline: str = "\n", source: Optional[str] = None):
        self.roots = roots
        self.encoding = encoding
        self.newline = newline
        self.source = source
        #: repairs made while parsing a damaged file, empty for a clean one
        self.issues: List[str] = []

    # ---- IO --------------------------------------------------------------
    @classmethod
    def parse(cls, path: str) -> "AedtDocument":
        text, enc, nl = read_text(path)
        doc = cls.parse_text(text)
        doc.encoding, doc.newline, doc.source = enc, nl, path
        for msg in doc.issues:
            log.warning("%s: %s", os.path.basename(path), msg)
        return doc

    @classmethod
    def parse_text(cls, text: str, strict: bool = False) -> "AedtDocument":
        """
        Parse a project document.

        Tolerant by default. A project file is written by someone else's
        software, and a block that does not close, or an ``$end`` that names
        the wrong block, is a reason to note the damage and keep reading --
        not to hand back nothing. Every repair is recorded in ``issues`` so it
        can be reported; ``strict=True`` restores the old behaviour of raising,
        which is what the round-trip tests want.
        """
        lines = split_logical(text)
        roots: List[AedtNode] = []
        stack: List[AedtBlock] = []
        issues: List[str] = []
        for ll in lines:
            target = stack[-1].children if stack else roots
            if ll.kind == "begin":
                blk = AedtBlock(ll.block_name or "", raw_begin=ll.raw)
                blk.parent = stack[-1] if stack else None
                target.append(blk)
                stack.append(blk)
            elif ll.kind == "end":
                if not stack:
                    msg = (f"line {ll.lineno}: '$end {ll.block_name}' without "
                           "a matching '$begin'")
                    if strict:
                        raise ValueError(msg)
                    issues.append(msg)
                    node = AedtProp(None, ll.text, raw=ll.raw)
                    (stack[-1].children if stack else roots).append(node)
                    continue
                if stack[-1].name != ll.block_name:
                    # Close the innermost block this '$end' actually names, if
                    # any: a missing '$end' in between is the usual cause, and
                    # unwinding to it keeps the rest of the file readable.
                    depth = next((k for k in range(len(stack) - 1, -1, -1)
                                  if stack[k].name == ll.block_name), None)
                    msg = (f"line {ll.lineno}: '$end {ll.block_name}' closes "
                           f"'$begin {stack[-1].name}'")
                    if strict or depth is None:
                        if strict:
                            raise ValueError(msg)
                        issues.append(msg + " (kept as text)")
                        node = AedtProp(None, ll.text, raw=ll.raw)
                        stack[-1].children.append(node)
                        continue
                    issues.append(msg + "; unwound to it")
                    del stack[depth + 1:]
                blk = stack.pop()
                blk.raw_end = ll.raw
            elif ll.kind == "binary":
                head, _, payload = ll.raw.partition("\n")
                node = AedtBinary(head, payload)
                node.parent = stack[-1] if stack else None
                target.append(node)
            else:
                if not ll.text:
                    node = AedtProp(None, "", raw=ll.raw, blank=True)
                else:
                    key, val = parse_statement(ll.text)
                    node = AedtProp(key, val, raw=ll.raw)
                node.parent = stack[-1] if stack else None
                target.append(node)
        if stack:
            msg = ("unterminated block(s): "
                   + ", ".join(repr(b.name) for b in stack[:4]))
            if strict:
                raise ValueError(msg)
            issues.append(msg + " -- closed at end of file")
        doc = cls(roots)
        doc.issues = issues
        return doc

    def to_text(self) -> str:
        out: List[str] = []
        for r in self.roots:
            out.extend(r.render(0))
        return self.newline.join(out)

    def write(self, path: str, encoding: Optional[str] = None) -> str:
        text = self.to_text()
        import tempfile
        import shutil
        target = os.path.abspath(path)
        suffix = os.path.splitext(target)[1]
        fd, temp = tempfile.mkstemp(prefix=".aether-", suffix=suffix,
                                    dir=os.path.dirname(target))
        os.close(fd)
        try:
            if target.lower().endswith(".aedtz"):
                from .archive import write_aedtz
                write_aedtz(temp, text, encoding or self.encoding or "utf-8",
                            member=os.path.splitext(os.path.basename(target))[0] + ".aedt",
                            cad_folder=os.path.splitext(target)[0] + ".cad")
            else:
                with open(temp, "wb") as fh:
                    fh.write(text.encode(encoding or self.encoding or "utf-8"))
                    fh.flush()
                    os.fsync(fh.fileno())
            if os.path.isfile(target):
                shutil.copy2(target, target + ".bak")
            os.replace(temp, target)
        finally:
            if os.path.exists(temp):
                os.unlink(temp)
        return path

    # ---- navigation ------------------------------------------------------
    @property
    def root(self) -> AedtBlock:
        for r in self.roots:
            if isinstance(r, AedtBlock):
                return r
        raise ValueError("document contains no block")

    def find(self, name: str) -> List[AedtBlock]:
        out: List[AedtBlock] = []
        for r in self.roots:
            if isinstance(r, AedtBlock):
                if r.name == name:
                    out.append(r)
                out.extend(r.find(name))
        return out

    # AEDT names the design block after the solver that owns it. Projects
    # written by the desktop use 'HFSSModel'; a design exported or scripted on
    # its own uses the generic 'Design'. Both appear in the wild, and a reader
    # that knows only one of them finds no designs at all in half the files it
    # is given.
    DESIGN_BLOCKS = ("Design", "HFSSModel", "HFSSDesign")

    def designs(self) -> List[AedtBlock]:
        """Every design block, whatever the writing version called it."""
        out: List[AedtBlock] = []
        seen = set()
        for nm in self.DESIGN_BLOCKS:
            for d in self.find(nm):
                if id(d) not in seen:
                    seen.add(id(d))
                    out.append(d)
        return out

    def hfss_designs(self) -> List[AedtBlock]:
        out = []
        for d in self.designs():
            t = str(d.get("DesignType", "") or "")
            if d.name in ("HFSSModel", "HFSSDesign") or "HFSS" in t \
                    or d.block("HfssEnums") is not None \
                    or d.block("ModelSetup") is not None:
                out.append(d)
        return out

    def __repr__(self):
        return (f"<AedtDocument {os.path.basename(self.source or '<text>')!r} "
                f"designs={len(self.designs())}>")


__all__ = ["AedtDocument", "AedtBlock", "AedtProp", "AedtBinary", "AedtNode", "Call",
           "Counted"]

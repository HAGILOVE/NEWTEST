"""
Session state for the Aether Desktop workspace.

Holds the live :class:`~aether.model.Project`, the message log that feeds the
Message Manager, and the background solve job. Everything the browser sees is
derived from these objects, so the GUI and the scripting console always agree
— there is no second copy of the model.
"""
from __future__ import annotations

import io
import logging
import threading
import time
import traceback
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

import numpy as np

from ..core.logging import get_logger
from ..model import Design, Project

log = get_logger("gui.state")

SEVERITY = {logging.DEBUG: "info", logging.INFO: "info",
            logging.WARNING: "warning", logging.ERROR: "error",
            logging.CRITICAL: "error"}


class MessageLog:
    """Ring buffer behind the Message Manager panel."""

    def __init__(self, limit: int = 4000):
        self._items: List[dict] = []
        self._limit = limit
        self._lock = threading.Lock()
        self._seq = 0

    def add(self, text: str, severity: str = "info", source: str = "") -> None:
        with self._lock:
            self._seq += 1
            self._items.append({
                "id": self._seq, "t": time.strftime("%H:%M:%S"),
                "severity": severity, "source": source, "text": str(text)})
            if len(self._items) > self._limit:
                del self._items[:len(self._items) - self._limit]

    def since(self, seq: int) -> List[dict]:
        with self._lock:
            return [m for m in self._items if m["id"] > seq]

    @property
    def seq(self) -> int:
        return self._seq

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class _LogBridge(logging.Handler):
    """Routes solver logging into the Message Manager."""

    def __init__(self, msgs: MessageLog):
        super().__init__(logging.INFO)
        self.msgs = msgs

    def emit(self, record: logging.LogRecord) -> None:
        try:
            src = record.name.replace("aether.", "")
            self.msgs.add(record.getMessage(), SEVERITY.get(record.levelno,
                                                            "info"), src)
        except Exception:                       # pragma: no cover
            pass


class Progress:
    """
    What a long-running command is doing right now.

    Opening a project, importing a CAD assembly and rebuilding the display
    buffers all take seconds to minutes on a real model. Without a published
    stage the workspace simply looks frozen, so every one of those operations
    now pushes its stage here and the browser renders it — the same contract
    the solve job already had, generalised to file and display work.

    The object is read by the message poller, which runs on its own request
    and therefore keeps ticking while the command holds the session lock.
    """

    def __init__(self):
        self._lock = threading.Lock()
        self.active = False
        self.label = ""
        self.stage = ""
        self.detail = ""
        self.done = 0
        self.total = 0
        self.started = 0.0
        self.finished = 0.0
        self.error = ""
        self.seq = 0
        self.cancel = threading.Event()

    # -- writing -------------------------------------------------------
    def begin(self, label: str, total: int = 0, stage: str = "") -> None:
        with self._lock:
            self.active = True
            self.label = str(label)
            self.stage = str(stage)
            self.detail = ""
            self.done = 0
            self.total = int(total)
            self.started = time.time()
            self.finished = 0.0
            self.error = ""
            self.seq += 1
            self.cancel.clear()

    def step(self, stage: str = "", detail: str = "", done: Optional[int] = None,
             total: Optional[int] = None, advance: int = 0) -> None:
        with self._lock:
            if not self.active:
                return
            if stage:
                self.stage = str(stage)
            if detail:
                self.detail = str(detail)
            if total is not None:
                self.total = int(total)
            if done is not None:
                self.done = int(done)
            elif advance:
                self.done += int(advance)
            self.seq += 1

    def end(self, error: str = "") -> None:
        with self._lock:
            self.active = False
            self.error = str(error or "")
            self.finished = time.time()
            self.seq += 1

    def cancelled(self) -> bool:
        return self.cancel.is_set()

    def request_cancel(self) -> None:
        self.cancel.set()

    # -- reading -------------------------------------------------------
    def to_json(self) -> dict:
        with self._lock:
            elapsed = ((self.finished or time.time()) - self.started
                       if self.started else 0.0)
            frac = (min(1.0, self.done / self.total) if self.total > 0
                    else (0.0 if self.active else 1.0))
            return {"active": self.active, "label": self.label,
                    "stage": self.stage, "detail": self.detail,
                    "done": self.done, "total": self.total,
                    "fraction": round(frac, 4), "error": self.error,
                    "elapsed": round(max(elapsed, 0.0), 2), "seq": self.seq}


@dataclass
class SolveJob:
    """A running (or finished) analysis."""
    setup: str = ""
    running: bool = False
    done: bool = False
    error: str = ""
    started: float = 0.0
    finished: float = 0.0
    pass_no: int = 0
    total_passes: int = 0
    freq_done: int = 0
    freq_total: int = 0
    partial_points: int = 0
    stage: str = ""

    @property
    def elapsed(self) -> float:
        end = self.finished if self.done else time.time()
        return max(end - self.started, 0.0) if self.started else 0.0

    def to_json(self) -> dict:
        return {"setup": self.setup, "running": self.running,
                "done": self.done, "error": self.error,
                "elapsed": round(self.elapsed, 2), "stage": self.stage,
                "pass": self.pass_no, "totalPasses": self.total_passes,
                "freqDone": self.freq_done, "freqTotal": self.freq_total}


class Session:
    """Everything one browser tab is looking at."""

    def __init__(self):
        self.project = Project("Project1")
        self.design: Optional[Design] = None
        self.messages = MessageLog()
        self.job = SolveJob()
        self.progress = Progress()
        # True while a project is open. Closing one leaves the workspace with
        # no document at all -- the state HFSS shows between projects -- rather
        # than silently creating a new empty one.
        self.project_open = True
        #: set by :func:`aether.gui.server.serve` so File ▸ Exit can stop it
        self.server = None
        self.cancel_event = threading.Event()
        self.study_results = []
        self.study_spec = {}
        self.opt_results = {}
        self.solution = None
        self.solution_serial = 0
        self.selection: List[str] = []
        # Face and edge picks, alongside the object selection. A face pick is
        # {"object": name, "face": index, "point": [x, y, z],
        #  "normal": [..], "lo": [..], "hi": [..], "area": m2}: the index alone
        # would not survive a re-tessellation, so the geometry that identifies
        # the face travels with it and every assignment is built from that.
        self.sel_faces: List[dict] = []
        self.sel_edges: List[dict] = []
        self.select_mode: str = "object"       # object | face | edge
        self.project_path: str = ""
        self.dirty = False
        self.view = {"mode": "shaded", "showMesh": False, "showField": False}
        self.clipboard: List[dict] = []
        self._undo: List[tuple] = []          # (design name, snapshot)
        self._redo: List[tuple] = []
        self.undo_limit = 40
        self._lock = threading.RLock()
        self._bridge = _LogBridge(self.messages)
        logging.getLogger("aether").addHandler(self._bridge)
        self.messages.add("Aether Desktop ready.", "info", "desktop")

    # ------------------------------------------------------------------
    def new_project(self, name: str = "Project1") -> Design:
        with self._lock:
            self.study_results = []; self.study_spec = {}; self.opt_results = {}
            self.project = Project(name)
            self._undo.clear()
            self._redo.clear()
            self.clipboard = []
            self.solution = None
            self.project_path = ""
            self.selection = []
            self.sel_faces = []
            self.sel_edges = []
            d = self.project.new_design("HFSSDesign1")
            self.design = d
            self.dirty = False
            self.project_open = True
            self.messages.add(f"Created project {name!r}.", "info", "desktop")
            return d

    def close_project(self) -> None:
        """
        Close the open document and leave the workspace empty.

        Everything scoped to the document goes with it: history, clipboard,
        picks, solution and study results. Nothing is written to disk here —
        deciding whether unsaved work should be saved first is the caller's
        job, and the UI asks before it calls.
        """
        with self._lock:
            name = self.project.name
            self.study_results = []
            self.study_spec = {}
            self.project = Project("Project1")
            self.design = None
            self._undo.clear()
            self._redo.clear()
            self.clipboard = []
            self.solution = None
            self.project_path = ""
            self.clear_picks()
            self.dirty = False
            self.project_open = False
            self.job = SolveJob()
            self.messages.add(f"Closed project {name!r}.", "info", "desktop")

    def insert_design(self, name: str = "", solution_type: str = "driven_modal"):
        with self._lock:
            n = name or f"HFSSDesign{len(self.project) + 1}"
            d = self.project.new_design(n, solution_type=solution_type)
            self.design = d
            self.dirty = True
            self.messages.add(f"Inserted design {n!r} ({solution_type}).",
                              "info", "desktop")
            return d

    def require_design(self) -> Design:
        if self.design is None:
            raise RuntimeError("no design is open — use Project ▸ Insert Design")
        return self.design

    # ---------------------------------------------------------- history
    def push_undo(self, label: str = "") -> None:
        """Record the model before an edit. Called for every mutating command."""
        d = self.design
        if d is None:
            return
        with self._lock:
            self._undo.append((d.name, label, d.snapshot()))
            if len(self._undo) > self.undo_limit:
                self._undo.pop(0)
            self._redo.clear()

    def clear_picks(self) -> None:
        """Drop every selection: objects, faces and edges."""
        self.selection = []
        self.sel_faces = []
        self.sel_edges = []

    def undo(self) -> str:
        with self._lock:
            if not self._undo:
                raise RuntimeError("nothing to undo")
            name, label, snap = self._undo.pop()
            d = self.project[name] if name in [x.name for x in
                                               self.project.designs] else self.design
            if d is None:
                raise RuntimeError("the design this edit belongs to is gone")
            self._redo.append((d.name, label, d.snapshot()))
            d.restore(snap)
            self.design = d
            self.solution = None
            self.clear_picks()
            self.study_results = []; self.study_spec = {}
            self.dirty = True
        self.messages.add(f"Undo{': ' + label if label else ''}.", "info",
                          "edit")
        return label

    def redo(self) -> str:
        with self._lock:
            if not self._redo:
                raise RuntimeError("nothing to redo")
            name, label, snap = self._redo.pop()
            d = self.project[name] if name in [x.name for x in
                                               self.project.designs] else self.design
            self._undo.append((d.name, label, d.snapshot()))
            d.restore(snap)
            self.design = d
            self.solution = None
            self.clear_picks()
            self.study_results = []; self.study_spec = {}
            self.dirty = True
        self.messages.add(f"Redo{': ' + label if label else ''}.", "info",
                          "edit")
        return label

    @property
    def can_undo(self) -> bool:
        return bool(self._undo)

    @property
    def can_redo(self) -> bool:
        return bool(self._redo)

    def undo_label(self) -> str:
        return self._undo[-1][1] if self._undo else ""

    def redo_label(self) -> str:
        return self._redo[-1][1] if self._redo else ""

    # ------------------------------------------------------------------
    def start_solve(self, setup_name: str = "", **kw) -> None:
        with self._lock:
            if self.job.running:
                raise RuntimeError("an analysis is already running")
            d = self.require_design()
            errs = d.validate()
            if errs:
                raise RuntimeError("validation failed: " + "; ".join(errs))
            st = d.get_setup(setup_name or None)
            self.cancel_event.clear()
            self.solution = None
            self.solution_serial += 1
            self.job = SolveJob(setup=st.name, running=True,
                                started=time.time(),
                                total_passes=st.max_passes,
                                freq_total=int(sum(
                                    len(s.frequencies()) if s.kind == "discrete"
                                    else min(len(s.frequencies()),
                                             s.max_points or d.config.sweep.interp_max_points)
                                    for s in st.sweeps)) or 1,
                                stage="meshing")
        t = threading.Thread(target=self._solve_worker,
                             args=(setup_name, kw, d), daemon=True)
        t.start()

    def _publish_partial(self, part) -> None:
        """Make an in-progress snapshot the current solution, so every Results
        command works while the analysis is still running. Plain reference
        assignment: readers see either the old or the new snapshot."""
        self.solution = part
        self.solution_serial += 1
        self.job.partial_points = int(len(part.freqs))

    def _solve_worker(self, setup_name, kw, d):
        try:
            self.messages.add(f"Analysis started for {self.job.setup!r}.",
                              "info", "analysis")
            probe = _ProgressProbe(self.job)
            logging.getLogger("aether").addHandler(probe)
            try:
                sol = d.solve(setup=setup_name or None, cancel=self.cancel_event,
                              on_partial=self._publish_partial, **kw)
            finally:
                logging.getLogger("aether").removeHandler(probe)
            with self._lock:
                self.solution = sol
                self.solution_serial += 1
                self.job.running = False
                self.job.done = True
                self.job.finished = time.time()
                self.job.stage = "complete"
            if sol.modes:
                self.messages.add(
                    f"Analysis complete in {self.job.elapsed:.1f} s "
                    f"({len(sol.modes)} eigenmode(s): "
                    + ", ".join(f"{m.f / 1e9:.4f} GHz" for m in sol.modes[:6])
                    + ").", "info", "analysis")
            else:
                self.messages.add(
                    f"Analysis complete in {self.job.elapsed:.1f} s "
                    f"({sol.sparams.n_freq} frequency points).", "info",
                    "analysis")
            for si in sol.sweep_info:
                if si.get("requested", "discrete") == "discrete":
                    continue
                note = (f"Sweep {si.get('name', '')!r} ({si['kind']}): "
                        f"{si['solved']} full solve(s) reconstructed "
                        f"{si['points']} points")
                if si["kind"] != si["requested"]:
                    note = (f"Sweep {si.get('name', '')!r}: only {si['points']} "
                            f"point(s), solved directly instead of {si['requested']}")
                self.messages.add(note + ".", "info", "analysis")
        except Exception as exc:                 # pragma: no cover - surfaced in UI
            with self._lock:
                self.job.running = False
                self.job.done = True
                self.job.error = str(exc)
                self.job.finished = time.time()
                from ..fem.control import SolveCancelled
                self.job.stage = "cancelled" if isinstance(exc, SolveCancelled) else "failed"
            self.messages.add(f"Analysis failed: {exc}", "error", "analysis")
            if getattr(self.solution, "partial", False):
                self.messages.add("The results computed before it stopped "
                                  "are still available in Results.", "info",
                                  "analysis")
            log.debug("solve traceback:\n%s", traceback.format_exc())


class _ProgressProbe(logging.Handler):
    """Turns solver log lines into progress-bar state."""

    def __init__(self, job: SolveJob):
        super().__init__(logging.INFO)
        self.job = job

    def emit(self, record):
        try:
            m = record.getMessage()
            if m.startswith("adaptive pass"):
                self.job.stage = "adaptive"
                self.job.pass_no = int(m.split()[2].rstrip(":"))
            elif m.startswith("tetrahedral meshing"):
                self.job.stage = "meshing"
            elif m.lstrip().startswith("f ="):
                self.job.stage = "sweep"
                self.job.freq_done += 1
            elif "frequency sweep" in m and "done" not in m:
                self.job.stage = "sweep"
                self.job.freq_done = 0
        except Exception:
            pass

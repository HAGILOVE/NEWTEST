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
import re
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
    #: "solve" (this module), "study" or "optimization" (engineering.py)
    kind: str = "solve"
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
    #: last solver message -- what it is doing right now
    detail: str = ""
    #: "process" (isolated, killable) or "thread"
    mode: str = "thread"
    pid: int = 0
    threads: int = 0
    #: unknowns in the current linear system / the factorisation backend
    dofs: int = 0
    backend: str = ""
    tets: int = 0
    #: user asked to stop / abort; the solver is winding down
    stopping: bool = False
    aborting: bool = False
    #: seconds spent per stage ("meshing", "adaptive", "sweep", ...)
    phases: Dict[str, float] = field(default_factory=dict)
    stage_since: float = 0.0
    #: how the run ended: complete / stopped / aborted / failed
    outcome: str = ""

    def enter_stage(self, name: str) -> None:
        now = time.time()
        if self.stage and self.stage_since and self.stage != name:
            self.phases[self.stage] = (self.phases.get(self.stage, 0.0)
                                       + now - self.stage_since)
        if self.stage != name or not self.stage_since:
            self.stage_since = now
        self.stage = name

    def phase_times(self) -> Dict[str, float]:
        out = dict(self.phases)
        if self.running and self.stage and self.stage_since:
            out[self.stage] = out.get(self.stage, 0.0) + time.time() - self.stage_since
        return {k: round(v, 1) for k, v in out.items()}

    @property
    def elapsed(self) -> float:
        end = self.finished if self.done else time.time()
        return max(end - self.started, 0.0) if self.started else 0.0

    def to_json(self) -> dict:
        return {"setup": self.setup, "kind": self.kind, "running": self.running,
                "done": self.done, "error": self.error,
                "elapsed": round(self.elapsed, 2), "stage": self.stage,
                "pass": self.pass_no, "totalPasses": self.total_passes,
                "freqDone": self.freq_done, "freqTotal": self.freq_total,
                "detail": self.detail, "mode": self.mode, "pid": self.pid,
                "threads": self.threads, "dofs": self.dofs,
                "backend": self.backend, "tets": self.tets,
                "stopping": self.stopping, "aborting": self.aborting,
                "phases": self.phase_times(), "outcome": self.outcome,
                "partialPoints": self.partial_points}


class Session:
    """Everything one browser tab is looking at."""

    def __init__(self):
        self.project = Project("Project1")
        self.design: Optional[Design] = None
        self.messages = MessageLog()
        self.job = SolveJob()
        self.progress = Progress()
        # True while a project is open. Closing one leaves the workspace with
        # no document at all -- the state Warps shows between projects -- rather
        # than silently creating a new empty one.
        self.project_open = True
        #: set by :func:`aether.gui.server.serve` so File ▸ Exit can stop it
        self.server = None
        self.cancel_event = threading.Event()
        #: the running isolated solver (aether.gui.worker.SolverProcess)
        self.solver = None
        #: how analyses run: solver threads (0 = automatic) and whether to use
        #: the isolated low-priority process
        self.perf = {"threads": 0, "isolate": True}
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
            d = self.project.new_design("WarpsDesign1")
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
            n = name or f"WarpsDesign{len(self.project) + 1}"
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
            # a fresh event per run: an aborted thread-mode solve that is still
            # unwinding must not be revived by the next run clearing its flag
            self.cancel_event = threading.Event()
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
                                stage="meshing", stage_since=time.time(),
                                mode=("process" if self._spawnable() else "thread"))
        t = threading.Thread(target=self._solve_worker,
                             args=(setup_name, kw, d, self.job,
                                   self.cancel_event), daemon=True)
        t.start()

    def _publish_partial(self, part) -> None:
        """Make an in-progress snapshot the current solution, so every Results
        command works while the analysis is still running. Plain reference
        assignment: readers see either the old or the new snapshot."""
        self.solution = part
        self.solution_serial += 1
        self.job.partial_points = int(len(part.freqs))

    # -- stopping ---------------------------------------------------------
    def request_stop(self) -> bool:
        """Finish the current step, then end the analysis keeping the
        results computed so far. Returns False when nothing is running."""
        with self._lock:
            if not self.job.running:
                return False
            self.job.stopping = True
        self.cancel_event.set()
        sp = self.solver
        if sp is not None:
            sp.stop()
        return True

    def request_abort(self) -> bool:
        """End the analysis *now*. A solver process is terminated; a solve
        running inside this process (thread mode) cannot be killed, so it is
        cancelled and detached -- its late result is discarded."""
        with self._lock:
            if not self.job.running:
                return False
            self.job.stopping = True
            self.job.aborting = True
        self.cancel_event.set()
        sp = self.solver
        if sp is not None:
            sp.abort()
        elif self.job.kind == "solve" and self.job.mode != "process":
            self._finish_stopped("aborted", "", self.job)
        elif self.job.kind != "solve":
            self.job.aborting = False       # a study ends after its current solve
        return True

    # -- the worker -------------------------------------------------------
    def _solve_worker(self, setup_name, kw, d, job, cancel):
        from . import worker
        self.messages.add(f"Analysis started for {self.job.setup!r}.",
                          "info", "analysis")
        probe = _ProgressProbe(job)
        use_proc = self._spawnable()
        if use_proc:
            try:
                self._run_in_process(worker, probe, setup_name, kw, d, job)
                return
            except _FallBack as why:
                self.messages.add(
                    f"Could not start the isolated solver process ({why}); "
                    "running inside the application instead.",
                    "warning", "analysis")
        self._run_in_thread(probe, setup_name, kw, d, job, cancel)

    def _run_in_process(self, worker, probe, setup_name, kw, d, job):
        job.mode = "process"
        job.threads = worker.default_threads(override=self.perf.get("threads", 0))
        if job.aborting:            # abort pressed before the process existed
            self._finish_stopped("aborted", "", job)
            return
        runner = worker.SolverProcess(
            d, setup_name, kw,
            on_log=lambda lvl, name, msg: self._on_solver_log(probe, lvl, name, msg),
            on_partial=lambda part: self._on_process_partial(d, part),
            threads=job.threads)
        self.solver = runner
        if job.aborting:            # abort pressed while it was being set up
            runner.abort()
        try:
            try:
                status, sol, message = runner.run()
            except Exception as exc:
                if runner.pid:
                    status, sol, message = "error", None, f"{type(exc).__name__}: {exc}"
                else:
                    raise _FallBack(exc)
        finally:
            self.solver = None
        if status == "done" and sol is not None:
            sol.design = d
            d.mesh = sol.mesh
            self._finish_ok(sol, job)
            return
        if sol is not None:
            sol.design = d
            d.mesh = sol.mesh
            sol.partial = True
            self.solution = sol
            self.solution_serial += 1
            job.partial_points = int(len(sol.freqs))
        self._finish_stopped(status, message, job)

    def _spawnable(self) -> bool:
        try:
            from . import worker
            return bool(self.perf.get("isolate", True)) and worker.can_spawn()
        except Exception:
            return False

    def _on_solver_log(self, probe, level, name, message) -> None:
        logging.getLogger(name).log(level, message)
        probe.feed(message)

    def _on_process_partial(self, d, part) -> None:
        part.design = d
        d.mesh = part.mesh
        self._publish_partial(part)

    def _run_in_thread(self, probe, setup_name, kw, d, job, cancel):
        job.mode = "thread"
        from . import worker
        job.threads = worker.default_threads(override=self.perf.get("threads", 0))
        worker.limit_native_threads(job.threads)

        def partial(part):
            if not job.aborting:     # a detached run must not touch the session
                self._publish_partial(part)
        try:
            logging.getLogger("aether").addHandler(probe)
            try:
                sol = d.solve(setup=setup_name or None, cancel=cancel,
                              on_partial=partial, **kw)
            finally:
                logging.getLogger("aether").removeHandler(probe)
            if job.aborting:        # detached: the user already walked away
                return
            self._finish_ok(sol, job)
        except Exception as exc:                 # pragma: no cover - surfaced in UI
            from ..fem.control import SolveCancelled
            if job.aborting:
                return
            status = "cancelled" if isinstance(exc, SolveCancelled) else "error"
            self._finish_stopped(status, str(exc), job)
            log.debug("solve traceback:\n%s", traceback.format_exc())

    def _finish_ok(self, sol, job) -> None:
        with self._lock:
            self.solution = sol
            self.solution_serial += 1
            job.running = False
            job.done = True
            job.finished = time.time()
            job.enter_stage("complete")
            job.outcome = "complete"
            job.stopping = False
        if sol.modes:
            self.messages.add(
                f"Analysis complete in {job.elapsed:.1f} s "
                f"({len(sol.modes)} eigenmode(s): "
                + ", ".join(f"{m.f / 1e9:.4f} GHz" for m in sol.modes[:6])
                + ").", "info", "analysis")
        else:
            self.messages.add(
                f"Analysis complete in {job.elapsed:.1f} s "
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

    def _finish_stopped(self, status: str, message: str, job) -> None:
        """The analysis ended without a full result: stopped, aborted, failed."""
        with self._lock:
            if job.done:
                return
            job.running = False
            job.done = True
            job.finished = time.time()
            job.stopping = False
            if status == "aborted" or job.aborting:
                job.outcome = "aborted"
                job.enter_stage("aborted")
                job.error = "Aborted by the user."
            elif status == "cancelled":
                job.outcome = "stopped"
                job.enter_stage("cancelled")
                job.error = "Stopped by the user."
            else:
                job.outcome = "failed"
                job.enter_stage("failed")
                job.error = message
        kept = getattr(self.solution, "partial", False)
        if job.outcome == "failed":
            self.messages.add(f"Analysis failed: {message}", "error", "analysis")
        elif job.outcome == "aborted":
            self.messages.add(
                f"Analysis aborted after {job.elapsed:.1f} s.", "warning",
                "analysis")
        else:
            self.messages.add(
                f"Analysis stopped after {job.elapsed:.1f} s.", "warning",
                "analysis")
        if kept:
            n = job.partial_points
            self.messages.add(
                "The results computed before it ended are still available in "
                f"Results ({n} frequency point{'s' if n != 1 else ''}).",
                "info", "analysis")


class _FallBack(RuntimeError):
    """The isolated solver process could not be started."""


class _ProgressProbe(logging.Handler):
    """Turns solver log lines into progress-bar state."""

    def __init__(self, job: SolveJob):
        super().__init__(logging.INFO)
        self.job = job

    def emit(self, record):
        try:
            self.feed(record.getMessage())
        except Exception:
            pass

    def feed(self, m: str) -> None:
        job = self.job
        try:
            if m.startswith("adaptive pass"):
                job.enter_stage("adaptive")
                job.pass_no = int(m.split()[2].rstrip(":"))
                mt = re.search(r"(\d+) tets", m)
                if mt:
                    job.tets = int(mt.group(1))
            elif m.startswith("tetrahedral meshing") and not m.endswith("..."):
                pass
            elif m.startswith("tetrahedral meshing"):
                job.enter_stage("meshing")
            elif m.lstrip().startswith("f ="):
                job.enter_stage("sweep")
                job.freq_done += 1
            elif "frequency sweep" in m and "done" not in m:
                job.enter_stage("sweep")
                job.freq_done = 0
            elif m.startswith("linear solver ready"):
                mb = re.search(r"\[([^,\]]+), n=(\d+)", m)
                if mb:
                    job.backend, job.dofs = mb.group(1), int(mb.group(2))
            if m.strip():
                job.detail = m.strip()[:160]
        except Exception:
            pass



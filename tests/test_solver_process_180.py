"""The analysis runs in its own low-priority process and can be stopped or
aborted -- the fix for "the simulation freezes the PC and cannot be ended"."""
import os
import pickle
import time

import numpy as np
import pytest

from conftest import needs_occ
from test_sweep_180 import guide

pytestmark = [needs_occ, pytest.mark.slow]


def session_with(design):
    from aether.gui.state import Session
    s = Session()
    s.new_project("G")
    s.project.designs[0] = design
    s.design = design
    return s


def wait(s, timeout=120.0):
    t_end = time.time() + timeout
    while s.job.running and time.time() < t_end:
        time.sleep(0.05)
    assert not s.job.running, "the job never finished"


def long_design(n=400):
    return guide("discrete", "8GHz", "12GHz", n)


def test_a_solution_survives_pickling():
    sol = guide("discrete", "9GHz", "11GHz", 3).solve(
        adaptive=False, progress=False, save_fields=True)
    back = pickle.loads(pickle.dumps(sol))
    np.testing.assert_allclose(back.sparams.s, sol.sparams.s)
    k = next(iter(back.fields))
    assert back.fields[k].eps_of_region(1) == 1.0 + 0j


def test_the_solve_runs_in_a_separate_process_with_the_same_answer():
    d = guide("discrete", "9GHz", "11GHz", 5)
    ref = d.solve(adaptive=False, progress=False)
    s = session_with(d)
    s.start_solve("S1", adaptive=False)
    wait(s)
    j = s.job
    assert j.mode == "process" and j.outcome == "complete" and not j.error
    assert j.threads >= 1 and j.dofs > 0
    np.testing.assert_allclose(s.solution.sparams.s, ref.sparams.s, atol=1e-12)
    assert s.solution.design is d and d.mesh is s.solution.mesh
    assert j.phases and "meshing" in j.phases


def test_stop_ends_the_run_and_keeps_the_points_solved_so_far():
    s = session_with(long_design())
    s.start_solve("S1", adaptive=False)
    t_end = time.time() + 120
    while time.time() < t_end and not (s.solution is not None
                                       and s.job.partial_points >= 2):
        time.sleep(0.05)
    assert s.request_stop() is True
    assert s.job.stopping
    wait(s)
    j = s.job
    assert j.outcome == "stopped" and j.stage == "cancelled"
    assert "Stopped" in j.error
    assert s.solution is not None and s.solution.partial
    assert 2 <= len(s.solution.freqs) < 400
    # a stopped run is not "failed"
    assert not any(m["severity"] == "error" for m in s.messages.since(0)
                   if "Analysis" in m["text"])


def test_abort_kills_the_process_at_once():
    s = session_with(long_design())
    s.start_solve("S1", adaptive=False)
    t_end = time.time() + 60
    while time.time() < t_end and not (s.solver and s.solver.pid
                                       and s.job.partial_points >= 1):
        time.sleep(0.05)
    pid = s.solver.pid
    t0 = time.time()
    assert s.request_abort() is True
    wait(s, 20)
    assert time.time() - t0 < 8
    assert s.job.outcome == "aborted" and s.job.stage == "aborted"
    assert s.solver is None
    with pytest.raises(OSError):
        os.kill(pid, 0) if os.name != "nt" else (_ for _ in ()).throw(OSError())
    # the session is usable again straight away
    s.design.setups[0].sweeps[0].count = 3
    s.start_solve("S1", adaptive=False)
    wait(s)
    assert s.job.outcome == "complete"


def test_temp_files_are_removed_after_every_ending():
    import glob
    import tempfile
    before = set(glob.glob(os.path.join(tempfile.gettempdir(), "aether-solve-*")))
    s = session_with(long_design(200))
    s.start_solve("S1", adaptive=False)
    time.sleep(2.0)
    s.request_abort()
    wait(s, 20)
    after = set(glob.glob(os.path.join(tempfile.gettempdir(), "aether-solve-*")))
    assert after <= before


def test_a_solver_that_dies_is_reported_not_hung():
    import signal
    if os.name == "nt":
        pytest.skip("POSIX signals")
    s = session_with(long_design())
    s.start_solve("S1", adaptive=False)
    t_end = time.time() + 60
    while time.time() < t_end and not (s.solver and s.job.partial_points >= 1):
        time.sleep(0.05)
    os.kill(s.solver.pid, signal.SIGKILL)          # e.g. the OOM killer
    wait(s, 20)
    assert s.job.outcome == "failed"
    assert "unexpectedly" in s.job.error
    assert s.solution is not None and s.solution.partial   # what it had is kept


def test_thread_mode_abort_detaches_immediately(monkeypatch):
    monkeypatch.setenv("AETHER_SOLVER_MODE", "thread")
    s = session_with(long_design())
    s.start_solve("S1", adaptive=False)
    time.sleep(1.0)
    assert s.job.mode == "thread"
    assert s.request_abort() is True
    assert not s.job.running and s.job.outcome == "aborted"
    time.sleep(1.5)                 # the orphan unwinds without touching the job
    assert s.job.outcome == "aborted"


def test_falls_back_to_the_thread_when_the_process_cannot_start(monkeypatch):
    from aether.gui import worker

    def boom(self):
        raise OSError("no process for you")
    monkeypatch.setattr(worker.SolverProcess, "run", boom)
    s = session_with(guide("discrete", "9GHz", "11GHz", 3))
    s.start_solve("S1", adaptive=False)
    wait(s)
    assert s.job.mode == "thread" and s.job.outcome == "complete"
    assert any("running inside the application" in m["text"]
               for m in s.messages.since(0))


def test_thread_limits(monkeypatch):
    from aether.gui import worker
    monkeypatch.delenv(worker.THREADS_ENV, raising=False)
    assert worker.default_threads(2) == 1
    assert worker.default_threads(4) == 3
    assert worker.default_threads(8) == 6
    assert worker.default_threads(64) == 16
    monkeypatch.setenv(worker.THREADS_ENV, "5")
    assert worker.default_threads(64) == 5
    env = worker.thread_env(3)
    assert env["MKL_NUM_THREADS"] == "3" and env["OMP_WAIT_POLICY"] == "PASSIVE"


def test_commands_report_when_nothing_is_running():
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    s = Session()
    assert dispatch(s, "analysis.cancel", {})["running"] is False
    assert dispatch(s, "analysis.abort", {})["running"] is False


def test_the_job_endpoint_is_light_and_lock_free():
    import json
    import urllib.request
    from aether.gui.server import serve
    srv, _, session = serve(port=8797, open_browser=False, token="",
                            block=False, template="waveguide")
    try:
        with session._lock:             # a long command holds the lock ...
            r = urllib.request.urlopen("http://127.0.0.1:8797/api/job", timeout=5)
            j = json.loads(r.read())    # ... and progress still answers
        assert set(j) >= {"job", "task", "serial", "hasSolution", "partial"}
        for k in ("stopping", "aborting", "detail", "phases", "mode", "outcome"):
            assert k in j["job"]
    finally:
        srv.shutdown()


def test_performance_settings_choose_threads_and_isolation():
    from aether.gui.api import dispatch
    d = guide("discrete", "9GHz", "11GHz", 3)
    s = session_with(d)
    info = dispatch(s, "analysis.performance", {})
    assert info["isolate"] is True and info["auto"] >= 1 and info["cpus"] >= 1
    dispatch(s, "analysis.setPerformance", {"threads": 2, "isolate": True})
    s.start_solve("S1", adaptive=False)
    wait(s)
    assert s.job.mode == "process" and s.job.threads == 2
    dispatch(s, "analysis.setPerformance", {"threads": 0, "isolate": False})
    s.start_solve("S1", adaptive=False)
    wait(s)
    assert s.job.mode == "thread" and s.job.outcome == "complete"
    with pytest.raises(ValueError):
        dispatch(s, "analysis.setPerformance", {"threads": 999})


def test_a_study_stops_cleanly_and_is_not_reported_as_failed():
    from aether.gui.api import dispatch
    d = guide("discrete", "9GHz", "11GHz", 3)
    d.variables["L"] = "30mm"
    s = session_with(d)
    # engineering workers run in a thread; Stop is cooperative there
    s.job = type(s.job)(kind="study", setup="Parameter study", running=True,
                        started=time.time())
    assert s.request_stop() is True
    assert s.job.stopping and s.cancel_event.is_set()
    assert s.request_abort() is True
    assert s.job.running and not s.job.aborting     # a study just stops

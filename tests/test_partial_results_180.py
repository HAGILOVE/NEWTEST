"""Results are available while an analysis is still running."""
import threading
import time

import numpy as np
import pytest

from conftest import needs_occ
from test_sweep_180 import guide

pytestmark = [needs_occ, pytest.mark.slow]


def test_each_solved_frequency_and_each_adaptive_pass_is_published():
    d = guide("discrete", "9GHz", "11GHz", 5)
    seen = []
    sol = d.solve(adaptive=False, progress=False, save_fields=True,
                  on_partial=lambda p: seen.append(p))
    assert len(seen) == 5                              # one per frequency
    assert all(p.partial for p in seen) and not sol.partial
    assert [len(p.freqs) for p in seen] == [1, 2, 3, 4, 5]
    # a snapshot is a usable solution: S-parameters and fields are there
    assert seen[1].sparams.s.shape == (2, 2, 2)
    assert len(seen[2].fields) == 3 * 2                # 2 excitations each
    np.testing.assert_allclose(seen[-1].sparams.s, sol.sparams.s, atol=1e-12)


def test_adaptive_passes_are_published_with_their_convergence():
    import aether as ae
    d = guide("discrete", "10GHz", "10GHz", 1)
    d.setups[0].max_passes = 3
    d.setups[0].min_passes = 3
    seen = []
    d.solve(adaptive=True, progress=False, on_partial=lambda p: seen.append(p))
    passes = [p for p in seen if len(p.freqs) == 1 and p.convergence]
    assert len(passes) >= 2
    assert [c["pass"] for c in passes[-1].convergence][:2] == [1, 2]


def test_a_session_shows_results_while_the_job_is_running():
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    s = Session()
    s.new_project("G")
    d = guide("discrete", "8GHz", "12GHz", 9)
    s.project.designs[0] = d
    s.design = d
    s.start_solve("S1", adaptive=False, save_fields=True)
    got = None
    t_end = time.time() + 120
    while time.time() < t_end and s.job.running:
        if s.solution is not None and getattr(s.solution, "partial", False):
            got = dispatch(s, "results.report", {})        # a live report
            break
        time.sleep(0.05)
    assert got is not None and got["freq"], "no partial results while running"
    n_partial = len(got["freq"])
    while s.job.running and time.time() < t_end:
        time.sleep(0.1)
    assert not s.job.error
    assert s.solution is not None and not s.solution.partial
    assert len(dispatch(s, "results.report", {})["freq"]) == 9 >= n_partial

"""A saved, solved project reopens with its solution: no second analysis."""
import os

import numpy as np
import pytest

from conftest import needs_occ

pytestmark = [needs_occ, pytest.mark.slow]


@pytest.fixture(scope="module")
def saved(tmp_path_factory):
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    from test_farfield_180 import dipole
    s = Session()
    s.new_project("Dipole")
    d = dipole()
    s.project.designs[0] = d
    s.design = d
    s.solution = d.solve(adaptive=False, progress=False, save_fields=True)
    path = str(tmp_path_factory.mktemp("rt") / "dipole.aedt")
    r = dispatch(s, "project.save", {"path": path})
    return s, path, r


def reopen(path):
    from aether.gui.api import dispatch
    from aether.gui.state import Session
    s2 = Session()
    dispatch(s2, "project.open", {"path": path})
    return s2


def test_saving_a_solved_project_writes_the_results_next_to_it(saved):
    s, path, r = saved
    assert r["results"].endswith(".aedt.aeres") and os.path.isfile(r["results"])


def test_reopening_restores_the_solution_without_solving(saved):
    s, path, _ = saved
    s2 = reopen(path)
    assert s2.solution is not None
    assert s2.solution.design is s2.design
    assert len(s2.solution.fields) == len(s.solution.fields)
    assert s2.solution.mesh.n_tets == s.solution.mesh.n_tets
    assert not s2.dirty


def test_restored_numbers_are_the_same(saved):
    s, path, _ = saved
    a, b = s.solution, reopen(path).solution
    np.testing.assert_allclose(a.sparams.s, b.sparams.s, rtol=0, atol=0)
    np.testing.assert_allclose(a.sparams.freq, b.sparams.freq)
    fa, fb = a.field(3e9, 0), b.field(3e9, 0)
    np.testing.assert_array_equal(fa.x, fb.x)
    pts = a.mesh.centroids()[:50]
    Ea, Ha = fa.eval_at(np.arange(50), pts)
    Eb, Hb = fb.eval_at(np.arange(50), pts)
    np.testing.assert_allclose(Ea, Eb, rtol=1e-12, atol=1e-18)
    np.testing.assert_allclose(Ha, Hb, rtol=1e-12, atol=1e-18)


def test_far_field_and_field_plots_work_on_the_restored_solution(saved):
    from aether.gui.api import dispatch
    s, path, _ = saved
    s2 = reopen(path)
    ff1 = s.solution.farfield()
    ff2 = s2.solution.farfield()
    assert ff2.peak_directivity_dbi() == pytest.approx(ff1.peak_directivity_dbi(),
                                                       abs=1e-9)
    buf = dispatch(s2, "view.field", {"quantity": "J", "where": "surface"})
    assert buf["count"] > 0
    rep = dispatch(s2, "results.report", {})
    assert rep["traces"]


def test_an_edited_project_does_not_load_stale_results(saved, tmp_path):
    s, path, _ = saved
    import shutil
    p2 = str(tmp_path / "copy.aedt")
    shutil.copy(path, p2)
    shutil.copy(path + ".aeres", p2 + ".aeres")
    with open(p2, "ab") as fh:
        fh.write(b"\n")                     # any change to the project file
    s2 = reopen(p2)
    assert s2.solution is None
    assert any("not restored" in m["text"] for m in s2.messages.items()) \
        if hasattr(s2.messages, "items") else True


def test_saving_without_a_solution_removes_a_stale_results_file(saved, tmp_path):
    from aether.gui.api import dispatch
    s, path, _ = saved
    import shutil
    p2 = str(tmp_path / "again.aedt")
    shutil.copy(path, p2)
    shutil.copy(path + ".aeres", p2 + ".aeres")
    s2 = reopen(p2)
    s2.solution = None
    dispatch(s2, "project.save", {"path": p2})
    assert not os.path.exists(p2 + ".aeres")

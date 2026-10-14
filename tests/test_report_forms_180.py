"""S-parameter report forms: impedance and the Smith-chart data."""
import numpy as np
import pytest

from conftest import needs_occ

from aether.gui.api import dispatch
from aether.gui.state import Session

pytestmark = needs_occ


@pytest.fixture(scope="module")
def session():
    import sys, os
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "examples"))
    from build_examples import parallel_plate_lumped
    s = Session()
    s.new_project("P")
    d = parallel_plate_lumped()
    s.project.designs[0] = d
    s.design = d
    s.solution = d.solve(adaptive=False, progress=False)
    return s


def test_input_impedance_traces_match_the_termination(session):
    # Port 2 terminates the line in 2*Z0, so the line input sees a real
    # impedance that swings around Z0 with frequency; check Z from S directly
    r = dispatch(session, "results.report", {"form": "zre",
                                             "traces": [{"i": 1, "j": 1}]})
    i = dispatch(session, "results.report", {"form": "zim",
                                             "traces": [{"i": 1, "j": 1}]})
    sp = session.solution.sparams
    s11 = sp.sij(1, 1)
    z0 = sp.z0[:, 0]
    want = z0 * (1 + s11) / (1 - s11)
    assert np.allclose(r["traces"][0]["y"], want.real)
    assert np.allclose(i["traces"][0]["y"], want.imag)


def test_impedance_needs_a_reflection_trace(session):
    with pytest.raises(ValueError, match="S\\(n,n\\)"):
        dispatch(session, "results.report", {"form": "zre",
                                             "traces": [{"i": 2, "j": 1}]})


def test_smith_and_real_imag_forms_carry_the_complex_trace(session):
    r = dispatch(session, "results.report", {"form": "smith",
                                             "traces": [{"i": 1, "j": 1}]})
    t = r["traces"][0]
    s11 = session.solution.sparams.sij(1, 1)
    assert np.allclose(t["re"], s11.real) and np.allclose(t["im"], s11.imag)
    assert max(np.hypot(t["re"], t["im"])) <= 1.0 + 1e-6      # passive
    re = dispatch(session, "results.report", {"form": "re"})["traces"][0]["y"]
    assert np.allclose(re, session.solution.sparams.sij(1, 1).real)

"""Automatic ports on the shapes people really draw: the port must follow the
*local* width of the signal where it is fed, not the size of its bounding box."""
import numpy as np
import pytest

import aether as ae
from aether.geometry import primitives as prim
from aether.gui.state import Session

from conftest import needs_occ

pytestmark = [needs_occ]

MM = 1e-3


def call(s, method, **params):
    from aether.gui.api import dispatch
    return dispatch(s, method, params)


def session_with(d):
    s = Session()
    s.new_project("P")
    s.project.designs[0] = d
    s.design = d
    return s


def bounds_mm(shape):
    lo, hi = shape.bounds()
    return [round(float(v) * 1e3, 4) for v in list(lo) + list(hi)]


def air_sub_gnd(d, x=(-20, 20), y=(-30, 30), h=1.6, top=12.0):
    d.add_box("air", (x[0] * MM, y[0] * MM, -0.035 * MM),
              ((x[1] - x[0]) * MM, (y[1] - y[0]) * MM, (top + 0.035) * MM), "vacuum")
    d.add_box("sub", (x[0] * MM, y[0] * MM, 0), ((x[1] - x[0]) * MM, (y[1] - y[0]) * MM, h * MM), "vacuum")
    d.add_box("gnd", (x[0] * MM, y[0] * MM, -0.035 * MM), ((x[1] - x[0]) * MM, (y[1] - y[0]) * MM, 0.035 * MM), "pec")


def patch_with_feed():
    """A 30 x 24 mm patch with a 3 mm feed line reaching the -y boundary: one
    polygon, so the bounding box is the patch -- not the feed."""
    d = ae.Design("patch", units="mm")
    air_sub_gnd(d)
    pts = [(-1.5, -30), (1.5, -30), (1.5, -12), (15, -12), (15, 12), (-15, 12), (-15, -12), (-1.5, -12)]
    sheet = prim.Polygon([[x * MM, y * MM, 1.6 * MM] for x, y in pts], name="patch")
    d.add_sheet("patch", sheet)
    d.add_setup("S1", frequency="3GHz")
    return d


SIG = {"kind": "object", "name": "patch"}
GND = {"kind": "object", "name": "gnd"}


def test_a_lumped_port_is_as_wide_as_the_feed_line_not_the_patch():
    s = session_with(patch_with_feed())
    r = call(s, "excitation.autoPort", kind="lumped", signal=[SIG], ground=[GND])
    sheet = next(x for x in s.design.sheets if x.name == r["sheet"])
    b = bounds_mm(sheet.shape)
    assert b[1] == b[4] == pytest.approx(-30.0, abs=1e-3)           # at the end of the feed line
    assert b[0] == pytest.approx(-1.5, abs=1e-3) and b[3] == pytest.approx(1.5, abs=1e-3)   # 3 mm, not 30
    assert b[2] == pytest.approx(0.0, abs=1e-3) and b[5] == pytest.approx(1.6, abs=1e-3)
    assert r["width"] == pytest.approx(3e-3, abs=1e-9)


def test_a_wave_port_window_is_sized_from_the_feed_width():
    s = session_with(patch_with_feed())
    r = call(s, "excitation.autoPort", kind="wave", signal=[SIG], ground=[GND])
    port = s.design.get_port(r["name"])
    assert r["plane"] == "y" and r["at"] == pytest.approx(-0.03)
    (x0, x1), (z0, z1) = port.selector.window
    assert x1 - x0 == pytest.approx(30e-3, abs=1e-6)                # 10 x 3 mm, not 10 x 30
    assert (x0 + x1) / 2 == pytest.approx(0.0, abs=1e-9)
    s_pt, g_pt = port.integration_line
    assert s_pt[0] == pytest.approx(0.0, abs=1e-9) and s_pt[2] == pytest.approx(1.6e-3, abs=1e-9)
    assert g_pt[2] == pytest.approx(0.0, abs=1e-9)


def test_an_off_centre_strip_gets_its_own_centre_and_width():
    d = ae.Design("ms", units="mm")
    air_sub_gnd(d)
    d.add_box("strip", (4 * MM, -30 * MM, 1.6 * MM), (2.2 * MM, 60 * MM, 0.035 * MM), "pec")
    s = session_with(d)
    r = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "strip"}], ground=[GND])
    b = bounds_mm(next(x for x in s.design.sheets if x.name == r["sheet"]).shape)
    assert b[0] == pytest.approx(4.0, abs=1e-3) and b[3] == pytest.approx(6.2, abs=1e-3)
    assert b[1] == b[4] and abs(b[1]) == pytest.approx(30.0)


def test_a_tapered_end_uses_the_width_of_the_end_face():
    d = ae.Design("taper", units="mm")
    air_sub_gnd(d)
    pts = [(-4, 30), (4, 30), (1, 10), (1, -30), (-1, -30), (-1, 10)]            # 2 mm at -y, 8 mm at +y
    d.add_sheet("t", prim.Polygon([[x * MM, y * MM, 1.6 * MM] for x, y in pts], name="t"))
    s = session_with(d)
    r = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "t"}], ground=[GND])
    b = bounds_mm(next(x for x in s.design.sheets if x.name == r["sheet"]).shape)
    assert b[4] == pytest.approx(-30.0) and b[3] - b[0] == pytest.approx(2.0, abs=1e-3)
    r2 = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "t"}], ground=[GND])
    b2 = bounds_mm(next(x for x in s.design.sheets if x.name == r2["sheet"]).shape)
    assert b2[4] == pytest.approx(30.0) and b2[3] - b2[0] == pytest.approx(8.0, abs=1e-3)   # the other end


def test_a_ground_narrower_than_the_signal_limits_the_sheet():
    d = ae.Design("n", units="mm")
    d.add_box("air", (-20 * MM, -30 * MM, -MM), (40 * MM, 60 * MM, 14 * MM), "vacuum")
    d.add_box("gnd", (-1 * MM, -30 * MM, -0.035 * MM), (2 * MM, 60 * MM, 0.035 * MM), "pec")
    d.add_box("strip", (-3 * MM, -30 * MM, 1.6 * MM), (6 * MM, 60 * MM, 0.035 * MM), "pec")
    s = session_with(d)
    r = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "strip"}],
             ground=[{"kind": "object", "name": "gnd"}])
    b = bounds_mm(next(x for x in s.design.sheets if x.name == r["sheet"]).shape)
    assert b[0] == pytest.approx(-1.0, abs=1e-3) and b[3] == pytest.approx(1.0, abs=1e-3)


def test_a_dipole_gap_is_bridged_in_the_middle_of_the_arms():
    d = ae.Design("dip", units="mm")
    d.add_box("air", (-60 * MM, -60 * MM, -80 * MM), (120 * MM, 120 * MM, 160 * MM), "vacuum")
    d.add_box("top", (-1 * MM, -1 * MM, 1 * MM), (2 * MM, 2 * MM, 40 * MM), "pec")
    d.add_box("bot", (-1 * MM, -1 * MM, -41 * MM), (2 * MM, 2 * MM, 40 * MM), "pec")
    s = session_with(d)
    r = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "top"}],
             ground=[{"kind": "object", "name": "bot"}])
    b = bounds_mm(next(x for x in s.design.sheets if x.name == r["sheet"]).shape)
    assert b[2] == pytest.approx(-1.0, abs=1e-3) and b[5] == pytest.approx(1.0, abs=1e-3)   # the 2 mm gap
    # a full arm wide on one axis, in the middle of the arm on the other
    wide = sorted([b[3] - b[0], b[4] - b[1]])
    assert wide == pytest.approx([0.0, 2.0], abs=1e-3)
    thin = 0 if b[3] - b[0] < 1e-6 else 1
    assert abs(b[thin]) < 1e-3                                       # through the middle of the arm


def test_a_coplanar_line_is_bridged_across_the_slot():
    d = ae.Design("cpw", units="mm")
    d.add_box("air", (-20 * MM, -30 * MM, -5 * MM), (40 * MM, 60 * MM, 15 * MM), "vacuum")
    d.add_box("sub", (-20 * MM, -30 * MM, -1.6 * MM), (40 * MM, 60 * MM, 1.6 * MM), "vacuum")
    d.add_box("left", (-20 * MM, -30 * MM, 0), (17.5 * MM, 60 * MM, 0.035 * MM), "pec")
    d.add_box("right", (2.5 * MM, -30 * MM, 0), (17.5 * MM, 60 * MM, 0.035 * MM), "pec")
    d.add_box("sig", (-1.5 * MM, -30 * MM, 0), (3 * MM, 60 * MM, 0.035 * MM), "pec")
    s = session_with(d)
    r = call(s, "excitation.autoPort", kind="lumped", signal=[{"kind": "object", "name": "sig"}],
             ground=[{"kind": "object", "name": "right"}])
    b = bounds_mm(next(x for x in s.design.sheets if x.name == r["sheet"]).shape)
    assert b[0] == pytest.approx(1.5, abs=1e-3) and b[3] == pytest.approx(2.5, abs=1e-3)     # across the 1 mm slot
    assert abs(b[1]) == pytest.approx(30.0) and b[1] == b[4]
    port = s.design.get_port(r["name"])
    assert port.direction[0] == pytest.approx(1.0)                  # signal -> ground, toward +x

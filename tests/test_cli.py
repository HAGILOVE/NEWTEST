"""End-to-end command-line behaviour."""
import os

import pytest

from conftest import needs_occ

import aether as ae
from aether.cli import main
from aether.io.warp.writer import write_project


@pytest.fixture()
def project(tmp_path):
    d = ae.Design("WarpsDesign1", units="mm")
    d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "15mm"), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value="15mm")
    d.assign_pec_outer()
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=1)
    st.add_sweep("Sweep1", "9GHz", "11GHz", 3)
    p = str(tmp_path / "proj.warp")
    write_project(p, d, mode="create")
    return p


@pytest.mark.parametrize("template", ["waveguide", "coax", "microstrip"])
def test_new_writes_a_project_that_reimports(tmp_path, template, capsys):
    p = str(tmp_path / f"{template}.warp")
    assert main(["new", p, "--template", template]) == 0
    assert os.path.getsize(p) > 0
    d, rep = ae.open_warps(p)
    assert not rep.unresolved
    assert d.solids and d.ports and d.setups
    assert not d.validate()


@needs_occ
def test_new_then_solve_gives_a_physical_answer(tmp_path):
    """The starter project must actually solve, and solve correctly."""
    p = str(tmp_path / "wg.warp")
    base = str(tmp_path / "wg")
    assert main(["new", p, "--template", "microstrip"]) == 0
    assert main(["solve", p, "--no-adaptive", "--out", base]) == 0
    sp = ae.read_touchstone(base + ".s2p")
    assert sp.is_passive() and sp.is_reciprocal(1e-6)
    assert abs(sp.sij(2, 1)).min() > 0.99      # a matched line passes power
    assert sp.db(1, 1).max() < -25             # and barely reflects


def test_materials_listing(capsys):
    assert main(["materials", "rogers"]) == 0
    out = capsys.readouterr().out
    assert "rogers_ro4003c" in out and "3.55" in out


def test_info_and_validate(project, capsys):
    assert main(["info", project]) == 0
    assert "WarpsDesign1" in capsys.readouterr().out
    assert main(["validate", project]) == 0
    assert "YES" in capsys.readouterr().out


def test_convert_warp_to_warpz(project, tmp_path):
    out = str(tmp_path / "p.warpz")
    assert main(["convert", project, out]) == 0
    assert os.path.getsize(out) > 0
    from aether.io.warp.tree import WarpDocument
    assert WarpDocument.parse(out).warps_designs()


def test_convert_touchstone_formats(tmp_path):
    import numpy as np
    f = np.linspace(1e9, 2e9, 5)
    s = 0.2 * np.ones((5, 2, 2), complex)
    a = str(tmp_path / "a.s2p")
    ae.write_touchstone(a, ae.SParameters(f, s, 50.0))
    b = str(tmp_path / "b.ts")
    assert main(["convert", a, b, "--format", "MA"]) == 0
    back = ae.read_touchstone(b)
    assert np.max(np.abs(back.s - s)) < 1e-9


@needs_occ
def test_mesh_command(project, tmp_path, capsys):
    out = str(tmp_path / "m.vtu")
    assert main(["mesh", project, "--size", "0.004", "--out", out]) == 0
    assert "TetMesh" in capsys.readouterr().out
    assert os.path.getsize(out) > 0


@needs_occ
def test_solve_command_writes_every_artifact(project, tmp_path, capsys):
    base = str(tmp_path / "run")
    assert main(["solve", project, "--no-adaptive", "--out", base]) == 0
    for ext in (".s2p", "_sparams.csv", "_modes.csv", "_report.html"):
        assert os.path.getsize(base + ext) > 0
    sp = ae.read_touchstone(base + ".s2p")
    assert sp.n_port == 2 and sp.n_freq == 3
    assert abs(sp.sij(2, 1)[0]) == pytest.approx(1.0, abs=5e-3)
    html = open(base + "_report.html").read()
    assert "Aether-EM" in html and "svg" in html


def test_unknown_file_gives_a_clean_error(tmp_path, capsys):
    assert main(["info", str(tmp_path / "nope.warp")]) == 1
    assert "error" in capsys.readouterr().err

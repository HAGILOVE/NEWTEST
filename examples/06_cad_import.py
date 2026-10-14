"""
Import a STEP file and solve on the imported geometry.

Real CAD arrives as STEP/IGES; Aether reads it through OpenCASCADE so curved
surfaces stay analytic all the way into the mesher.  This example exports a
STEP file first so it runs anywhere, then re-imports it.
"""
import os

import aether as ae
from aether.geometry.brep_io import export_shapes
from aether.geometry.kernel import GmshSession, build_shape


def make_step(path="ridge_guide.step"):
    """A ridged waveguide section, written as STEP AP203."""
    body = (ae.Box((0, 0, 0), ("22.86mm", "10.16mm", "20mm"))
            - ae.Box(("9mm", "0mm", "5mm"), ("4.86mm", "3mm", "10mm")))
    with GmshSession("step") as gmsh:
        build_shape(body, gmsh)
        gmsh.model.occ.synchronize()
        export_shapes(path, gmsh)
    return path


def main():
    step = make_step()
    print(f"STEP file: {step} ({os.path.getsize(step)} bytes)")

    d = ae.Design("imported_guide", units="mm")
    d.add_solid("guide", ae.import_cad(step, name="guide"), "vacuum")
    d.add_wave_port("p1", axis="z", value=0)
    d.add_wave_port("p2", axis="z", value="20mm")
    d.assign_pec_outer()
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=2)
    st.add_sweep("Sweep", "8GHz", "12GHz", 9)

    mesh = d.generate_mesh(10e9, force=True, size=0.0025)
    print(mesh.report())

    sol = d.solve(adaptive=False)
    print(sol.summary())
    m = sol.port_mode(10e9, 0, 0)
    print(f"\nport mode (plain WR-90 cross-section): {m.kind}, "
          f"cutoff {m.f_cut/1e9:.4f} GHz  [analytic 6.5571 GHz]")
    print("The ridge sits in the middle of the run, so it shows up as a "
          "reflective discontinuity in S11 rather than in the port modes.")
    sol.sparams.write_touchstone("ridge_guide.s2p")


if __name__ == "__main__":
    main()

"""
Project files: read a .warp project, inspect it, modify it, write it back.

Shows both writing modes:
  * ``create`` -- generate a fresh .warp from an Aether model,
  * ``update`` -- edit an existing project so that every byte Aether does not
    model is preserved exactly.
"""
import os
import sys

import aether as ae
from aether.io.warp.tree import WarpDocument
from aether.io.warp.writer import write_project


def make_demo_project(path):
    d = ae.Design("WarpsDesign1", units="mm")
    d.add_box("substrate", (0, 0, 0), ("20mm", "10mm", "0.8mm"),
              "rogers_ro4003c")
    d.add_box("air", ("-5mm", "-5mm", "0.8mm"), ("30mm", "20mm", "6mm"), "air")
    d.add_cylinder("via", ("10mm", "5mm", 0), "0.15mm", "0.8mm", "copper")
    d.add_wave_port("p1", axis="x", value=0)
    d.add_wave_port("p2", axis="x", value="20mm")
    d.assign_radiation("Rad1")
    st = d.add_setup("Setup1", frequency="10GHz", max_passes=6, delta_s=0.02)
    st.add_sweep("Sweep1", "1GHz", "20GHz", 191)
    return write_project(path, d, mode="create")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "demo_project.warp"
    if not os.path.exists(path):
        make_demo_project(path)
        print(f"created {path}")

    # ---- raw tree: byte-exact round trip ----------------------------
    doc = WarpDocument.parse(path)
    assert doc.to_text().encode(doc.encoding) == open(path, "rb").read()
    print("raw parse/write round trip : byte-identical")
    print(f"designs in project         : "
          f"{[str(b.get('Name')) for b in doc.warps_designs()]}")

    # ---- model level -------------------------------------------------
    design, report = ae.open_warps(path)
    print("\n" + str(report))
    print("\n" + design.summary())

    # ---- modify and write back, preserving everything else -----------
    design.get_setup("Setup1").frequency = 12e9
    out = os.path.splitext(path)[0] + "_modified.warp"
    write_project(out, design, mode="update")
    print(f"\nwrote {out} (update mode: only the changed statements differ)")

    a = open(path).read().splitlines()
    b = open(out).read().splitlines()
    changed = [(i, x, y) for i, (x, y) in enumerate(zip(a, b)) if x != y]
    for i, x, y in changed:
        print(f"  line {i+1}: {x.strip()!r} -> {y.strip()!r}")


if __name__ == "__main__":
    main()

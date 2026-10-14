"""
Command-line interface: ``aether <command> ...``

    aether doctor                       check the Python environment
    aether gui                          open the Aether Desktop workspace
    aether new        <file.warp>       write a small, ready-to-solve project
    aether info       <file>            inspect an .warp / .sNp / CAD file
    aether convert    <in> <out>        .warp <-> .warpz, .sNp <-> .ts, CAD
    aether validate   <file.warp>       parse + round-trip integrity check
    aether mesh       <file.warp>       generate and report the mesh
    aether solve      <file.warp>       run the analysis, write results
    aether materials  [pattern]         list the material library
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from typing import List, Optional

from .core.logging import configure, get_logger
from .version import __engine__, __version__

log = get_logger("cli")


TEMPLATES = ("waveguide", "coax", "microstrip")


def _p_doctor(args) -> int:
    from ._preflight import main as doctor_main
    return doctor_main()


def _p_gui(args) -> int:
    """Launch the graphical workspace and open it in a browser."""
    from .gui.server import serve
    serve(host=args.host, port=args.port,
          open_browser=not args.no_browser,
          project=args.project, template=args.template,
          token="" if args.no_token else None)
    return 0


def _p_new(args) -> int:
    """Write a small, fast, physically meaningful starter project."""
    from .io.warp.writer import write_project
    from .model import Design
    import math
    from .core.constants import c0, eta0

    t = args.template
    if t == "waveguide":
        d = Design("WR90_Thru", units="mm")
        d.add_box("guide", (0, 0, 0), ("22.86mm", "10.16mm", "20mm"), "vacuum")
        d.add_wave_port("p1", axis="z", value=0)
        d.add_wave_port("p2", axis="z", value="20mm")
        d.assign_pec_outer("Walls")
        st = d.add_setup("Setup1", frequency="10GHz", max_passes=3,
                         delta_s=0.02)
        st.add_sweep("XBand", "8.2GHz", "12.4GHz", 15)
    elif t == "coax":
        a = 1.0e-3
        b = a * math.exp(50.0 * 2 * math.pi / eta0)
        L = 20e-3
        from .geometry.primitives import Cylinder
        d = Design("Coax50", units="mm")
        d.add_solid("diel", Cylinder((0, 0, 0), b, L)
                    - Cylinder((0, 0, -1e-3), a, L + 2e-3), "vacuum")
        d.add_wave_port("p1", axis="z", value=0,
                        integration_line=((a, 0, 0), (b, 0, 0)))
        d.add_wave_port("p2", axis="z", value=L,
                        integration_line=((a, 0, L), (b, 0, L)))
        st = d.add_setup("Setup1", frequency="10GHz", max_passes=1)
        st.add_sweep("Sweep", "1GHz", "20GHz", 11)
    else:                                   # microstrip-like parallel plate
        h, w, L = 1e-3, 10e-3, 20e-3
        from .geometry.select import PlaneSelector
        d = Design("PlateLine", units="mm")
        d.add_box("air", (0, 0, 0), (L, w, h), "vacuum")
        d.assign_boundary("PMC_y0", "pmc", PlaneSelector("y", 0))
        d.assign_boundary("PMC_y1", "pmc", PlaneSelector("y", w))
        z0 = eta0 * h / w
        d.add_lumped_port("p1", axis="x", value=0, impedance=z0,
                          direction=(0, 0, 1))
        d.add_lumped_port("p2", axis="x", value=L, impedance=z0,
                          direction=(0, 0, 1))
        st = d.add_setup("Setup1", frequency="5GHz", max_passes=2)
        st.add_sweep("Sweep", "1GHz", "10GHz", 10)

    path = args.path
    if not os.path.splitext(path)[1]:
        path += ".warp"
    write_project(path, d, mode="create")
    print(f"wrote {path}  [{t}]")
    print(d.summary())
    print(f"\nnext:  aether solve {path}")
    return 0


def _p_info(args) -> int:
    path = args.path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".warp", ".warpz"):
        from .io.warp.tree import WarpDocument
        doc = WarpDocument.parse(path)
        print(f"{path}\n  encoding : {doc.encoding}\n  designs  : "
              f"{len(doc.designs())}")
        for i, d in enumerate(doc.warps_designs() or doc.designs()):
            print(f"  [{i}] {str(d.get('Name','?')):<24} "
                  f"type={d.get('DesignType')} solution={d.get('SolutionType')}")
        from .io.warp.translate import read_design
        for i in range(len(doc.warps_designs() or doc.designs())):
            des, rep = read_design(doc, i)
            print(rep)
            print(des.summary())
    elif ext.startswith(".s") or ext == ".ts":
        from .io.touchstone import read_touchstone
        sp = read_touchstone(path)
        print(sp.summary())
    else:
        from .geometry.brep_io import detect_format, quick_bounds
        fmt = detect_format(path)
        lo, hi = quick_bounds(path)
        print(f"{path}\n  format : {fmt}\n  bbox   : {lo} .. {hi} m")
    return 0


def _p_convert(args) -> int:
    src, dst = args.src, args.dst
    se, de = (os.path.splitext(x)[1].lower() for x in (src, dst))
    if se in (".warp", ".warpz") and de in (".warp", ".warpz"):
        from .io.warp.tree import WarpDocument
        WarpDocument.parse(src).write(dst)
    elif se in (".ts",) or se.startswith(".s"):
        from .io.touchstone import read_touchstone, write_touchstone
        sp = read_touchstone(src)
        write_touchstone(dst, sp, fmt=args.format, unit=args.unit,
                         version=2.0 if de == ".ts" else 1.0)
    else:
        from .geometry.brep_io import export_shapes, import_into_occ
        from .geometry.kernel import GmshSession
        with GmshSession("convert") as gmsh:
            import_into_occ(src, gmsh)
            export_shapes(dst, gmsh)
    print(f"wrote {dst}")
    return 0


def _p_validate(args) -> int:
    from .io.warp.tree import WarpDocument
    with open(args.path, "rb") as fh:
        original = fh.read()
    doc = WarpDocument.parse(args.path)
    text = doc.to_text().encode(doc.encoding or "utf-8")
    ok = text == original
    print(f"parsed {len(doc.designs())} design block(s)")
    print(f"round-trip byte-identical : {'YES' if ok else 'NO'}")
    if not ok:
        a, b = original.split(b"\n"), text.split(b"\n")
        n = 0
        for i, (x, y) in enumerate(zip(a, b)):
            if x != y:
                print(f"  line {i+1}:\n    original: {x[:120]!r}\n"
                      f"    written : {y[:120]!r}")
                n += 1
                if n >= 10:
                    break
        if len(a) != len(b):
            print(f"  line count {len(a)} -> {len(b)}")
    from .io.warp.translate import read_design
    for i in range(len(doc.warps_designs() or doc.designs())):
        _, rep = read_design(doc, i)
        print(rep)
    return 0 if ok else 1


def _load_design(path: str, index):
    from . import open_warps
    d, rep = open_warps(path, index)
    if rep.unresolved:
        log.warning("%d unresolved item(s) -- see the import report",
                    len(rep.unresolved))
    return d


def _p_mesh(args) -> int:
    d = _load_design(args.path, args.design)
    f = d.setups[0].frequency if d.setups else 1e9
    m = d.generate_mesh(f, force=True, backend=args.backend,
                        **({"size": args.size} if args.size else {}))
    print(m.report())
    if args.out:
        from .io.vtk_io import write_vtu
        write_vtu(args.out, m, cell_data={"region": m.tet_region})
        print(f"wrote {args.out}")
    return 0


def _p_solve(args) -> int:
    d = _load_design(args.path, args.design)
    if args.order:
        d.config.basis_order = args.order
        for s in d.setups:
            s.basis_order = args.order
    if args.passes:
        for s in d.setups:
            s.max_passes = args.passes
    sol = d.solve(backend=args.backend, adaptive=not args.no_adaptive,
                  save_fields=bool(args.fields))
    print(sol.summary())
    base = args.out or os.path.splitext(args.path)[0]
    n = sol.sparams.n_port
    sol.sparams.write_touchstone(f"{base}.s{n}p")
    sol.sparams.to_csv(f"{base}_sparams.csv")
    from .io.csv_io import write_port_modes_csv
    write_port_modes_csv(f"{base}_modes.csv", sol)
    from .post.report import html_report
    html_report(sol, f"{base}_report.html")
    print(f"wrote {base}.s{n}p, {base}_sparams.csv, {base}_modes.csv, "
          f"{base}_report.html")
    if args.fields:
        fs = sol.field(sol.freqs[-1], 0)
        fs.to_vtk(f"{base}_fields.vtu")
        print(f"wrote {base}_fields.vtu")
    return 0


def _p_materials(args) -> int:
    from .core.materials import LIBRARY
    pat = (args.pattern or "").lower()
    print(f"{'name':28} {'eps_r':>8} {'tan_d':>9} {'mu_r':>6} "
          f"{'sigma [S/m]':>13}  kind")
    for n in LIBRARY.names():
        if pat and pat not in n:
            continue
        m = LIBRARY.get(n)
        e = m.eps_model.eps(1e9)
        mu = m.mu_model.eps(1e9)
        td = -e.imag / e.real if e.real else 0.0
        print(f"{n:28} {e.real:8.4g} {td:9.5g} {mu.real:6.3g} "
              f"{m.sigma:13.5g}  {m.kind}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="aether", description=f"{__engine__} v{__version__}")
    p.add_argument("--version", action="version",
                   version=f"{__engine__} {__version__}")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("-q", "--quiet", action="store_true")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("doctor", help="check the Python environment")
    s.set_defaults(func=_p_doctor)

    s = sub.add_parser("gui", help="open the Aether Desktop workspace")
    s.add_argument("--host", default="127.0.0.1")
    s.add_argument("--port", type=int, default=0)
    s.add_argument("--no-browser", action="store_true")
    s.add_argument("--no-token", action="store_true",
                   help="disable the API token (only for automated testing)")
    s.add_argument("--project", default=None, help="open this .warp on start")
    s.add_argument("--template", default=None, choices=TEMPLATES,
                   help="start from a template")
    s.set_defaults(func=_p_gui)

    s = sub.add_parser("new", help="write a small, ready-to-solve project")
    s.add_argument("path")
    s.add_argument("--template", default="waveguide", choices=TEMPLATES)
    s.set_defaults(func=_p_new)

    s = sub.add_parser("info", help="inspect a project, network or CAD file")
    s.add_argument("path")
    s.set_defaults(func=_p_info)

    s = sub.add_parser("convert", help="convert between supported formats")
    s.add_argument("src")
    s.add_argument("dst")
    s.add_argument("--format", default="RI", choices=["RI", "MA", "DB"])
    s.add_argument("--unit", default="GHz")
    s.set_defaults(func=_p_convert)

    s = sub.add_parser("validate", help="check .warp parse/write integrity")
    s.add_argument("path")
    s.set_defaults(func=_p_validate)

    s = sub.add_parser("mesh", help="generate the mesh and report it")
    s.add_argument("path")
    s.add_argument("--design", default=0)
    s.add_argument("--backend", default="auto",
                   choices=["auto", "occ", "builtin"])
    s.add_argument("--size", type=float, default=None, help="element size [m]")
    s.add_argument("--out", default=None, help="write a .vtu file")
    s.set_defaults(func=_p_mesh)

    s = sub.add_parser("solve", help="run the analysis")
    s.add_argument("path")
    s.add_argument("--design", default=0)
    s.add_argument("--backend", default="auto",
                   choices=["auto", "occ", "builtin"])
    s.add_argument("--order", type=int, default=None, choices=[1, 2])
    s.add_argument("--passes", type=int, default=None)
    s.add_argument("--no-adaptive", action="store_true")
    s.add_argument("--fields", action="store_true", help="save field data")
    s.add_argument("--out", default=None, help="output basename")
    s.set_defaults(func=_p_solve)

    s = sub.add_parser("materials", help="list the material library")
    s.add_argument("pattern", nargs="?", default=None)
    s.set_defaults(func=_p_materials)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    args = build_parser().parse_args(argv)
    configure("DEBUG" if args.verbose else ("WARNING" if args.quiet else "INFO"))
    from ._preflight import AetherEnvironmentError, environment_error
    if args.cmd != "doctor":
        env = environment_error()
        if env is not None:
            # One clear diagnosis instead of a nested traceback from whichever
            # scientific import happened to fail first.
            print(str(env), file=sys.stderr)
            return 2
    try:
        if isinstance(getattr(args, "design", None), str) \
                and args.design.isdigit():
            args.design = int(args.design)
        return int(args.func(args) or 0)
    except KeyboardInterrupt:                    # pragma: no cover
        print("interrupted", file=sys.stderr)
        return 130
    except AetherEnvironmentError as exc:
        print(str(exc), file=sys.stderr)
        return 2
    except Exception as exc:
        if args.verbose:
            raise
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":                       # pragma: no cover
    sys.exit(main())

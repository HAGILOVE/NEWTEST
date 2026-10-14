"""Actionable model checks. Unsupported physics must fail before assembly."""

from __future__ import annotations
import math
import numpy as np


def additional_errors(d):
    errs = import_errors(d)
    if d.solution_type not in ("driven_modal", "eigenmode"):
        errs.append(
            f"{d.solution_type}: only driven_modal and eigenmode are implemented "
            "by the current solver"
        )
    if d.config.time_convention != "ejwt":
        errs.append("Only exp(+jωt) time convention is implemented")
    supported = {
        "pec",
        "pmc",
        "radiation",
        "finite_cond",
        "impedance",
        "symmetry_e",
        "symmetry_h",
        "lumped_rlc",
    }
    for b in d.boundaries:
        if b.btype not in supported:
            errs.append(f"{b.name}: boundary {b.btype} is not implemented")
        elif d.solution_type == "eigenmode" and b.btype in ("radiation",
                                                           "lumped_rlc"):
            errs.append(
                f"{b.name}: {b.btype} boundaries are not supported by the "
                "eigenmode solver (the first-order absorbing term makes the "
                "problem nonlinear in frequency and the modes are not "
                "reliable). Use PEC, finite-conductivity or surface-impedance "
                "walls, or find the open structure's response with a driven "
                "solution.")
    allnames = [o.name for o in d.solids + d.sheets]
    if len(set(allnames)) != len(allnames):
        errs.append("Object and sheet names must be unique")
    if len(set(s.name for s in d.setups)) != len(d.setups):
        errs.append("Solution setup names must be unique")
    for o in d.solids + d.sheets:
        try:
            lo, hi = np.asarray(o.shape.bounds(), float)
            if not np.isfinite([lo, hi]).all():
                errs.append(f"{o.name}: non-finite coordinates")
            if o in d.solids and np.any(hi - lo <= 0):
                errs.append(f"{o.name}: zero/negative solid extent")
        except Exception as exc:
            errs.append(f"{o.name}: geometry unavailable ({exc})")
    for p in d.ports:
        if int(p.num_modes) < 1:
            errs.append(f"{p.name}: mode count must be positive")
        if p.kind == "lumped":
            z = complex(p.impedance)
            if not np.isfinite([z.real, z.imag]).all() or z.real <= 0:
                errs.append(f"{p.name}: impedance requires a positive real part")
            if not np.isfinite(p.direction).all() or np.linalg.norm(p.direction) == 0:
                errs.append(f"{p.name}: invalid field direction")
    for st in d.setups:
        if not math.isfinite(st.frequency) or st.frequency <= 0:
            errs.append(f"{st.name}: solution frequency must be finite and positive")
        if st.basis_order not in (1, 2):
            errs.append(f"{st.name}: basis order must be 1 or 2")
        if not (1 <= st.min_passes <= st.max_passes <= 100):
            errs.append(f"{st.name}: require 1 ≤ minimum passes ≤ maximum passes ≤ 100")
        if not math.isfinite(st.delta_s) or not 0 < st.delta_s < 1:
            errs.append(f"{st.name}: require 0 < ΔS < 1")
        if d.solution_type == "eigenmode":
            if not 1 <= int(st.n_modes) <= 50:
                errs.append(f"{st.name}: number of modes must be 1..50")
            if not math.isfinite(st.min_frequency) or st.min_frequency < 0:
                errs.append(f"{st.name}: minimum frequency must be >= 0")
            if not math.isfinite(st.delta_f) or not 0 < st.delta_f < 1:
                errs.append(f"{st.name}: require 0 < max delta frequency < 1")
        if len(set(s.name for s in st.sweeps)) != len(st.sweeps):
            errs.append(f"{st.name}: duplicate sweep names")
        for sw in st.sweeps:
            if sw.kind not in ("discrete", "fast", "interpolating"):
                errs.append(f"{sw.name}: unknown sweep strategy")
            try:
                f = sw.frequencies()
                if not len(f) or not np.isfinite(f).all() or np.any(f <= 0):
                    errs.append(f"{sw.name}: finite positive frequencies required")
                if len(f) > 20001:
                    errs.append(f"{sw.name}: maximum 20001 frequency points per sweep")
            except Exception as exc:
                errs.append(f"{sw.name}: invalid sweep ({exc})")
    for op in d.mesh_ops:
        if any(n not in allnames for n in op.objects):
            errs.append(f"{op.name}: missing mesh target")
    return errs


def report(d):
    from .geometry.kernel import available
    from .mesh.generator import target_size
    from .parametric import walk
    from .geometry.primitives import ImportedShape

    errors = d.validate()
    warnings = []
    if any(getattr(o.shape,"reference_only",False) for o in d.sheets):
        warnings.append("Reference sketches are visible drawing guides only and are excluded from FEM meshing.")
    occ = available()
    if not occ:
        warnings.append(
            "OCC unavailable: native CAD and STEP export are unavailable; builtin meshing approximates curved boundaries."
        )
        if any(
            isinstance(sh, ImportedShape)
            for o in d.solids + d.sheets
            for sh in walk(o.shape)
        ):
            errors.append("Imported CAD requires the OCC backend")
    if any(b.btype == "radiation" for b in d.boundaries):
        warnings.append(
            "Radiation uses a first-order absorbing boundary, not PML. Check air clearance and convergence."
        )
    for o in d.solids:
        if getattr(o.shape, "_parametric", None) and d.ports:
            warnings.append(
                "Geometry expressions rebuild primitives. Fixed-coordinate ports and boundary selections do not automatically follow changed dimensions; verify assignments."
            )
            break
    if d.sheets and not occ:
        warnings.append(
            "Builtin mesh may not conform to internal sheets; verify port and sheet placement on the generated mesh."
        )
    estimate = None
    try:
        f = d.setups[0].frequency if d.setups else 1e9
        h, _ = target_size(d, f)
        lo, hi = d.bounding_box()
        n = np.maximum(1, np.ceil((hi - lo) / h)).astype(int)
        estimate = {
            "targetSize": h,
            "uniformGridTets": int(6 * np.prod(n)),
            "note": "Uniform bounding-grid estimate only; OCC/adaptive element counts can differ substantially.",
        }
    except Exception:
        pass
    return {
        "ok": not errors,
        "errors": list(dict.fromkeys(errors)),
        "warnings": list(dict.fromkeys(warnings)),
        "occ": occ,
        "estimate": estimate,
        "capabilities": {
            "drivenModal": True,
            "basisOrders": [1, 2],
            "adaptive": True,
            "parameterSweep": True,
            "eigenmode": True,
            "periodicFloquet": False,
            "pml": False,
            "warpsNativeFullCompatibility": False,
        },
    }


def import_errors(d):
    """Prevent solving a partial imported model or assumed material assignment."""
    import os,re
    from .parametric import walk
    from .geometry.primitives import ImportedShape
    errors=[]
    objects={o.name:o for o in d.solids+d.sheets}
    for name,obj in objects.items():
        for shape in walk(obj.shape):
            if getattr(shape,"_cad_unreadable",""):
                errors.append(f"{name}: geometry unavailable. Replace CAD Source with a readable STEP/BREP export.");break
            if isinstance(shape,ImportedShape) and not os.path.isfile(shape.path):
                errors.append(f"{name}: CAD source file is missing.");break
        if getattr(obj,"import_material",""):
            errors.append(f"{name}: unresolved imported material {obj.import_material!r}; assign the correct material before solving.")
    for issue in getattr(d,"import_issues",[]):
        m=re.match(r"(part|boundary|excitation) '([^']+)'",issue)
        if m:
            kind,name=m.groups()
            names=objects if kind=='part' else {x.name for x in (d.boundaries if kind=='boundary' else d.ports)}
            if name in names:continue
        errors.append('Unresolved import: '+issue)
    return list(dict.fromkeys(errors))

"""
Adaptive mesh refinement.

The convergence criterion is HFSS's: between two consecutive passes the
maximum change of any S-parameter entry,

    dS = max_ij | S_ij^(n) - S_ij^(n-1) |

must fall below ``delta_s``.  Elements are ranked by a **tangential-H jump**
indicator: the electric field is tangentially continuous by construction, so
any discontinuity of ``n x H`` across an interior face is pure discretisation
error and is a reliable, cheap, basis-independent local error estimate.

Refinement is applied as a *size field* handed back to the mesher, so each
pass produces a fresh, well-shaped, globally-conforming mesh rather than a
progressively distorted bisected one.
"""
from __future__ import annotations

import os
import tempfile
from typing import List, Optional, Tuple

import numpy as np

from ..core.logging import get_logger, timed
from .assembly import assemble_regions
from .boundary import BoundaryTerms
from .elements import DofMap

log = get_logger("fem.adaptive")


def element_error(mesh, dofmap, x, freq, mu_of_region) -> np.ndarray:
    """Per-element tangential-H jump indicator (dimensionless, normalised)."""
    from ..core.constants import mu0, omega
    from .elements import tet_basis

    fp = dofmap.face_perm if dofmap.order >= 2 else None
    lam = np.array([0.25, 0.25, 0.25, 0.25])
    _, C = tet_basis(dofmap.order, mesh.grads, lam, fp)
    c = x[dofmap.elem_dofs] * dofmap.elem_signs
    curlE = np.einsum("eia,ei->ea", C, c)
    mu = np.array([mu_of_region(int(r)) for r in mesh.tet_region])
    H = -curlE / (1j * omega(freq) * mu0 * mu[:, None])

    f2t = mesh.face_to_tet()
    interior = np.nonzero(f2t[:, 1] >= 0)[0]
    t1 = f2t[interior, 0]
    t2 = f2t[interior, 1]
    tri = mesh.faces[interior]
    p = mesh.nodes[tri]
    nrm = np.cross(p[:, 1] - p[:, 0], p[:, 2] - p[:, 0])
    area = 0.5 * np.linalg.norm(nrm, axis=1)
    n = nrm / np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-300)
    jump = np.cross(n, H[t1] - H[t2])
    contrib = area * np.sum(np.abs(jump) ** 2, axis=1)

    err = np.zeros(mesh.n_tets)
    np.add.at(err, t1, contrib)
    np.add.at(err, t2, contrib)
    scale = err.max()
    return err / scale if scale > 0 else err


def size_field_from_error(mesh, err: np.ndarray, fraction: float = 0.3,
                          factor: float = 0.72) -> np.ndarray:
    """Per-node target element size: shrink the worst *fraction* of elements."""
    h = np.cbrt(np.maximum(mesh.volumes, 1e-300) * 6.0 * np.sqrt(2.0))
    thresh = np.quantile(err, 1.0 - fraction) if len(err) else 0.0
    h_new = np.where(err >= thresh, h * factor, h)
    node_h = np.full(mesh.n_nodes, np.inf)
    for k in range(4):
        np.minimum.at(node_h, mesh.tets[:, k], h_new)
    node_h[~np.isfinite(node_h)] = h.mean()
    return node_h


def write_pos_field(path: str, mesh, node_h: np.ndarray) -> str:
    """gmsh background-mesh view (scalar tetrahedron ``SS``) for remeshing."""
    p = mesh.nodes
    with open(path, "w") as fh:
        fh.write('View "bgmesh" {\n')
        for t in mesh.tets:
            xs = p[t]
            coords = ",".join(f"{xs[i][j]:.9g}" for j in range(3) for i in range(4))
            vals = ",".join(f"{node_h[i]:.9g}" for i in t)
            fh.write(f"SS({coords}){{{vals}}};\n")
        fh.write("};\n")
    return path


# --------------------------------------------------------------------------


def remesh_from_error(design, mesh, err: np.ndarray, freq: float,
                      backend: str = "auto", pass_no: int = 1,
                      fraction: Optional[float] = None):
    """
    A fresh mesh whose element size follows the per-element error *err*.

    The mesher is handed a background size field; if that route is
    unavailable the whole model is remeshed uniformly finer instead.  The new
    mesh is also stored on ``design.mesh``.
    """
    from ..mesh.generator import generate
    cfg = design.config.adaptive
    size_file = None
    try:
        node_h = size_field_from_error(
            mesh, err, cfg.refinement_fraction if fraction is None else fraction)
        fd, size_file = tempfile.mkstemp(suffix=".pos")
        os.close(fd)
        write_pos_field(size_file, mesh, node_h)
        new_mesh = generate(design, freq, backend=backend, size_field=size_file)
    except Exception as exc:                           # pragma: no cover
        log.warning("size-field remesh unavailable (%s); "
                    "falling back to uniform refinement", exc)
        from ..mesh.generator import target_size
        h, _ = target_size(design, freq)
        new_mesh = generate(design, freq, backend=backend,
                            size=h * (0.7 ** pass_no))
    finally:
        if size_file and os.path.exists(size_file):
            os.unlink(size_file)
    design.mesh = new_mesh
    return new_mesh


def adaptive_solve(design, setup, backend: str = "auto",
                   enabled: bool = True, cancel=None, on_pass=None) -> Tuple:
    """
    Run the adaptive passes and return the converged discretisation.

    Returns ``(mesh, dofmap, region_ops, boundary_terms, history)``.
    """
    from ..mesh.generator import generate
    from .driver import solve_frequency, _material_maps

    from .control import checkpoint
    checkpoint(cancel)
    cfg = design.config.adaptive
    order = setup.basis_order
    f0 = setup.frequency
    history: List[dict] = []

    if design.mesh is not None and not enabled:
        mesh = design.mesh                       # reuse a user-prepared mesh
    else:
        mesh = design.generate_mesh(f0, force=True, backend=backend)
    checkpoint(cancel)
    dm = DofMap(mesh, order)
    ops = assemble_regions(mesh, order, dm)
    bts = BoundaryTerms(mesh, dm, design)

    if not enabled or setup.max_passes <= 1:
        history.append(dict(**{"pass": 1, "tets": mesh.n_tets,
                               "dof": dm.n_dof, "delta_s": None}))
        return mesh, dm, ops, bts, history

    S_prev = None
    size_file = None
    converged = 0
    for p in range(1, setup.max_passes + 1):
        checkpoint(cancel)
        last = p == setup.max_passes
        S, z0, psols, flds, _, _ = solve_frequency(
            design, mesh, dm, ops, bts, f0, save_field=not last)
        dS = None if S_prev is None else float(np.max(np.abs(S - S_prev)))
        history.append({"pass": p, "tets": mesh.n_tets, "dof": dm.n_dof,
                        "delta_s": dS})
        log.info("adaptive pass %d: %d tets, %d DOF, dS = %s",
                 p, mesh.n_tets, dm.n_dof,
                 "--" if dS is None else f"{dS:.5f}")
        S_prev = S
        if on_pass is not None:
            try:
                on_pass(mesh, dm, f0, S, z0, psols, flds, list(history))
            except Exception:                               # noqa: BLE001
                log.debug("partial-result hook failed", exc_info=True)
        if dS is not None and dS <= setup.delta_s and p >= setup.min_passes:
            converged += 1
            if converged >= max(int(getattr(setup, 'min_converged', 1)), cfg.min_converged_passes):
                log.info("adaptive solution converged (dS = %.5f <= %.5f)",
                         dS, setup.delta_s)
                break
        else:
            converged = 0
        if p == setup.max_passes:
            log.warning("adaptive limit reached without meeting delta_S "
                        "(last dS = %s)", dS)
            break

        checkpoint(cancel)
        # ---- refine -------------------------------------------------
        eps, mu = _material_maps(design, mesh, f0)
        x = flds[0].x
        err = element_error(mesh, dm, x, f0, lambda r: mu.get(r, 1.0 + 0j))
        mesh = remesh_from_error(design, mesh, err, f0, backend, p,
                                 getattr(setup, 'refinement', None))
        dm = DofMap(mesh, order)
        with timed(log, f"re-assembling pass {p + 1}"):
            ops = assemble_regions(mesh, order, dm)
            bts = BoundaryTerms(mesh, dm, design)

    return mesh, dm, ops, bts, history


__all__ = ["adaptive_solve", "element_error", "size_field_from_error",
           "remesh_from_error"]

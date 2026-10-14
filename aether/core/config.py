"""
Global solver configuration -- one dataclass that every kernel reads.

Defaults are chosen to mirror the usual out-of-the-box "driven modal" setup so
that a first-time user gets comparable accuracy without tuning anything.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field, asdict
from typing import Literal, Optional


@dataclass
class MeshSettings:
    """Initial-mesh and adaptive-refinement controls."""
    lambda_refinement: float = 0.25      # target h = lambda_min * this
    min_elements_per_wavelength: float = 4.0
    curvature_angle_deg: float = 22.5
    max_element_size: Optional[float] = None   # [m]; None -> from lambda
    min_element_size: Optional[float] = None
    surface_deviation: Optional[float] = None
    order: int = 2                       # gmsh element order for geometry
    optimize: bool = True
    algorithm3d: int = 1                 # 1=Delaunay, 4=Frontal, 10=HXT
    algorithm2d: int = 6                 # 6=Frontal-Delaunay
    growth_rate: float = 1.5


@dataclass
class AdaptiveSettings:
    """Adaptive-pass loop (Warps: 'Solution Setup -> Adaptive Solutions')."""
    enabled: bool = True
    max_passes: int = 6
    min_passes: int = 1
    min_converged_passes: int = 1
    delta_s: float = 0.02                # max |dS| between consecutive passes
    refinement_fraction: float = 0.30    # fraction of elements refined per pass
    error_metric: Literal["residual", "field_jump", "energy"] = "field_jump"


@dataclass
class SolverSettings:
    """Linear-algebra backend selection."""
    linear_solver: Literal["auto", "direct", "iterative"] = "auto"
    direct_backend: Literal["auto", "umfpack", "superlu", "pardiso"] = "auto"
    iterative: Literal["gmres", "bicgstab"] = "gmres"
    tol: float = 1e-8
    maxiter: int = 3000
    restart: int = 120
    preconditioner: Literal["ilu", "jacobi", "none"] = "ilu"
    ilu_drop_tol: float = 1e-4
    ilu_fill_factor: float = 12.0
    direct_threshold_dof: int = 400_000  # above this, prefer iterative
    threads: int = int(os.environ.get("AETHER_THREADS", "0")) or os.cpu_count() or 1


@dataclass
class SweepSettings:
    """Frequency-sweep strategy."""
    kind: Literal["discrete", "fast", "interpolating"] = "discrete"
    rom_order: int = 12                  # Krylov moments for 'fast' (PRIMA/AWE)
    interp_tol: float = 1e-3
    interp_max_points: int = 100
    save_fields: bool = False


@dataclass
class PortSettings:
    """Wave-port / lumped-port modal analysis."""
    num_modes: int = 1
    deembed: bool = False
    renormalize_to: Optional[float] = None    # Ohm; None -> keep modal Z
    impedance_definition: Literal["pi", "pv", "vi"] = "pi"
    integration_line_required: bool = False
    eigen_tol: float = 1e-10
    eigen_maxiter: int = 500


@dataclass
class Config:
    """Top-level configuration object attached to every :class:`Design`."""
    mesh: MeshSettings = field(default_factory=MeshSettings)
    adaptive: AdaptiveSettings = field(default_factory=AdaptiveSettings)
    solver: SolverSettings = field(default_factory=SolverSettings)
    sweep: SweepSettings = field(default_factory=SweepSettings)
    port: PortSettings = field(default_factory=PortSettings)
    basis_order: int = 1                 # 1 = Whitney(lowest), 2 = second order
    time_convention: Literal["ejwt", "emjwt"] = "ejwt"
    verbose: bool = True
    cache_dir: str = ".aether_cache"

    def to_dict(self) -> dict:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict) -> "Config":
        c = cls()
        for k, v in d.items():
            if not hasattr(c, k):
                continue
            cur = getattr(c, k)
            if hasattr(cur, "__dataclass_fields__") and isinstance(v, dict):
                for kk, vv in v.items():
                    if hasattr(cur, kk):
                        setattr(cur, kk, vv)
            else:
                setattr(c, k, v)
        return c


__all__ = ["Config", "MeshSettings", "AdaptiveSettings", "SolverSettings",
           "SweepSettings", "PortSettings"]

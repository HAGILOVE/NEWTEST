"""
Optimetrics-style optimisation: tune design variables until goals are met.

Warps Optimetrics asks for three things -- which variables may move and within
what range, what the response must do (the *goals*), and how to search.  This
module is that, on top of the dimension-expression rebuild that parameter
studies already use::

    res = ae.optimize(design,
                      variables={"L": ("15mm", "40mm")},
                      goals=[Goal("eigenfreq", target=10e9)],
                      method="nelder-mead", max_evals=40)
    res.best          # {'L': 0.0211...}   [SI]
    res.apply(design) # set the design variables to the optimum

Goals are one-sided *hinge* costs: a goal that is already satisfied costs
nothing, so a feasible point has total cost 0 and the search stops there
instead of polishing a number nobody asked about.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple, Union

import numpy as np

from .core.constants import to_si
from .parametric import ANGLE, D0, FREQ, LENGTH, Scope, rebuild

METHODS = ("nelder-mead", "pattern", "quasi-newton", "differential-evolution")
GOAL_KINDS = {
    "s_max": "max dB(S) over the band must stay below the target",
    "s_min": "min dB(S) over the band must stay above the target",
    "s_at": "dB(S) at one frequency must equal the target",
    "resonance": "frequency of the deepest dB(S11) notch in the band must "
                 "equal the target [Hz]",
    "eigenfreq": "frequency of an eigenmode must equal the target [Hz]",
    "peak_gain": "peak far-field gain must reach the target [dBi]",
}


class _Stop(Exception):
    """Budget exhausted or every goal met."""


@dataclass
class Goal:
    """
    One requirement on the response.

    ``kind`` is one of :data:`GOAL_KINDS`.  S-parameter goals address
    ``S(port, port2)`` (1-based) on the band ``f_start .. f_stop``;
    ``eigenfreq`` addresses mode ``mode`` (1-based).  ``weight`` scales the cost.
    """
    kind: str
    target: float = 0.0
    port: int = 1
    port2: int = 1
    f_start: Optional[float] = None
    f_stop: Optional[float] = None
    mode: int = 1
    weight: float = 1.0
    excitation: int = 0

    def __post_init__(self):
        if self.kind not in GOAL_KINDS:
            raise ValueError(f"unknown goal {self.kind!r}; use one of "
                             f"{', '.join(GOAL_KINDS)}")
        for a in ("f_start", "f_stop"):
            v = getattr(self, a)
            if v is not None and not isinstance(v, (int, float)):
                setattr(self, a, to_si(v, "frequency"))
        if self.kind in ("resonance", "eigenfreq") and \
                not isinstance(self.target, (int, float)):
            self.target = to_si(self.target, "frequency")
        if self.weight <= 0:
            raise ValueError("goal weight must be positive")

    # ------------------------------------------------------------------
    def _band(self, f: np.ndarray) -> np.ndarray:
        lo = f.min() if self.f_start is None else self.f_start
        hi = f.max() if self.f_stop is None else self.f_stop
        m = (f >= lo * (1 - 1e-12)) & (f <= hi * (1 + 1e-12))
        if not m.any():
            raise ValueError(
                f"goal band {lo / 1e9:g}-{hi / 1e9:g} GHz holds none of the "
                "solved frequencies")
        return m

    def evaluate(self, sol) -> Tuple[float, float]:
        """``(measured value, cost >= 0)`` for a finished solution."""
        w = self.weight
        if self.kind == "eigenfreq":
            if not sol.modes:
                raise ValueError("eigenfreq goal needs an eigenmode design")
            if not 1 <= self.mode <= len(sol.modes):
                raise ValueError(f"mode {self.mode} was not found")
            f = sol.modes[self.mode - 1].f
            return f, w * abs(f - self.target) / abs(self.target) * 100.0
        if self.kind == "peak_gain":
            g = sol.farfield(excitation=self.excitation).peak_gain_dbi()
            return g, w * max(0.0, self.target - g)
        sp = sol.sparams
        if sp is None:
            raise ValueError("S-parameter goal needs a driven solution")
        f = np.asarray(sp.freq)
        db = sp.db(self.port, self.port2)
        m = self._band(f)
        if self.kind == "s_max":
            v = float(db[m].max())
            return v, w * max(0.0, v - self.target)
        if self.kind == "s_min":
            v = float(db[m].min())
            return v, w * max(0.0, self.target - v)
        if self.kind == "s_at":
            k = int(np.argmin(np.abs(f - (self.f_start or f[0]))))
            return float(db[k]), w * abs(float(db[k]) - self.target)
        if self.kind == "resonance":
            idx = np.nonzero(m)[0]
            k = idx[int(np.argmin(db[idx]))]
            return float(f[k]), w * abs(f[k] - self.target) / abs(self.target) * 100.0
        raise AssertionError(self.kind)

    def describe(self) -> str:
        if self.kind == "eigenfreq":
            return f"mode {self.mode} frequency = {self.target / 1e9:g} GHz"
        if self.kind == "peak_gain":
            return f"peak gain >= {self.target:g} dBi"
        band = ""
        if self.f_start is not None:
            band = f" @ {self.f_start / 1e9:g}" + (
                f"-{self.f_stop / 1e9:g}" if self.f_stop else "") + " GHz"
        s = f"dB(S({self.port},{self.port2}))"
        return {"s_max": f"max {s} <= {self.target:g}{band}",
                "s_min": f"min {s} >= {self.target:g}{band}",
                "s_at": f"{s} = {self.target:g}{band}",
                "resonance": f"S11 notch at {self.target / 1e9:g} GHz{band}"
                }[self.kind]


@dataclass
class OptVariable:
    name: str
    low: float                    # SI
    high: float
    start: float
    dim: tuple = LENGTH

    def text(self, value: float) -> str:
        """The expression stored in the design for *value* (SI)."""
        unit = {LENGTH: "m", FREQ: "Hz", ANGLE: "rad"}.get(self.dim, "")
        return f"{value:.12g}{unit}"


@dataclass
class OptimizationResult:
    best: Dict[str, float]
    best_cost: float
    history: List[dict]
    method: str
    n_evals: int
    satisfied: bool
    stopped: str                     # "goals met" | "budget" | "converged" | "cancelled"
    runtime: float
    variables: List[OptVariable] = field(default_factory=list)
    goals: List[Goal] = field(default_factory=list)

    def expressions(self) -> Dict[str, str]:
        by = {v.name: v for v in self.variables}
        return {k: by[k].text(v) for k, v in self.best.items()}

    def apply(self, design) -> int:
        """Set the design variables to the optimum and rebuild the geometry."""
        vars_ = dict(design.variables)
        vars_.update(self.expressions())
        return rebuild(design, vars_)

    def summary(self) -> str:
        out = [f"optimisation [{self.method}]: {self.n_evals} solve(s), "
               f"{self.runtime:.1f} s, stopped: {self.stopped}",
               f"  best cost {self.best_cost:.6g}"
               f"{'  (all goals met)' if self.satisfied else ''}"]
        for v in self.variables:
            out.append(f"  {v.name} = {self.best[v.name] * 1e3:.6g} mm"
                       if v.dim == LENGTH else
                       f"  {v.name} = {self.best[v.name]:.6g}")
        return "\n".join(out)


# --------------------------------------------------------------------------


def _parse_variables(design, variables) -> List[OptVariable]:
    if not variables:
        raise ValueError("choose at least one variable to optimise")
    scope = Scope(design.variables)
    out = []
    for name, rng in dict(variables).items():
        if name not in design.variables:
            raise ValueError(f"design variable {name!r} is not defined")
        lo_t, hi_t = rng
        cur = scope.variable(name)
        lo, hi = scope.evaluate(lo_t), scope.evaluate(hi_t)
        if lo.dim != cur.dim or hi.dim != cur.dim:
            raise ValueError(f"{name}: limits must have the variable's "
                             "dimension")
        if not lo.value < hi.value:
            raise ValueError(f"{name}: the lower limit must be below the "
                             "upper limit")
        out.append(OptVariable(name, lo.value, hi.value,
                               min(max(cur.value, lo.value), hi.value),
                               cur.dim))
    return out


def _clone(design):
    from .model import Design
    work = Design(design.name)
    work.restore(design.snapshot())
    return work


def optimize(design, variables: Dict[str, Sequence], goals: Sequence[Goal],
             setup: Optional[str] = None, method: str = "nelder-mead",
             max_evals: int = 40, adaptive: bool = False,
             backend: str = "auto", cost_tol: float = 1e-9,
             callback: Optional[Callable[[dict], None]] = None,
             cancel=None) -> OptimizationResult:
    """
    Search the variable ranges for the point that best meets *goals*.

    The design itself is never modified: every trial runs on a copy.  Use
    :meth:`OptimizationResult.apply` to adopt the optimum.
    """
    from .fem.control import SolveCancelled
    if method not in METHODS:
        raise ValueError(f"unknown method {method!r}; use one of "
                         f"{', '.join(METHODS)}")
    goals = list(goals)
    if not goals:
        raise ValueError("define at least one goal")
    if not 2 <= int(max_evals) <= 1000:
        raise ValueError("maximum solves must be between 2 and 1000")
    vars_ = _parse_variables(design, variables)
    lo = np.array([v.low for v in vars_])
    hi = np.array([v.high for v in vars_])
    u0 = (np.array([v.start for v in vars_]) - lo) / (hi - lo)
    need_gain = any(g.kind == "peak_gain" for g in goals)
    design.get_setup(setup)

    t0 = time.perf_counter()
    history: List[dict] = []
    cache: Dict[tuple, float] = {}
    best = {"cost": math.inf, "x": None}
    state = {"stopped": "converged"}

    def point(u):
        return lo + np.clip(u, 0.0, 1.0) * (hi - lo)

    def cost(u) -> float:
        u = np.clip(np.asarray(u, float), 0.0, 1.0)
        key = tuple(np.round(u, 9))
        if key in cache:
            return cache[key]
        if cancel is not None and cancel.is_set():
            state["stopped"] = "cancelled"
            raise _Stop
        if len(history) >= max_evals:
            state["stopped"] = "budget"
            raise _Stop
        x = point(u)
        work = _clone(design)
        exprs = dict(work.variables)
        for v, xv in zip(vars_, x):
            exprs[v.name] = v.text(xv)
        rebuild(work, exprs)
        errs = work.validate()
        if errs:
            raise ValueError("a trial point is invalid: " + "; ".join(errs))
        try:
            sol = work.solve(setup=setup, backend=backend, adaptive=adaptive,
                             save_fields=need_gain, progress=False,
                             cancel=cancel)
        except SolveCancelled:
            state["stopped"] = "cancelled"
            raise _Stop
        rows, total = [], 0.0
        for g in goals:
            val, c = g.evaluate(sol)
            rows.append({"goal": g.describe(), "value": float(val),
                         "cost": float(c)})
            total += c
        rec = {"eval": len(history) + 1,
               "values": {v.name: float(xv) for v, xv in zip(vars_, x)},
               "cost": float(total), "goals": rows,
               "runtime": float(sol.runtime)}
        history.append(rec)
        cache[key] = total
        if total < best["cost"]:
            best["cost"], best["x"] = total, x.copy()
        if callback is not None:
            callback(rec)
        if total <= cost_tol:
            state["stopped"] = "goals met"
            raise _Stop
        return total

    n = len(vars_)
    try:
        if method == "nelder-mead":
            from scipy.optimize import minimize
            step = 0.2
            simplex = [u0] + [np.clip(u0 + step * np.eye(n)[i]
                                      * (1 if u0[i] + step <= 1 else -1), 0, 1)
                              for i in range(n)]
            minimize(cost, u0, method="Nelder-Mead", bounds=[(0, 1)] * n,
                     options=dict(initial_simplex=np.array(simplex),
                                  xatol=2e-4, fatol=1e-9,
                                  maxfev=int(max_evals) * 4))
        elif method == "pattern":
            _pattern_search(cost, u0)
        elif method == "quasi-newton":
            from scipy.optimize import minimize
            minimize(cost, u0, method="L-BFGS-B", bounds=[(0, 1)] * n,
                     options=dict(maxfun=int(max_evals) * 4, eps=0.02,
                                  ftol=1e-12, gtol=1e-9))
        else:
            from scipy.optimize import differential_evolution
            differential_evolution(cost, [(0, 1)] * n, maxiter=1000,
                                   popsize=max(4, min(8, max_evals // (2 * n) or 4)),
                                   tol=1e-8, polish=False, seed=1,
                                   x0=u0, init="sobol")
    except _Stop:
        pass
    if best["x"] is None:
        if state["stopped"] == "cancelled":
            # cancelled before the first solve finished: report that, with the
            # starting values standing in as "best" and no cost to claim
            return OptimizationResult(
                {v.name: v.start for v in vars_}, math.inf, history, method,
                0, False, "cancelled", time.perf_counter() - t0, vars_, goals)
        raise RuntimeError("the optimisation was stopped before any point was "
                           "solved")
    satisfied = best["cost"] <= cost_tol
    if state["stopped"] == "converged" and not satisfied \
            and len(history) >= max_evals:
        state["stopped"] = "budget"
    return OptimizationResult(
        {v.name: float(xv) for v, xv in zip(vars_, best["x"])},
        float(best["cost"]), history, method, len(history), satisfied,
        state["stopped"], time.perf_counter() - t0, vars_, goals)


def _pattern_search(cost, u0, step: float = 0.2, shrink: float = 0.5,
                    min_step: float = 5e-4) -> None:
    """Compass search: poll +/- step on every axis, move on improvement."""
    x = np.clip(np.asarray(u0, float), 0, 1)
    fx = cost(x)
    n = len(x)
    while step >= min_step:
        improved = False
        for i in range(n):
            for sgn in (1.0, -1.0):
                y = x.copy()
                y[i] = min(max(y[i] + sgn * step, 0.0), 1.0)
                if y[i] == x[i]:
                    continue
                fy = cost(y)
                if fy < fx - 1e-15:
                    x, fx, improved = y, fy, True
                    break
        if not improved:
            step *= shrink


__all__ = ["Goal", "OptVariable", "OptimizationResult", "optimize", "METHODS",
           "GOAL_KINDS"]

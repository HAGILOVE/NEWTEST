# Aether-EM — HFSS Analysis and Engineering Design

This document is the design record: what Ansys HFSS actually does, which of
those things matter, and how each one is realised in this code base.

---

## 1. What HFSS is, functionally

HFSS is not "a Maxwell solver" — it is a **pipeline** with seven stages, each
of which is a substantial piece of engineering. Reproducing HFSS means
reproducing the pipeline, not just the PDE.

```
 ┌──────────────┐   ┌────────┐   ┌──────────┐   ┌───────┐   ┌────────┐   ┌────────────┐   ┌───────────┐
 │ Parametric   │→ │ Mesh   │→ │ Material │→ │ Port  │→ │ Linear │→ │ Adaptive   │→ │ Post-     │
 │ solid model  │   │ (tet)  │   │ + BC     │   │ modes │   │ solve  │   │ refinement │   │ processing│
 └──────────────┘   └────────┘   └──────────┘   └───────┘   └────────┘   └────────────┘   └───────────┘
   ACIS kernel      Delaunay/     eps,mu,sigma   2-D eigen   sparse LU    ΔS criterion    S-params,
   history tree     advancing     PEC/IBC/ABC    problem     multi-RHS    error indicator fields, far field
                    front
```

### 1.1 The numerics HFSS actually uses

| Aspect | HFSS | Why it is that way |
|---|---|---|
| Formulation | E-field double-curl (vector Helmholtz), frequency domain | Directly yields S-parameters; no time-stepping stability limit |
| Elements | Tetrahedra with **curl-conforming (Nédélec) vector basis** | Enforces `n×E` continuity and `n·D` jump — the actual physics at a material interface. Nodal elements produce *spurious modes*; edge elements do not |
| Orders | 0.5 (Whitney), 1.5, 2.5 ("mixed order") | Trade accuracy per unknown against matrix size |
| Ports | 2-D modal eigen-analysis on the port cross-section | Gives an exact, reflectionless termination for each mode |
| Solve | Sparse direct (multi-frontal) or iterative, one factorisation per frequency reused across excitations | N ports cost one factorisation, not N |
| Convergence | Adaptive passes until `max|ΔS| < ΔS_target` | The user does not have to know mesh theory |
| Sweeps | Discrete / Fast (model-order reduction) / Interpolating | 500 frequency points must not cost 500 full solves |

### 1.2 Why edge elements are non-negotiable

The physical electric field is tangentially continuous and normally
discontinuous across a dielectric boundary. A nodal (Lagrange) vector basis
forces *all three* components continuous, which is wrong, and the discrete
operator then acquires a large null space that pollutes the spectrum with
non-physical "spurious modes". Whitney edge functions

```
W_ab = λ_a ∇λ_b − λ_b ∇λ_a ,   DOF = ∮_edge E·dl
```

reproduce exactly the right continuity, and their gradients span the discrete
null space of the curl operator cleanly. Every serious full-wave FEM code —
HFSS included — is built on them. Aether is too.

---

## 2. Module map

| HFSS concept | Aether module | Notes |
|---|---|---|
| Modeler / history tree | `aether.geometry.primitives` | Symbolic op-tree; serialisable, replayable, exportable |
| ACIS kernel | `aether.geometry.kernel` (OpenCASCADE via gmsh) | Real BRep, not facets |
| Material manager | `aether.core.materials` | Debye / Drude / Lorentz / Djordjevic-Sarkar / tabulated |
| Initial + adaptive mesh | `aether.mesh.generator`, `aether.fem.adaptive` | λ-based seeding, error-indicator size field |
| Boundaries | `aether.model.Boundary`, `aether.fem.boundary` | PEC, PMC, IBC, finite conductivity, radiation, lumped RLC |
| Excitations | `aether.model.WavePort/LumpedPort`, `aether.fem.ports` | 2-D modal eigenproblem, integration lines |
| Solution setup | `aether.model.Setup`, `aether.fem.driver` | ΔS convergence, sweeps |
| Solver | `aether.fem.assembly`, `aether.fem.linalg` | Region-blocked assembly, factorise-once/solve-many |
| Fields / reports | `aether.fem.fields`, `aether.post.*` | VTK, Touchstone, CSV, HTML, far field |
| `.aedt` project file | `aether.io.aedt` | Byte-exact round trip |

---

## 3. Design decisions, and what each buys

### 3.1 Geometry is a symbolic tree, not a kernel handle

`Box`, `Cylinder`, boolean nodes and transforms are recorded as data. The tree
can be replayed into OpenCASCADE, tested analytically with
`geometry.implicit.contains` (no CAD kernel needed), **and serialised into real
HFSS primitive commands** on export. That last point is why an Aether model
round-trips through `.aedt` as parametric geometry instead of as a dead mesh.

### 3.2 Boundary conditions are attached geometrically, not by face id

HFSS stores boundaries against ACIS face ids. Those ids are meaningless outside
a live modeller session and they change when the model is re-meshed. Aether
uses **selectors** — predicates on `(centroid, normal)` — so an assignment
survives remeshing, adaptive passes, and a change of mesh backend. This is
also what allows adaptive refinement to remesh from scratch each pass instead
of degrading one mesh by repeated bisection.

### 3.3 Assembly is blocked by material region

`S` and `T` are assembled once per region with the material factored out:

```
A(f) = Σ_r (1/μ_r(f)) S_r  −  k0(f)² Σ_r ε_r(f) T_r   + boundary terms
```

A 500-point sweep therefore re-scales and re-sums pre-built sparse blocks; the
mesh is never touched again, and dispersive materials cost nothing extra.

### 3.4 The port eigenproblem is reduced before it is solved

The natural mixed (edge + nodal) port pencil is **singular** — the `Ẽz` columns
of the mass side vanish, producing a cloud of infinite eigenvalues that a
shift-invert Arnoldi iteration mistakes for physical modes. Aether eliminates
`Ẽz` analytically (a Schur complement) and solves a regular pencil of half the
size. This was not a performance decision: without it the solver silently
returned spurious modes on fine port meshes.

### 3.5 Mode polarity is pinned deterministically

An eigenvector is defined only up to a sign, and that sign lands directly in
`S21`. Two ports of the same uniform line will disagree by exactly 180° unless
polarity is fixed. Aether uses the integration line when there is one, and
otherwise orients the mean transverse field's dominant Cartesian component
positive — reproducible across meshes, frequencies and ports.

### 3.6 PEC bodies cost zero unknowns

Solids whose material is PEC (or that are flagged `solve_inside=False`) have
their elements removed from the solution volume; the exposed faces become model
boundary and pick up the perfect-E condition. This is HFSS's "do not solve
inside", and it is why a model full of metal is not a model full of unknowns.

### 3.7 `.aedt` fidelity: raw preservation plus structured editing

Every parsed statement keeps its exact source text. Serialising a node that was
not modified re-emits those bytes verbatim, so

```
write(parse(f)) == f       # byte for byte, verified in CI
```

Editing a property marks only that statement dirty. The consequence is that
`update` mode cannot lose mesh operations, optimetrics setups, report
definitions or field overlays — because it never rewrites them.

---

## 4. What is deliberately *not* claimed

Honesty about limits is part of the design.

* **Face ids do not survive.** A boundary stored only as `Faces=[17,18]` cannot
  be re-attached to geometry from the text file alone; the ACIS ids exist only
  inside a modeller session. Aether reports these in `ImportReport.unresolved`
  rather than guessing. Object-based assignments (`Objects=[...]`) *are*
  re-attached, and Aether's own selectors round-trip exactly.
* **`.sat` / `.sab` (ACIS) cannot be read.** It is a proprietary Spatial
  format that OpenCASCADE does not support. Export STEP from the modeller.
* **Swept/lofted/blended history is not replayed** on import — the create
  commands Aether understands are listed in `io/aedt/translate.py`. Everything
  else is reported, not silently dropped. STEP import covers those bodies.
* Aether writes a structurally correct AEDT tree; **compatibility with a given
  Ansys release should be verified against that release**, since the schema
  evolves between versions.

---

## 5. Verification strategy

Numerical code that is not checked against closed-form answers is decoration.
The test suite compares against analytic results only — never against stored
output of this code:

| Test | Analytic reference |
|---|---|
| Quadrature | exact integrals of barycentric monomials to degree 5 |
| Whitney basis | `∮_edge W_e·dl = δ_ef` |
| Order-2 basis | exact reproduction of every linear vector field |
| Trace identity | triangle basis == tangential trace of the tet basis |
| WR-90 modes | `f_c = c/2·√((m/a)²+(n/b)²)`, `β=√(k0²−k_c²)`, `Z_TE = η0/√(1−(f_c/f)²)` |
| Below cutoff | `α = √(k_c²−k0²)` |
| Uniform guide | `S11→0`, `S21 = e^{−jβL}` |
| Shorted guide | `S11 = −e^{−2jβL}`, `|S11| = 1` |
| Lossy fill | `α = k0²·tanδ/(2β)` |
| Coax | `β = k0`, `Z_wave = η0`, `Z_pv = (η0/2π)ln(b/a)` |
| Parallel plate | `Z0 = η0·h/w`; mismatch `|Γ| = 1/3` |
| Lossless iris | `|S11|²+|S21|² = 1` to 1e-6, monotone in slot width |

See `docs/VALIDATION.md` for measured numbers.

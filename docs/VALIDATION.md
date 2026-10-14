# Validation

Every figure below is a comparison against a **closed-form** result, produced
by the test suite in `tests/`. Nothing is compared against stored output of
this code.

## 1. WR-90 rectangular waveguide (a = 22.86 mm, b = 10.16 mm)

Port modal solution at 10 GHz, 1 317-element mesh, order 1:

| Quantity | Analytic | Aether | Error |
|---|---|---|---|
| TE10 cutoff | 6.5571 GHz | 6.5600 GHz | 0.04 % |
| TE10 β at 10 GHz | 158.238 rad/m | 158.187 rad/m | 0.03 % |
| TE10 wave impedance | 498.98 Ω | 499.14 Ω | 0.03 % |
| TE20 cutoff | 13.1143 GHz | 13.1213 GHz | 0.05 % |
| TE01 cutoff | 14.7536 GHz | 14.7520 GHz | 0.01 % |
| α at 5 GHz (evanescent) | 88.91 Np/m | 89.21 Np/m | 0.34 % |

## 2. Mesh and order convergence

20 mm of WR-90 at 10 GHz; the error is in the insertion phase of `S21` against
`e^{−jβL}`.

| h | tets | order 1 \|S11\| | order 1 phase err | order 2 \|S11\| | order 2 phase err |
|---|---|---|---|---|---|
| 8.0 mm | 301 | 7.4e−2 | −7.309° | 6.3e−4 | −0.004° |
| 5.0 mm | 542 | 3.1e−2 | −1.012° | 3.6e−4 | +0.037° |
| 3.0 mm | 1 302 | 2.1e−3 | −0.454° | 2.9e−5 | +0.008° |
| 2.0 mm | 3 399 | 4.2e−4 | −0.231° | 3.1e−6 | +0.002° |

Order 1 shows the expected `O(h²)` phase convergence; order 2 is two to three
orders of magnitude more accurate on the same mesh.

## 3. Adaptive passes

WR-90 through-line, ΔS target 0.002:

| Pass | Tetrahedra | DOF | ΔS |
|---|---|---|---|
| 1 | 301 | 467 | — |
| 2 | 2 047 | 3 036 | 0.12127 |
| 3 | 8 103 | 11 240 | 0.00377 |
| 4 | 29 715 | 38 972 | **0.00178** ✓ |

Converged result: `S11 = −73.4 dB`, `|S21| = 1.0000`, largest singular value
`1.000000` (passive).

## 4. Coaxial line (50 Ω in air, a = 1 mm, b = 2.3023 mm)

| Quantity | Analytic | Aether |
|---|---|---|
| β / k0 | 1.000000 | 1.000000 |
| cutoff | 0 (TEM) | < 0.1 GHz |
| wave impedance | 376.730 Ω | 376.730 Ω |
| line impedance `Z_pv` | 50.000 Ω | 50.19 Ω (0.4 %) |
| `S21` phase over 10 mm | −120.083° | −120.60° |
| `S11` | 0 | −56.6 dB |

## 5. Parallel-plate line with lumped ports (h = 1 mm, w = 10 mm)

`Z0 = η0·h/w = 37.673 Ω` exactly.

| Case | Analytic | Aether |
|---|---|---|
| matched, `S11` | 0 | −59.8 dB |
| matched, `\|S21\|` | 1 | 0.9999995 |
| matched, `S21` phase over 20 mm | −120.083° | −120.094° |
| `2·Z0` termination, `\|Γ\|` | 0.33333 | 0.3333 |

## 6. Lossy fill

WR-90, 20 mm, `ε_r = 1`, `tanδ = 0.02`, 10 GHz.
Analytic `α = k0²·tanδ/(2β)`; the computed `|S21|` matches `e^{−αL}` within
5 %, and the network remains passive with `Σ|S|² < 1`.

## 7. Internal PEC sheet — inductive iris

Zero-thickness perfect-E plate with a centred slot, 30 mm WR-90, 10 GHz:

| Slot width | \|S11\| | \|S21\| | `\|S11\|²+\|S21\|²` |
|---|---|---|---|
| 16 mm | 0.2482 | 0.9687 | 1.000000 |
| 12 mm | 0.5927 | 0.8054 | 1.000000 |
| 8 mm | 0.9163 | 0.4006 | 1.000000 |
| 0 mm (closed) | 1.0000 | < 1e−9 | 1.000000 |

Monotone in slot width and lossless to 1e−6, as an inductive iris must be.

## 8. Iris-coupled cavity (single-pole bandpass)

Two irises, 20 mm cavity, 11 mm slots: transmission peak at 9.0123 GHz with
`|S21| = 0.9953`, 3 dB bandwidth 249 MHz (loaded Q ≈ 36), and a worst-case
energy-balance error of `5.4e−14`.

## 9. File-format integrity

| Check | Result |
|---|---|
| `.aedt` parse → write | byte-identical (incl. blank lines, wrapped values, escaped quotes, BOM/CRLF) |
| edit one property | exactly one line differs |
| Design → `.aedt` → Design → `.aedt` | zero differing lines |
| Touchstone v1/v2 × RI/MA/DB × 1–4 ports | max error < 1e−9 |
| `.s2p` column-major convention | verified against the literal byte order |
| STEP export → import → mesh | volume matches to 1e−6 relative |

## 10. Round-trip fidelity of CSG and ports

Boolean geometry, transform stacks, integration lines and lumped-port
parameters are checked by *behaviour*, not by bounding box — a subtraction
flattened into a union still meshes and still solves, it is just a different
structure:

| Check | Result |
|---|---|
| coax `Cylinder − Cylinder` → `.aedt` → back | point membership identical (centre outside, annulus inside) |
| rotate + translate stack | membership and bbox identical |
| lumped port impedance / direction | 37.673 Ω and 75 Ω, `(0,0,1)` and `(0,1,0)` preserved |
| wave-port integration line | endpoints preserved to 1e−12 |

## 11. Starter templates (`aether new`)

| Template | Solve time | Result |
|---|---|---|
| `microstrip` | 0.9 s | S11 < −46 dB, \|S21\| > 0.9999, passive, reciprocal, `z0 = 37.67 Ω` |
| `coax` | 8 s | S11 < −50 dB, \|S21\| = 1.00000, `Zpv = 51.2 Ω` (coarse default mesh) |
| `waveguide` | 16 s | S11 < −38 dB, \|S21\| > 0.9999, 3 adaptive passes |

## 12. Graphical workspace

The desktop UI is tested twice: the command layer and HTTP server headless,
and the real interface driven in Chromium.

| Layer | Checks |
|---|---|
| API (`tests/test_gui.py`) | 28 — draw/boolean/transform/property commands, all five selector kinds, boundary and port parameters reaching the model, setup and sweep editing, validation, template loading, meshing **from a worker thread**, a full solve with passivity/reciprocity assertions, field-overlay buffers, the scripting console, and the server (token rejection, error reporting, path-traversal, message stream) |
| Browser (`tests/test_gui_browser.py`) | 43 — the whole workflow clicked through: ribbon, dialogs, tree, WebGL framebuffer is genuinely painted, mesh overlay, solve, S-parameter chart, port-mode table, scripting console, view controls, dark theme, and **zero JavaScript errors for the entire session**; ray picking; automatic name suggestions; the file browser navigating a real directory tree and saving a project that reparses; the edit tools driven from the menu and the keyboard (duplicate, copy/paste, undo/redo, arrange) with the object count asserted after each; and a CAD import that reports the file's contents and lands at the declared size; the file browser opened **from inside** the Import dialog, returning to it with the path filled in; an imported body's unit changed from the property grid and from Replace CAD Source; the three selection modes from toolbar and keyboard; a face picked in the WebGL viewport feeding a boundary assignment, a mesh operation and a face sweep; per-object colour, transparency and visibility from the property grid; the right-click menus in the viewport and the tree, including running a command from one; a picked face measured on screen; two faces showing a gap with its dimension label; a box drawn from two clicked points; boundaries drawn in the viewport with their legend; the file browser listing and filtering DXF; and an assembly offering to split, and splitting |
| DXF (`tests/test_dxf.py`) | 16 — outlines at the declared size, a flattened circle within 0.3 % of its true area, layers, arc bulges, POLYLINE entities, the unit override, binary DXF refused with an explanation, and a drawing imported as a sheet with its hole cut then swept into 35 µm of copper |
| Robustness (`tests/test_robustness.py`) | 20 — an unparseable statement kept verbatim; a stray quote costing one line instead of the file; a damaged project still opening in the workspace; the CAD filter offering and applying DXF; every body of an assembly drawing and saving as itself; a twelve-body file read ≤ 4 times rather than 24; a non-ASCII path; an unreadable STEP explaining itself; bounded caches; and sheets taking the same properties, measurement and round trip as solids |
| Files & naming (`tests/test_gui_files.py`) | 28 — name generation and collision handling for objects, boundaries, ports, setups and sweeps; directory listing, filtering, hidden files, unreadable folders, breadcrumbs, places, save-path resolution; the full save → browse → reopen path the dialogs take |
| Edit & CAD (`tests/test_gui_edit.py`) | 40 — move/rotate/mirror on one and many objects with the resulting bounding boxes checked; clipboard round trip and independence of the copy; the three duplicate patterns including the total-count convention and attach-to-original; undo/redo across draw, move and delete, with a deleted object's boundary still pointing at the restored object; a failed command leaving no history entry; CAD import at the declared unit and at each override (mm/cm/m/inch); an imported body saved and reopened after its source file was moved away, with unit and transform intact; a missing source reported rather than dropped; and Replace CAD Source editing the object in place, with its material, transform and boundary references surviving |
| Selection, meshing & face modelling (`tests/test_selection.py`) | 55 — face counts from both tessellation paths; a boundary on a picked face tagging that face's exact area and no other, at two different mesh sizes; two faces assigned as one boundary; mesh operations on objects and on faces, with locality checked against the opposite face; sweep and move faces including undo, the object keeping its identity and boundaries, a project-file round trip; a face of an imported STEP body swept; a curved face refused; an operation that cannot build leaving the body untouched; a sweep not reaching a neighbouring body's identical face; the true extent of an imported curved part; per-object colour, transparency and visibility; a three-body STEP importing as three pickable parts (and healing no longer welding it into one shell); edge, face, gap and object measurements including offset faces where the centre distance is the wrong answer; and assignments reported on the faces they cover without a mesh |
| Native HFSS files (`tests/test_aedt_native.py`) | 29 — a desktop-written project with embedded Parasolid payloads: parsed, byte-exact round trip, payloads verbatim after an edit, the design found under its solver-specific block name, operand parts excluded, boundaries and ports resolved through body ids, face-id boundaries reported, native bodies extracted and repointable at a STEP export; values in unanticipated units ('20cel', pF, nH, %) evaluated instead of aborting the load; one unreadable property costing only its own item; and the workspace stating why a project of native bodies shows nothing |
| Dead-entry sweep | every menu item and ribbon button clicked — **123 entry points, none broken**, plus 7 correctly greyed out (undo, redo and the clipboard on an empty design) |

Measured on the shipped templates through the UI: initial mesh 678 tetrahedra
in 0.11 s, a 10-point lumped-port solve in 0.1 s, `S11 < −46 dB`,
`|S21| > 0.9999`, passive and reciprocal.

## 13. Test suite

```
$ pytest -q
411 passed
```

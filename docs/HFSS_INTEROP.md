# HFSS / AEDT interoperability

## 1. The `.aedt` file

An AEDT project is a tab-indented, nested, plain-text block tree:

```
$begin 'AnsoftProject'
	FileVersion(1, 0)
	Created='Tue Sep 02 09:11:04 2026'
	$begin 'Desktop'
		Version(2024, 2)
		InfoStr='It\'s fine'
		List=[1, 2, 3.5]
	$end 'Desktop'
$end 'AnsoftProject'
```

Statement forms Aether parses and re-emits:

| Form | Example | Python value |
|---|---|---|
| string | `Name='Box1'` | `str` (escapes resolved) |
| number | `Count=12`, `F=1.5e-3` | `int` / `float` |
| boolean | `SolveInside=true` | `bool` |
| list | `List=[1, 2, 3]` | `list` |
| call | `Version(2024, 2)` | `Call('Version', [2024, 2])` |
| counted array | `Pts[3: 'a','b','c']` | `Counted` |

`.aedtz` (the zipped project) is handled transparently by the same API.

### 1.1 Byte-exact round trip

```python
from aether.io.aedt.tree import AedtDocument
doc = AedtDocument.parse("project.aedt")
doc.write("copy.aedt")          # identical bytes, verified in CI
```

Three things make this hold:

* every logical statement caches its exact source text and re-emits it unless
  modified;
* logical lines are reassembled across physical lines when brackets, quotes or
  parentheses are still open, so HFSS's wrapped dataset entries survive;
* encoding, BOM presence and newline style (`\n` vs `\r\n`) are detected and
  reproduced — a UTF-8 file never acquires a BOM on the way out.

`$begin` / `$end` are recognised only outside quoted strings, so a property
whose value contains the literal text `$end` does not truncate the file.

Check any project from the command line:

```
aether validate project.aedt
```

### 1.2 Editing without collateral damage

```python
doc.root.path("Desktop").set("Version", Call("Version", [2025, 1]))
doc.write("out.aedt")           # exactly one line differs
```

`update` mode uses this for whole models:

```python
design, report = aether.open_hfss("project.aedt")
design.get_setup("Setup1").frequency = 12e9
aether.save_hfss(design, "project_v2.aedt", mode="update")
```

Mesh operations, optimetrics, report definitions, field overlays and design
settings are untouched **because they are never rewritten**, not because they
were carefully re-serialised.

## 2. What transfers between the models

| HFSS | Aether | Direction |
|---|---|---|
| model units | `Design.units` | both |
| project / design variables | evaluated into geometry | import |
| materials (ε, μ, tanδ, σ, ρ, k) | `Material` | both |
| Box, Cylinder, Sphere, Cone, Torus, Rectangle, Polyline | primitives | both |
| Move / Rotate / Scale history | transform stack | both |
| Perfect E/H, Radiation, Finite Conductivity, Impedance, Lumped RLC, Symmetry | `Boundary` | both |
| Wave Port (modes, de-embed, renormalise, integration line) | `WavePort` | both |
| Lumped Port (impedance, direction) | `LumpedPort` | both |
| Setup (frequency, ΔS, passes, basis order) | `Setup` | both |
| Sweeps (LinearCount / LinearStep / LogScale / SinglePoint) | `FrequencySweep` | both |

## 3. What does not transfer, and why

**Boundaries stored as kernel face ids.** HFSS writes
`Faces=[17, 18]` — indices into an ACIS session that no longer exists. There is
no way to recover which surface that was from the file alone. Aether lists
these in `ImportReport.unresolved` instead of guessing:

```
AEDT import report for design 'HFSSDesign1'
  UNRESOLVED (1):
    - boundary 'rad1' (Radiation): attached to kernel face ids [17, 18];
      re-assign it with a selector
```

Re-attach it explicitly:

```python
design.assign_radiation("rad1", aether.BoundingBoxFaceSelector("+z"))
```

Boundaries written as `Objects=['air']` **are** re-attached automatically, and
Aether's own selectors round-trip exactly, because they are stored in an
auxiliary `$begin 'AetherSelector'` block that HFSS ignores.

**`.sat` / `.sab` bodies.** ACIS is a proprietary Spatial format that
OpenCASCADE cannot read. Export the body as STEP AP214 from the modeller
(`Modeler → Export`) and import that; Aether tells you so explicitly rather
than failing obscurely.

**Unsupported creation commands** (sweeps along a path, lofts, blends, imported
bodies) are reported per part. The STEP route covers all of them.

## 4. Touchstone

Read and write `.s1p … .snp` (v1) and `.ts` (v2), in `RI`, `MA` and `DB`, with
any frequency unit and per-port reference impedances.

Two details other readers get wrong and this one does not:

* **a v1 `.s2p` is column-major** (`S11 S21 S12 S22`) while every other port
  count is row-major — getting this wrong silently swaps `S12` and `S21`;
* **v1 wraps long records over several lines with no continuation marker**, so
  records must be reassembled by counting values, not by counting lines.

```python
sp = aether.read_touchstone("meas.s2p")
sp.renormalize(50.0).write_touchstone("out.ts", version=2.0, fmt="MA")
```

A wave port's impedance is frequency-dependent; Touchstone 1.0 cannot express
that, so writing v1 emits a warning and stores the first-point value.
Renormalise to a constant impedance first, or write v2.

## 4a. Reading a project the HFSS desktop actually wrote

A project saved from the modeller does not look like the tidy text tree the
format description suggests, and four separate things about it will each stop
a naive reader dead. All four are handled:

**Embedded binary bodies.** A project built in the modeller stores its solids
as Parasolid bodies, and carries them *inside* the project file as
length-prefixed blobs: `$begin 'x_b'`, a path, `BIN000000006179`, then exactly
that many bytes. Those bytes contain quotes, brackets and literal `$end`
sequences, so a line-oriented parser walks straight into them and reports
`unterminated block 'x_b'`. The payload is now taken by its declared length and
kept verbatim, which also keeps the round trip byte-exact — a 780 kB project
with 23 embedded bodies rewrites to the same bytes it was read from.

**The design block's name.** The desktop writes `$begin 'HFSSModel'`; scripted
and exported projects write `$begin 'Design'`. A reader that knows only one
finds no designs at all in half the files it is handed. Both are recognised.

**Where the boundaries live.** The desktop nests them one level down, in
`BoundarySetup ▸ Boundaries`; older projects list them directly under
`BoundarySetup`. Both layouts are read.

**Boundaries attached to body ids.** HFSS writes `Objects(1255)`, not a name.
The part ids are collected while the geometry is read and the assignments
resolved through them, so `PerfE` and `Wave Port` land on the right bodies.
Boundaries given only by *face* ids (`Faces(145)`) still cannot be placed —
those ids describe surfaces that exist only inside the modeller session — and
are reported as unresolved so they can be re-assigned by picking the faces.

**Values in units nobody anticipated.** Every part in a desktop-written project
carries `ReferenceTemperature='20cel'`, and a project can hold powers,
currents, capacitances and percentages besides. An expression evaluator that
knows only lengths and frequencies hands `20cel` to Python's parser and gets
`invalid decimal literal` — which, raised from the middle of a project load,
cost the whole model. Any `<number><unit>` token is now understood: the units
that have an SI meaning are converted, temperatures are converted with their
offset, and an unrecognised suffix is taken as a bare number rather than a
syntax error. Beyond that, reading is *per item*: a boundary, port or setup
whose value still cannot be evaluated is skipped and listed in the report,
never allowed to abort the load.

**Damage costs only the damaged part.** A project file is written by someone
else's software, and it can contain things this reader has not seen. Three
levels of tolerance keep one oddity from costing the whole model:

* a **statement** that cannot be parsed is kept verbatim — the tree still
  holds it, the round trip is still byte-exact, and only that one value is
  unavailable;
* a **quoted value with no closing quote** ends at its own line. It used to be
  joined to every line that followed while the parser looked for the closing
  quote, so one stray apostrophe swallowed the rest of the file and the parse
  died thousands of lines away with `unterminated string near offset 0`. A
  value genuinely continues across lines only with the trailing backslash HFSS
  actually writes, in the base64 blocks;
* a **block** that does not close, or an `$end` naming the wrong block, is
  repaired: the reader unwinds to the block the `$end` names, or closes what is
  open at end of file, and records what it did. `parse_text(strict=True)` still
  raises, which is what the round-trip tests use.

**What comes back, and what does not.** Everything except the native geometry:
design name and units, variables, materials, the object list with names,
materials and solve-inside flags, boundaries, excitations, mesh and analysis
setups. Parasolid itself OpenCASCADE cannot read, so each native body is
written out of the project into `<project>.cad/` and created as an object
marked *needs a readable source*. The model therefore keeps its structure and
everything attached to those bodies, and each is completed by exporting STEP
from HFSS (Modeler ▸ Export ▸ .step) and pointing at it with
`Modeler ▸ Replace CAD Source…`.

## 5. Geometry interchange

| Format | Read | Write |
|---|---|---|
| STEP (`.step`, `.stp`) | yes (BRep, healed) | yes |
| IGES (`.iges`, `.igs`) | yes | yes |
| BREP | yes | yes |
| STL | yes (watertight → volume) | yes |
| DXF (`.dxf`) | yes (closed outlines → sheets) | no |
| ACIS (`.sat`, `.sab`) | no — export STEP instead | no |

Import applies OpenCASCADE shape healing (sew faces, fix small/degenerate
edges, make solids), which is the single most common reason an imported model
refuses to mesh.

**Units.** STEP and IGES store bare numbers and declare separately what they
mean; Aether works in metres. The declaration is read and applied (`SI_UNIT`,
`CONVERSION_BASED_UNIT('INCH')`, the IGES global-section unit), and can be
overridden per import — necessary for the files that declare wrongly and for
STL and OBJ, which declare nothing at all and are assumed to be millimetres.
Nothing is applied silently: the file is inspected before the import and its
solid count, face count, resulting extent in millimetres and the unit applied
against the unit declared are reported to the caller and to the message log.
Writing follows the same rule — STEP and IGES are written *in* millimetres and
declared as millimetres, so a file Aether exports reads back at the same size
in Aether, in HFSS and in any mechanical CAD system.

**Imported bodies in a project file.** An imported part is written as an
`ImportParameters` block carrying `SourceFile`, `ModelUnits`, `ScaleToM`,
`HealGeometry` and `EmbeddedFile`, and the source is copied into a
`<project>.cad` folder next to the project. Reading resolves the copy first and
the recorded absolute path second, so a project stays openable after it is
moved or handed on. A part whose source cannot be found is still loaded — with
its transforms, boundaries and ports — and reported in the import warnings
rather than dropped.

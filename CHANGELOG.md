# 1.8.0 — solver features Warps users expect, and a modeler that draws the way they do

**Solver**

- **Interpolating and Fast sweeps are real.** Both labels used to run a full solve at every frequency. *Interpolating* now fits one rational model (set-valued AAA) through adaptively chosen solves, probing the midpoint of every gap and confirming where the model moves fastest; *Fast* projects the full operator onto a reduced basis grown at the worst-residual frequency. An 81-point X-band sweep needs 20 full solves instead of 81 at the same accuracy (|dS| < 1e-3 by default; error tolerance and maximum solutions are per sweep). Sweeps shorter than 7 points are solved directly.
- **Eigenmode solver** (resonant frequency, Q, mode fields). The curl-free null space is projected out explicitly, so no spurious zero-frequency modes appear. Verified against analytic cavity resonances (0.004 % at second order), Q = 1/tan(d) for a lossy filling (exact), and Pozar's conductor Q for a copper cavity (0.24 %). Adaptive passes refine on mode movement. Radiation boundaries are rejected rather than solved badly.
- **Far field and antenna parameters.** Stratton-Chu transform rewritten (chunked, proper quadrature) and verified against the exact field of a Hertzian dipole (power 0.1 %, directivity 1.7638 vs 1.7609 dBi). Accepted power is taken from the field itself (`P_rad + P_diss`), so gain and efficiency do not depend on port normalisation; the power absorbed by the radiation boundary is reported beside the far-field power as a check on the air region. A half-wave dipole model gives 2.25 dBi (theory 2.15), a null on the axis, round H-plane and Zin = 69 ohm at the 2.95 GHz resonance.
- **Optimisation.** `ae.optimize` / Tools > Optimization: variables with ranges, goals (S-parameter in a band, notch frequency, eigenmode frequency, peak gain), Nelder-Mead, pattern search, L-BFGS-B or differential evolution. Every trial is a real solve on a copy; Apply best is one undo step.
- **Warps setup fields.** Minimum passes, minimum converged passes, refinement per pass, linear-step sweeps, edit setup / edit sweep; all round-trip through `.warp`.

**Bugs found and fixed on the way**

- `OuterSelector` ("all outer faces") also selected the surface of PEC bodies cut out of the solution volume, so a radiation boundary landed on antenna metal and the input resistance doubled. It now means the outside of the air region only.
- The direct solver ordered columns with COLAMD, which is for A^T A; the FEM matrix has a symmetric pattern. MMD_AT_PLUS_A is 85x faster at 8.7k unknowns.
- A mesh operation on a sheet passed its surface tag as a volume and aborted gmsh; Netgen optimisation segfaulted on small port sheets.
- `Circle` bounds were inflated along the axis; a failed multi-edit did not roll back `solve_inside`.

**Desktop**

- **Results:** E, H and the **surface current** on the metal, on the surfaces, on selected objects or on a cut plane; peak or any instant of the RF cycle with a phase slider and animation; dB scale; vector arrows. Radiation pattern report (polar / rectangular, antenna-parameter table, 3-D pattern), eigenmode table, and per-mode fields.
- **Time animation of every result.** Pick a frequency and press Animate: E, H, the surface current and the radiated field move through the RF cycle, with a speed control and a phase slider. Quantity *Far field* animates the instantaneous radiated |E| as a 3-D surface that breathes in and out (or shows static gain in dBi); *Component* X / Y / Z plots the signed instantaneous component, which is what shows a wave travelling or a charge sloshing. The frequency selector is always shown (greyed when only one frequency was saved).
- **The radiation boundary can be hidden** (Results > Show Radiation Boundary, and in the exported viewer). It surrounds the model and used to cover every field plot and the pattern; it is now off by default and faint when on.
- **Save As > three.js 3D viewer (\*.html).** One self-contained page (three.js r149 embedded, works from disk, no network) with the model (colours, transparency, per-object visibility, ports, boundaries, edges) and, for a solved design, the complex E / H / Js on surfaces and on a cut plane through each axis, the complex far field, the S-parameters and the antenna table. Because the stored data is complex, the page's phase slider, animation, |V| / X / Y / Z component, frequency and excitation selectors are arithmetic on the file, not baked frames. Also File > Export 3D Viewer (three.js)…, `export.threejs` over RPC, and `aether.gui.threejs.export(session, path)`.
- **PARDISO solver (large models, minutes -> seconds).** SuperLU is single-threaded with a weak ordering for 3-D meshes: a 35k-unknown second-order dipole did not finish in 18 minutes. With `pypardiso` installed (extra `fast`, installed by `run.py --setup`) the complex system is factorised as an equivalent real block system by MKL PARDISO in ~2 s (residual 2e-14, identical antenna results); without it the built-in SuperLU path is unchanged. `AETHER_LINEAR_BACKEND=superlu` turns it off.
- **Results are saved with the project and restored on open.** Saving a solved project writes `<project>.wres` beside it (mesh, S-parameters, port modes, saved fields; npz + JSON, no pickle). Reopening restores the solution, so reports, field plots, animation and far field are available without solving again. A SHA-256 of the project file ties the results to it: if the `.warp` was changed since, they are not loaded.
- **Results while the analysis runs.** A partial solution is published after every adaptive pass and every solved frequency; the Results commands work immediately and the open plot refreshes as points arrive. If the run fails or is cancelled, what was computed stays available.
- **Results list.** Under Results in the project tree every report and field plot is its own entry with its own settings (Y-axis form, traces, axis ranges, markers, field quantity, frequency). Clicking opens it as it was left; the Results menu adds a new one; right-click Duplicate / Rename / Delete.
- **Plots.** One interactive x/y plot engine fills the window at the real pixel size; X/Y min/max are editable, the wheel zooms about the cursor, dragging pans, double-click goes back to Auto. Clicking puts a marker (m1, m2 ...) on the nearest trace point; markers drag along their trace and a table gives X, Y and the difference from m1; "Marker to Peak / Min". The polar pattern's outer value and dB range are editable. Plot opacity and model opacity sliders let the antenna be seen inside its radiation pattern.
- **Lumped-port polarity.** The port field runs from the Ground end to the Signal end (Warps's integration line). The Assign Lumped Port dialog takes the direction and detects the two end points from the selected face (editable, with Swap); port properties and the context menu have Reverse Polarity and Edit Polarity; the 3-D view draws every lumped port's ground -> signal arrow. Reversing is one undo step and is saved in the `.warp`; it changes the sign of S21 between two ports.
- **Port polarity is picked with the mouse (Warps "New Line").** For lumped and wave ports: select the port face, press *New Line…*, click the **signal** end and then the **ground** end in the 3-D view (points snap to vertices and edge mid-points, an arrow follows the cursor), or press Tab and type the coordinates; *Swap* reverses it. The line runs signal → ground and the port's electric field points along it (field from + to −), which is the orientation the wave-port mode polarity rule (∫e·l̂ > 0) already used. **Behaviour change:** ports created with the two-face *Lumped / Wave Port (pick)* tools now run signal → ground (they ran ground → signal), so S21 between two such ports changes sign relative to 1.7.x; numbers of ports whose direction was given explicitly are unchanged, only the end labels in the dialogs follow the new convention.
- **Ports without coordinates: mark Signal and Ground, then Assign Port.** Right-click an object (or a picked face / edge) ▸ *Mark as Signal (+)* / *Mark as Ground (−)*, then right-click ▸ *Assign Lumped Port (auto)*, *Assign Wave Port (auto)* or *Assign Port (auto type)*. The gap axis, port plane, sheet size and signal → ground direction are worked out from the two conductors: a lumped sheet bridges the gap at the end of the signal line nearest the model boundary (width = the narrower conductor; a second port on the same line goes to the other end), a wave port is placed across the signal end with a window that covers the ground cross-section (or ~10 signal widths when the ground is not enclosed) and an integration line snapped to the facing conductor faces. *Auto type* picks a wave port when a conductor reaches the model boundary and a lumped port otherwise. Two selected objects offer a one-step *Lumped / Wave Port between the two selected* (first = signal). `portmarks.set / portmarks.clear / excitation.autoPort` over RPC; a gap over λ/10 gets a warning. Verified: two automatic wave ports on a straight microstrip give |S21| > 0.7, |S11| < 0.6.
- **Automatic ports follow the signal where it is fed (fix).** The first version sized the port from the *bounding box* of the whole signal object, so a patch with its feed line in one object got a 30 mm port on a 3 mm line, and a wide-ended taper got the wrong end. The planner now (1) finds the feed end as the end of the conductor closest to the model boundary, not the longest side of the box; (2) reads the signal's real outline at that end (the corners of the end face), so the lumped sheet is as wide as the line there and the wave-port window is 10 line widths, centred on the line; (3) clips the sheet to the ground it lands on; (4) bridges the closest gap, also for nested conductors (a coplanar line between grounds), where the bounding boxes do not separate; (5) feeds through the middle of a conductor that does not reach the boundary (dipole arms). *Port by Picking* and the Lumped / Wave Port dialogs use the same planner; with **two metals selected** the port commands open *Assign Port between two metals* (signal / ground selectors with Swap, Lumped / Wave / Automatic, and a live description of what will be built). Geometry tests cover a patch with feed, an off-centre strip, a tapered end, a ground narrower than the signal, dipole arms and a coplanar line.
- **Lumped RLC works as an element, with the right physics.** The boundary used to treat R in ohms as a sheet resistance (ohm per square), which is wrong by the aspect ratio of the sheet, and it loaded both tangential components. A sheet of width w and length L now carries Zs = Z · w / L and conducts only along its direction (shorter side by default, or X / Y / Z / the line between the two metals); the series / parallel combination of R, L and C is evaluated at each frequency. Checked against the analytic reflection of a parallel-plate line: R = Z0 matches (|S11| < 0.01), 2 Z0 reflects 1/3, a capacitor and series / parallel R-L-C match Γ = (Z − Z0)/(Z + Z0) including phase, and a Z0 sheet across a matched line gives S11 = −1/3, S21 = 2/3. Right-click ▸ *Assign Lumped RLC…* between two selected (or marked) metals builds the bridging sheet from the signal's width like an automatic port; values take engineering suffixes (`2.2n`, `0.5p`). Direction and series / parallel are saved in the `.warp`.
- **Snap to the model while drawing and moving.** While placing a point (Box / Rectangle / Cylinder / ... by points, Move by two points) the cursor jumps to a vertex, an edge middle or a face centre of any visible object within 12 px, and the hint names which one. After the first point the snapped point is projected onto the drawing plane; the first point also moves the plane to that feature. *Snap to model* in the draw panel turns it off.
- **Hide / Show** in the right-click menu of the viewport and the tree (Hide, Show, Hide Others, Show All) for the whole selection.
- **Files open solid.** After opening a project or importing CAD the parts are drawn opaque (air / vacuum / radiation regions stay see-through so the parts inside remain visible); a transparency set by hand afterwards is kept. The *Solid* toggle switches it off.
- **Much faster opening.** The display mesh was built for every body by the CAD kernel with an element size tuned to its thinnest dimension, so a 0.035 mm patch became 1300 triangles. A box, cylinder, cone, sphere or torus is now triangulated directly from its formula and flat faces of CAD bodies get no interior points. A 299-part project: geometry 22.8 s → 1.4 s and the viewport data 107 MB → 6.6 MB; a STEP of the same 299 bodies imports in 13 s instead of 19 s (6 s of that is the STEP reader itself).
- **Relative coordinate systems (Warps "Relative CS").** Draw ▸ Coordinate System ▸ *Relative CS…*: click a vertex, an edge mid-point or a face centre (all three now snap), or type an origin; the CS becomes the working one and every typed / displayed coordinate (drawing, ports, New Line, status bar) is relative to it, while the model and files keep global metres. Select the working CS in the status-bar chip; rename / delete / back to Global. Saved in the `.warp` (`AetherCoordinateSystems`). Offset-only: rotated CS and *Face CS* are not implemented.
- **Antenna parameters vs frequency.** `Results > Antenna Parameters vs Frequency…`: directivity, gain (total), realized gain (with mismatch 1 − |S11|²), radiation efficiency, total efficiency and |S11| against frequency, at each frequency's peak or at a fixed (θ, φ), total or θ/φ polarisation, with markers and a data table. One point per saved field, so enable *Save fields* on a discrete sweep.
- **Closing or replacing a project clears everything of the old solution** (report tabs, field overlay and its panel and legend, Results list); the multi-select panel no longer fails when the selected names are gone.
- **File dialogs sort**: by name, newest/oldest, size or type, from the drop-down or by clicking a column header; the choice is remembered.
- **Windows move.** Dialogs and the field / drawing / New Line panels drag by their title bar (double-click resets, position remembered, never off-screen); dialogs also resize.
- **Plane and grid visibility.** The field panel has *Show plane / Show plot*, the viewport a *Grid plane* toggle (View menu too), the exported three.js viewer both.
- **Fields and current on the metals you choose.** The field panel's *Plot on ▸ Chosen metals* lists every conducting solid and sheet with a checkbox; E, H and the surface current Js are drawn only on the ticked ones, with the rest of the model kept visible and faint behind them (Model opacity). *selection / all / none* buttons, and *Follow viewport selection*: clicking a metal in the 3-D view or the project tree shows its field or current at once. The exported three.js viewer has the same metal list.
- **Drawing:** XY / YZ / ZX work planes (a rectangle was always drawn on XY whatever plane was meant), plane taken from a hovered flat face, Tab to type values with the mouse paused, a click or Enter to accept. New by-points circle, sphere and cone. Drawn faces are valid port and boundary targets.
- **Editing:** selecting several objects turns the property grid into one panel that sets material, colour, transparency and visibility on all of them in one undo step. A basic colour palette with a "more colours" picker replaces the bare colour box.
- Insert Eigenmode Design, an eigenmode setup dialog, and a Setup/Sweep dialog laid out like Warps's.

**Housekeeping**

- Release patches, test-result XML and per-version upgrade notes removed; `examples/` now holds nine complete `.warp` projects (dipole and patch antennas, waveguide, filter, coax, cavities, a parametric slab) built by `examples/build_examples.py`, with scripts for the dipole, optimisation, sweep strategies and eigenmodes.

# 1.7.9 — the import report, the mesh, and assigning a port by pointing at it

Built against the same user project as 1.7.7 and 1.7.8, and against the import report exported from it: 15 unsupported-PML material errors, 6 unresolved PML radiation boundaries, 20 unresolved parts and a setup that would not validate.

- **The PML apparatus is dropped on import.** HFSS builds a perfectly matched layer as geometry: a shell of `PML_*` boxes and wedges, a `PMLGroup*` material per stretching direction, and a `PML_radiation*` boundary on every outer face. None of it is the model the engineer drew and none of it can be solved here, so all of it is discarded before any geometry work — and the open condition it stood for is put back as a **Radiation boundary on the outer surface**, so the model is not quietly closed. On the user's project this alone removes 21 of the 30 unresolved items and every material error in the report.
- **The air region is rebuilt.** `Region` is stored as "the model bounding box plus this much padding on each of the six sides", and it was arriving as an unsupported part — which left the model with nothing but metal in it and nothing to solve. The padding (absolute or percentage, per face) and any faces afterwards swept outward by hand are read and the box is reconstructed, as a solved vacuum body.
- **A setup imported from HFSS validates.** HFSS writes `BasisOrder=0` for mixed order and `-1` for zeroth order; both imported verbatim and then failed validation with "basis order must be 1 or 2" on a setup the user never touched. The nearest supported order is used and the substitution is reported.
- **Generate Mesh no longer stops at the first unreadable body.** A part stored as an ACIS or Parasolid attachment cannot be rebuilt by any open kernel, and one of them used to abort the whole mesh with a `CadImportError`. Those bodies are now left out, the rest of the model meshes, and the message window names exactly which bodies are missing and what to do about them. On the user's project: mesh generation went from failing outright to 68,981 tetrahedra in six seconds.
- **Modeler ▸ Repair Bodies.** One STEP export, every placeholder body, one dialog: the file is read once, its bodies are matched to the bodies without geometry by name, and the mapping is shown — with each candidate's true extent in millimetres, so a part can be identified by its size when the export carries no names — for correction before anything changes.
- **The initial mesh always comes back.** A conductor's refractive index is in the thousands, and letting it set the element size asked for 80 nm elements across a 60 mm board. Bodies that are not solved inside no longer set the size at all, the index that does is capped, and the result is held to an element budget with the coarsening reported rather than silently applied.
- **Ports by pointing at two conductors.** `Simulation ▸ Excitations ▸ Lumped Port (pick)`, or the viewport's right-click menu: click the signal face, click the ground face, Apply. The sheet the port needs is created across the gap — no wider than the narrower of the two picks — and the integration line runs ground → signal, which is what fixes the sign of V and therefore of the port impedance. `Wave Port (pick)` assigns the port to the picked cross-section and takes an optional reference pick for its integration line. Ctrl+click adds faces to either side; S and G re-arm the signal and ground rows; Esc cancels.
- **An assignment that lands on nothing says so.** Boundaries and ports report the number of face triangles they cover, and warn in the message window when that is zero — the quietest failure mode in a field solver was a boundary that is in the tree, solves, and is not on the model.
- Generate Mesh on a design with no geometry, and on a design with no setup, now say what is missing instead of failing obscurely.

# 1.7.8 — selection, moving, sweeping, and the cost of an import

- **Sweep Face Along Normal makes a new object.** It was built exactly like Move Faces — the swept volume was fused into the body the face belongs to — so the command that exists to turn a face into an object of its own did nothing of the kind. It now creates the swept body, names it, gives it the source body's material and leaves the source untouched. Move Faces still drags the face and grows or trims the body, which is the other half of the pair.
- **Rubber-band selection.** Ctrl+drag a rectangle in the viewport (or arm the toolbar's box-select button) to select every object, face, edge or vertex it covers, in whichever pick mode is active; Shift adds to what is already selected. Picking one face at a time is workable on a box and hopeless on a coil.
- **Move by two points.** Select, then point at where it should go: click a base point and a destination, or type ΔX/ΔY/ΔZ, or type a distance to keep the direction and change how far. Live wireframe preview of where the selection will land, every field editable, `Copy` to leave a duplicate behind, Esc to step back. No modal over the model.
- **The by-points draw grew the wrong way.** The closest-approach solve for the height step had its sign inverted, so dragging the cursor up made the box grow down.
- **Importing a CAD file is roughly twice as fast.** Inspecting a file read it twice and meshed it twice; the viewport then meshed it a third time to draw it. Inspection is now one read and one mesh, and that mesh is kept and handed to the viewport. On the user's 18-body NURBS STEP: 12.3 s to import and draw becomes 5.3 s, with the display itself instant. A DXF is no longer tessellated twice either.
- **Import and draw work on an empty workspace.** With no project open they answered "no design is open — use Project ▸ Insert Design"; they now create the document they need and say so.
- **A selection can no longer be undone by a reply that was already in flight.** Every RPC reply carries a state snapshot, and a slow one was overwriting a selection made after it was sent.
- A browser tab closed in the middle of a reply no longer risks taking the server down with it.

# 1.7.7 — the three faults that stopped a real project loading

Reproduced from a user's own files: an HFSS project of 29 bodies, the STEP those bodies were exported to, and a DXF of the coil layer. All three failures are fixed and each has a regression test built from the smallest case that carries the same defect.

- **A project could load completely and show nothing.** A material name containing a space or a hyphen — "Polyflon copper-clad ULTEM (tm)", and an HFSS project is full of them — was stored in the library under one key and looked up under another, because `add` folded only case while `get` also folded spaces and hyphens. `materials.list` therefore raised for the whole library, and that call sits between "project loaded" and "draw it": the workspace held a complete model and displayed an empty viewport. The two normalisations are now one.
- **Opening is no longer all-or-nothing.** Reading the file is the only step allowed to abort an open; a failure in materials, in the display, in the import report or in the diagnostics is reported and the model is still drawn.
- **A STEP import could never finish.** A STEP export carries more than its solids: this one also held presentation geometry — free faces of 321 m² and free curves 36 m long, in an assembly whose largest body is 48 mm. `mesh.generate` meshes every entity in the model, so those faces were being triangulated at the assembly's element size. Meshing now runs only on the entities the displayed bodies actually use (1,995 strays dropped in this file), and the element size is solved against a triangle budget (`AETHER_VIEW_MAX_TRIS`, 900,000 by default) instead of being taken on trust. The same guard covers the inspection pass that reports a file's bodies before import. Measured on the user's file: inspection went from never finishing and 5 GB of RAM to 8.6 s; import plus display of all 18 bodies is about 20 s at 190 MB.
- **A DXF drawing could be refused whole because of one edge.** A layout exporter writes 0.1 µm steps into a 45 mm outline; OpenCASCADE will not build an edge shorter than its confusion tolerance and answered "Could not create line". Rings are now cleaned against a tolerance derived from the ring's own size with a one-micrometre floor, and a single unusable outline is skipped and reported rather than taking the drawing with it.
- **Display caches are emptied when the document changes**, and the blob budget is halved. Opening several large projects in one session no longer accumulates the buffers of the ones that were closed.

# 1.7.6 — resizable docks, drawing in the viewport, and why it is blank

- **Every dock edge is a splitter.** The Message Manager was a fixed 178 px — one and a half lines of an import report. Drag any edge to resize, double-click it to restore the default, double-click the tab strip to collapse it to its tabs, and the sizes are remembered between runs.
- **Draw by points is no longer a modal.** Clicking two points used to throw a dialog over the model and ask for the numbers again. The numbers now live in a panel beside the model: the cursor position, both corners, the size and the height update live as you drag, every field is editable, and typing a value and pressing Enter is the same action as clicking. Esc steps back one point instead of abandoning the draw. Box, rectangle and cylinder all work this way, with a wireframe preview and a size label on the model.
- **A live coordinate readout in the status bar**, at all times — on geometry it reads the point under the cursor, off it the work plane.
- **"It loaded but nothing appeared" now has an answer.** `View ▸ Display Diagnostics` reports every object as displayed / no geometry / not drawable / hidden / empty, with its material, transparency and extent, and names the two cases that look like a failed import but are not: a model whose visible bodies are all near-transparent air or PML regions, and one whose real parts are hundreds of times smaller than its air box.
- **`View ▸ Solid Display`** ignores material transparency, so air and PML regions stop hiding the model. It is switched on automatically — and said so — when a freshly opened project has nothing but near-transparent bodies to show.
- A body that cannot be triangulated is drawn as its extent box and reported, instead of being silently dropped from the scene.
- **Fit Selection** (Ctrl+Shift+D, `View ▸ Fit Selection`, and *Zoom to Object* in the tree): Fit All frames the radiation box, which leaves the patch inside it sub-pixel.

# 1.7.5 — document lifecycle, progress and viewport speed

- **Close Project** (File ▸ Close Project, Ctrl+W) and a real **File ▸ Exit** that stops the server instead of only closing a tab. The workspace now has a "no project open" state rather than silently substituting an empty one.
- **Save / Don't Save / Cancel** before anything discards unsaved work — New Project, New from Template, Open Project, Close Project and Exit. The old prompt offered only discard-or-cancel, so keeping the work meant cancelling and starting over.
- **Progress while it works.** Opening a project, importing CAD and rebuilding the display buffers publish their stage, item and count on a channel answered by its own request, so it keeps updating while the command holds the session lock. A blocking overlay names the stage and the Progress panel carries the detail.
- **Viewport speed.** Tessellation is cached for every shape, not only for imported bodies (a redraw re-meshed the whole model in OpenCASCADE before). Objects carry a geometry digest, so a redraw re-sends only what changed and the browser rebuilds only those GPU buffers and pick trees. Vertex arrays travel as float32 blobs instead of JSON numbers.
- Face metadata, face-outline extraction and face clustering rewritten as array operations; the per-face Python loop was quadratic in the number of faces, which is exactly the imported-STEP case.
- Boundary and port overlays reuse the cached display triangles instead of tessellating the model a second time on every redraw.
- Project tree: rename, delete and set-active for designs; project and design context menus.
- Export Solution Data browses to a folder and resolves to an absolute path; a relative name used to land in whatever directory the server started in.
- A rolled-back command no longer replaces every body in the design with an equal-but-different copy.

# 1.7.1 — import repair

- Restore `_clean_part_name`, missing from 1.7.0, and cover the multi-body GUI registration branch without requiring OCC.
- Add ezdxf-based INSERT/curve/OCS reading, conservative same-layer LINE/ARC endpoint stitching and visible unsolved Sketch references.
- Fit 2D-only projects to actual sheet/reference bounds; preserve references through AEDT/AEDTZ save, transforms and undo.
- Decode UTF-16 BOM projects; preserve nested AEDTZ relative CAD paths with extraction safety checks.
- Fix unresolved typing imports found by static analysis; extend regression cases and ship DXF checks.

# 1.7.0 — 2026-09-06

- Dimension-checked variable expressions and persistent primitive bindings; rebuild through Boolean/profile history.
- Actual FEM parameter studies on isolated copies, comparison plot and summary/curve CSV exports.
- Cooperative cancellation; saved solver/mesh controls; unsupported physics preflight errors.
- Atomic STL/STEP export with no bounding-box fallback; STEP units checked by reimport.
- Accurate affine primitive bounds; analytic volume and unambiguous radius/diameter/area measurements.
- Air-region creation, return-loss metrics, marker and interpolated threshold crossings.
- Reproducible CPU FEM benchmark, HTTP integration and engineering regression tests.
- Carries all file, editing and measurement fixes from 1.6.1.

# 1.6.1 — 2026-09-05

- Fixed edit persistence after reopening a project; GUI auto-save rebuilds supported model branches. Explicit update mode remains a limited settings update.
- Atomic project replacement and previous-save backup. Content-addressed CAD sidecars and portable AEDTZ payloads.
- Reset cross-project history, rollback failed edits, undo Cut, guard active solves, maintain mesh references.
- Analytic segment separation, coordinate distance/deltas/angle/circle, dimension Resize, CSV export and viewport point picking.
- Persist units, local mesh operations and additional sweep/setup fields.
- Add isolated launcher and Korean guide with explicit test limitations.

# Changelog

## 1.6.0

A robustness release: the failures that cost a whole file, and the ones that
cost a whole afternoon.

### "unterminated string near offset 0"

One unbalanced apostrophe in a project file swallowed **every line after it**:
the line joiner kept looking for the closing quote to the end of the file, and
the parse then failed thousands of lines away from the damage. A quoted value
now ends at its own line unless it carries the trailing backslash HFSS
actually writes (the base64 blocks still join). Around that, two more levels
of tolerance:

* a statement that cannot be parsed is **kept verbatim** rather than raising —
  the tree still holds it and the round trip is still byte-exact;
* a block that does not close, or an `$end` naming the wrong block, is
  repaired and recorded instead of aborting the read.

A damaged project now opens with everything that was readable in it.

### STEP files that would not load, or took forever

* **Every body was read separately.** Measuring the parts, listing them and
  drawing them each re-imported the whole file: a twelve-part assembly was
  read 24+ times, which is what "it hangs" and "it eats memory" looked like.
  All three now come from one import — a 24-body file went from **6.7 s to
  1.3 s**, with flat memory.
* **All the parts drew as the same part.** The display cache key left out
  *which body* it was, so an assembly rendered as whichever part was
  tessellated first. (Its own regression test now checks each part is in its
  own place, at its own size.)
* **Non-ASCII paths.** OpenCASCADE takes narrow file names, so on Windows a
  Korean folder name or an accented part number reached it mangled and the
  read simply failed. Such files are now copied to a temporary ASCII name for
  the kernel.
* **A file that will not read** now says which file and what to try, instead
  of surfacing a raw kernel error.
* The display cache is bounded by triangles held rather than by entry count,
  and the bounds cache is bounded at all.

### DXF was unreachable

The reader shipped in 1.5.0, but the file browser's CAD filter did not list
`.dxf` — so the files were not shown and the feature appeared not to exist.
`.dxf` is now in the CAD filter with a format of its own, and **choosing a
format in the dialog actually filters the listing** (every entry used to carry
the same value, so the choice did nothing).

### Sheets are objects too

A sheet — a DXF outline, an imported surface — could not take a colour
(`no solid named …`), could not be measured, and came back from a saved
project as a *solid*. Sheets now carry the same colour, transparency and
visibility as solids, are measured the same way, and stay sheets through a
project file. Per-object display settings and the imported **body index** are
written to the project and read back, so a reopened assembly is still twelve
different parts rather than one part twelve times.

### Tests

411 (was 387), including a new `tests/test_robustness.py`.

## 1.5.0

### An assembly is a list of parts now

A multi-body STEP arrived as one lump that could be neither split nor picked
apart. Two things were wrong:

* **shape healing welded it together.** Healing sews faces, and sewing an
  assembly makes one compound that then fails to become a solid — a good
  three-part file came back as fifteen loose faces and *no solids at all*.
  Healing is now applied only when reading the file as-is produced nothing
  solid, which is the case it was meant for.
* **the importer made one object.** It now makes **one object per body**,
  named from the CAD label where the file carries one, so each part takes its
  own material and assignments. *Import as a single body* remains for the
  cases where the assembly really is one thing, and the bodies can be listed
  before importing.

### AutoCAD .dxf

Read directly, with no third-party library, so an air-gapped install reads
drawings too: LINE, LWPOLYLINE (arcs and bulges included), POLYLINE, CIRCLE,
ARC, SOLID and POINT, on any layer, honouring `$INSUNITS` (nothing declared is
read as millimetres). Closed outlines become sheets and an outline inside
another is cut out of it — a mounting hole, a slot, a coupling gap. One
**Sweep Face Along Normal** then gives the outline thickness: an antenna trace
drawn in AutoCAD becomes 35 µm of copper in two steps. Binary DXF and DWG are
refused with an explanation instead of a stack trace.

### Measuring

Every pick now answers the question that made you click it, in the model's own
units: an edge reports its length, two edges their lengths and separation, a
face its area and extent, **two faces the gap between them** (with parallelism
and plane spacing when they are parallel), a selection its overall size and
the gap between two objects. The distance is the *minimum* separation rather
than centre-to-centre — two faces that barely overlap have a gap that has
nothing to do with the distance between their middles — and the span it
measured is drawn in the viewport with the number floating over it.

### Drawing from the screen

**Draw ▸ Box / Rectangle / Cylinder by points**: the first click fixes the
origin (on a body if you click one, on the visible working plane if you do
not), the second the opposite corner, with the outline rubber-banding and its
running dimensions shown as you move. The creation dialog then opens already
filled in with those numbers. `S` toggles grid snapping, `Esc` cancels.

### Boundaries and ports are visible

They were invisible: a port was a row in a tree, and whether it had landed on
the face you meant was something the solve told you. They are now drawn on the
faces they cover, colour-coded by type, with a legend naming each (click a row
for its properties) and the port's integration line on top. No mesh is needed
— the selectors are evaluated against the displayed triangles, so what is
drawn is exactly what the mesher will tag.

### Tests

387 (was 354), including a new `tests/test_dxf.py`.

## 1.4.0

### "invalid decimal literal" — one property stopped a whole project loading

Every part in a desktop-written project carries `ReferenceTemperature='20cel'`.
The expression evaluator knew lengths, frequencies, angles, times and ohms, so
`20cel` went to Python's parser as-is and came back `invalid decimal literal` —
raised from the middle of the load, which meant no model at all and an empty
screen.

* **any** `<number><unit>` token is now understood: SI units are converted,
  temperatures with their offset (`20cel` → 293.15), powers, currents,
  capacitances, inductances, percentages and the rest by scale, and an
  unrecognised suffix is taken as a bare number instead of a syntax error;
* an expression that still cannot be evaluated raises a typed `ExpressionError`,
  and reading is **per item**: the boundary, port or setup that carries it is
  skipped and listed in the import report. One bad value can no longer cost the
  other 99 %.
* A project whose bodies are all native (Parasolid) genuinely has nothing to
  draw — that is now **said once, plainly**, naming the objects and the way to
  complete them, instead of leaving an empty viewport and a warning per object
  per redraw.

### Face operations on imported bodies

* **The extent of an imported curved part was wrong.** OpenCASCADE builds its
  bounding box from surface control points, and a circle drawn as three
  rational arcs reaches twice its radius: a 10 mm rod reported a 30 mm box, so
  the camera framed empty space, the ground grid was drawn for a model twice
  the size and the automatic mesh seed came from a diagonal that does not
  exist. Bounds now come from points that are actually on the geometry.
  (The analytic cylinder was loose the same way, by a radius at each end.)
* **A curved face is refused** with a reason: "along the normal" has no single
  direction on a cylinder wall, and the old behaviour was to extrude along the
  average of the wall's normals — a direction that means nothing.
* **A face operation that cannot be applied no longer looks like it worked.**
  The tessellator fell back to drawing a bounding box whenever a build failed,
  which for a broken sweep meant a box appearing in place of the body. Model
  errors now propagate, the operation is undone, and the message says what
  went wrong. The build is verified when the operation is applied, not later.
* **A sweep only ever touches its own body.** With a whole design built into
  one modelling session, another object's face can sit exactly where the
  recorded one does; matching is now restricted to the body's own faces.

### Per-object display

Colour, transparency and visibility are now properties of the object, not only
of its material — each with a *reset* back to the material's value, and a
hidden object neither drawn nor pickable. A red patch on a red substrate no
longer needs a new material to fix.

### Right-click, as in HFSS

The viewport and the project tree both have context menus. The viewport's
holds the pick modes, Assign Boundary / Wave Port / Lumped Port, Add Mesh
Operation, Sweep Face Along Normal, Move Faces, Arrange, Duplicate, Boolean,
Copy / Paste / Delete, Fit All and Properties, enabled according to what is
picked; right-clicking an object selects it first. The tree's menu is per node
— Rename, Hide, Show All and the assignments on an object; Properties and
Delete on a boundary, port, setup or mesh operation; the draw commands and
Import CAD on the Modeler node.

### Tests

354 (was 324).

## 1.3.0

### "unterminated block 'x_b'" — projects from the HFSS desktop now open

A project built in the modeller stores its solids as Parasolid bodies and
carries them inside the `.aedt` itself, as length-prefixed binary blobs
(`BIN000000006179` followed by exactly that many bytes). Those bytes contain
quotes, brackets and literal `$end` sequences, so the line-oriented lexer
walked into them and gave up. Four separate things had to change:

* the lexer takes a `BIN<count>` payload **by its length** and keeps it
  verbatim — a 780 kB project with 23 embedded bodies now round-trips
  **byte for byte**, including after an edit elsewhere in the file;
* the design block is found whether it is called `Design` (scripted and
  exported projects) or `HFSSModel` (what the desktop writes);
* boundaries are read from `BoundarySetup ▸ Boundaries` as well as directly
  from `BoundarySetup`;
* `Objects(1255)` — HFSS writes **body ids**, not names — is resolved through
  the part ids collected while the geometry is read, so `Perfect E` and
  `Wave Port` land on the right bodies. Boundaries given only by *face* ids
  are still reported as unresolved rather than mis-applied.

Parasolid itself OpenCASCADE cannot read. Each native body is therefore written
out of the project into `<project>.cad/` and created as an object marked *needs
a readable source*: the model keeps its object list, materials, boundaries,
ports and setups, and each body is completed by exporting STEP from HFSS and
pointing at it with *Replace CAD Source*. Parts that are HFSS's own operand
bodies are no longer imported as objects of their own.

### Selection: objects, faces and edges

Picking is what tells an assignment *where*, so it now works as it does in a
modeller:

* **Object / Face / Edge** modes, on the viewport toolbar and on `O` / `F`
  / `E`; Ctrl-click adds; the status bar shows the picked **area** or
  **length**;
* faces come from the CAD kernel (a box has six, a cylinder three); without a
  kernel the viewport groups its own triangles by continuity and gets the same
  answer for the primitives;
* a picked face is highlighted on its own, not the whole body;
* **a pick stores geometry, not an index** — a point on the face, its normal
  and its extent — so an assignment survives remeshing, every adaptive pass, a
  change of mesh size and a reopened project. Face numbering does not.

### What a picked face can be used for

* **Boundaries and excitations** — *Picked faces* is offered in every
  assignment dialog and is the default whenever something is picked.
* **Mesh operations** (new): `Simulation ▸ Add Mesh Operation…` refines the
  initial mesh on chosen objects or faces to a stated maximum element length.
  They appear under **Mesh** in the tree, are individually editable and can be
  switched off. A face refinement is kept local — the fine size at the face's
  rim is not allowed to propagate through the body.
* **Face modelling** (new): `Sweep Face Along Normal…` extrudes a face and adds
  the swept volume; `Move Faces…` drags the face, growing the body or trimming
  it on a negative distance. Both are recorded as an operation *over that
  face*, so the distance stays editable, the object keeps its name, material
  and every assignment, and each is one undo step. Both are written to the
  project file and read back.

### Tests

324 (was 274). `tests/test_aedt_native.py` (15) builds a project with the same
shape as a desktop-written one — embedded binary payloads included — and
`tests/test_selection.py` (30) checks that a boundary on a picked face tags
that face's exact area and no other, at two mesh sizes, and that a swept face
grows the body by exactly the distance given.

## 1.2.0

### Import CAD did nothing at all

Every dialog shared one panel element. Opening the file browser from inside the
Import CAD dialog therefore **overwrote the dialog that opened it**: picking a
file wrote the path into a detached node, the import had nothing to import, and
the button appeared dead. Dialogs are now a stack — each owns its element, only
the top one takes Escape or a backdrop click, and closing it reveals the parent
exactly as it was left. Every other nested Browse… button was affected the same
way and is fixed by the same change.

Along with it, the file browser:

* accepts a **full path typed or pasted** into its name box — a folder is
  navigated to, a file is accepted straight away;
* **reopens where you were last time**, per file kind, so a CAD library and a
  project folder are remembered separately.

### An imported body is a real object now

* **Model units** and the **source file** are editable in the property grid,
  and from `Modeler ▸ Replace CAD Source…`. Both edit the object in place, so
  its name, material, transforms and every boundary and port assigned to it
  survive a corrected unit or a newer revision of the CAD file.
* The property grid shows the source file name and flags it when the file is
  gone, with *Locate file…* to point at it again.
* New command `modeler.replaceCad`; imported bodies now report their
  provenance in the session state.

### Projects with imported geometry actually save

Writing recorded only an absolute source path, and reading never restored the
body at all — so saving a project with an imported STEP and reopening it lost
that part in silence.

* `ImportParameters` now carries `ModelUnits`, `ScaleToM` and `EmbeddedFile`
  alongside `SourceFile`, and **the reader restores the body**.
* Saving copies each imported CAD file into a `<project>.cad` folder beside the
  project, recorded as a relative path; the absolute path stays as a fallback.
  A project can now be moved, copied or sent on and still open.
* A part whose source cannot be found is loaded anyway — with its transforms,
  boundaries and ports — and named in the import warnings, instead of quietly
  not being there.

### Tests

274 (was 261). The browser suite covers the browser-inside-a-dialog path that
was broken; `tests/test_gui_edit.py` covers save → move the source away →
reopen, a missing source, and replacing a source in place.

## 1.1.0

### CAD import now states its units instead of guessing

STEP and IGES store bare numbers and declare separately what they mean. A file
that means 20 mm, read as metres, becomes a 20 metre part: the camera fits to
it and every other object in the model turns into an invisible speck — which
is what "I imported a STEP file and nothing appeared" actually is.

* The file's own declaration (`SI_UNIT`, `CONVERSION_BASED_UNIT('INCH')`, the
  IGES global-section unit) is read and applied. The conversion is done by
  Aether rather than by `Geometry.OCCTargetUnit`, which OpenCASCADE honours
  only for the first STEP read in a process — every later import in the same
  session came back in the file's own numbers.
* **Model units** in the Import CAD dialog overrides the declaration:
  m / cm / mm / µm / inch / mil / foot. STL and OBJ declare nothing anywhere
  and are read as millimetres unless told otherwise.
* The file is **inspected before it is imported**, on choosing it and again on
  every unit change: format, solid count, face count, the extent it will land
  at in millimetres, and the unit applied against the unit declared. The same
  line goes to the Message Manager on import.
* Surfaces without a closed solid, unreadable files and ACIS `.sat` are
  reported as such rather than importing nothing in silence.
* STEP and IGES **export** now writes millimetres under its millimetre header.
  Previously the header said millimetres and the coordinates were metres, so a
  file Aether wrote came back a thousand times too small anywhere — including
  in Aether.
* Repeated reads of one file are cached on path, size and mtime, and imported
  bodies are tessellated once instead of on every viewport rebuild
  (0.12 s → 0.000 s per redraw on the test assembly).

### The edit tools a real design needs

All of them act on the current selection, work on any number of objects at
once, and are a single undo step each.

* **Undo / Redo** (`Ctrl+Z` / `Ctrl+Y`), 40 steps deep and labelled with the
  operation. The design is snapshotted whole, so a boundary or port that
  referred to a deleted object still refers to *that* object after the undo.
  A command that fails leaves no history entry.
* **Cut / Copy / Paste** (`Ctrl+X` / `C` / `V`) with material and solve-inside
  preserved, plus **Paste at Offset**.
* **Duplicate** along a line, around an axis, or mirrored (`Ctrl+D`), with the
  copies optionally united into the original. The count is the total including
  the original, and the axis angle is either the span of the whole pattern or
  the step, by a checkbox.
* **Arrange** move / rotate / mirror / scale, now on a multi-selection and
  with an axis or plane point.
* Menu items that cannot do anything yet are greyed out rather than failing
  when clicked.

Fixed along the way: `modeler.duplicate` converted the pattern angle to
radians and then handed it to `Shape.rotate`, which converted it again as
degrees — a 90° step became 1.57°.

### Tests

261 (was 222). New `tests/test_gui_edit.py` (32) checks the resulting geometry
rather than the return value; the browser suite grew to 23 and its dead-entry
sweep now covers 107 entry points.

# Formulation

## 1. Governing equation

With the engineering time convention `exp(+jωt)`, Maxwell's curl equations
combine into the double-curl vector wave equation for **E**:

```
∇ × ( (1/μ_r) ∇ × E ) − k0² ε_c E = 0 ,        k0 = ω/c0
```

with the complex relative permittivity

```
ε_c(f) = ε_r'(f) − j ε_r''(f) − j σ/(ω ε0)
```

so loss is a **negative** imaginary part. `μ_c` is formed the same way. Every
dispersion model (Debye, Drude, Lorentz, Djordjevic-Sarkar, tabulated) is only
a rule for producing these two complex numbers; no solver kernel knows more
than that.

## 2. Weak form

Multiplying by a test function **W** and integrating by parts,

```
∫ (1/μ_r)(∇×W)·(∇×E) dV − k0² ∫ ε_c W·E dV + ∮ W·( n̂ × (1/μ_r) ∇×E ) dS = 0
```

The surface term is where every boundary condition lives.

### 2.1 Impedance-type boundaries

Using `(1/μ_r)∇×E = −j k0 η0 H` and the Leontovich condition, the surface term
becomes

```
A += j k0 Ỹ ∮ (n̂×W)·(n̂×E) dS ,        Ỹ = η0 / Z_s
```

* `Ỹ = 1` → first-order Sommerfeld radiation boundary (matched to free space)
* `Z_s = (1+j)/(σδ)` → finite conductivity, with
  `δ = √(2/(ωμσ))`; a `coth(γt)` factor covers finite thickness and the
  Hammerstad–Jensen factor `1 + (2/π)atan(1.4(Δ/δ)²)` covers surface roughness
* `Z_s` from a series/parallel `R‖L‖C` → lumped RLC sheet

The sign is positive-imaginary, i.e. dissipative, which is the same sign the
lossy-material term `+j k0² ε'' T` carries — a useful internal consistency
check.

### 2.2 Wave ports

On a port plane with outward normal `n̂ = −ẑ`, expanding the tangential field
in the port's own modes `e_m` (normalised `∫_S e_m·e_m dS = 1`) gives

```
A += Σ_m (γ_m/μ_r) v_m v_mᵀ ,      v_m,i = ∫_S W_i · e_m dS
b   = 2 (γ_inc/μ_r) v_inc          (unit incident amplitude)
```

`v_m` is exactly the surface mass matrix applied to the mode vector, because
the port basis is literally the trace of the volume basis — no interpolation
error is introduced at the port plane. The reflected amplitudes follow from

```
b_m = ⟨E, e_m⟩ − a δ_{m,inc} ,     S_ij = (b_i / a_j) · √(Z_j / Z_i)
```

### 2.3 Lumped ports

A lumped port is a driven impedance sheet. With port impedance `Z_p`, field
direction length `L` and transverse width `w`, the sheet impedance is
`Z_s = Z_p·w/L`, and

```
A += j k0 (η0/Z_s) ∮ (n̂×W)·(n̂×E) dS
b   = 2 j k0 (η0/Z_s) ∮ W·e dS
```

The validation case is a parallel-plate line, whose impedance `η0·h/w` is
exact: matched termination gives |S11| < −50 dB, and a `2Z0` termination gives
|Γ| = 1/3 to within 3 %.

## 3. Port modal eigenproblem

Writing `E = [E_t + ẑE_z] e^{−γz}` and scaling `Ẽz = jβE_z` to remove β from
the longitudinal equation yields

```
| −A_tt   T_tz | |E_t|         | T_tt  0 | |E_t|
|   0     A_zz | |Ẽz |  = β²   | T_zt  0 | |Ẽz |
```

with

```
A_tt = ∫(1/μ)(∇_t×E_t)(∇_t×W_t) − k0²∫ε E_t·W_t
T_tt = ∫(1/μ) E_t·W_t
T_tz = ∫(1/μ) W_t·∇_t Ẽz          (T_zt = T_tzᵀ)
A_zz = ∫(1/μ) ∇_t W_z·∇_t Ẽz − k0² ∫ε W_z Ẽz
```

The right-hand matrix is singular. Eliminating `Ẽz`,

```
Ẽz = β² A_zz⁻¹ T_zt E_t
A_tt E_t = −β² ( T_tt − T_tz A_zz⁻¹ T_zt ) E_t
```

gives a **regular** pencil of half the size whose entire spectrum is physical.

Modal power is integrated directly from the recovered fields,
`P = ½ Re ∫ (E_t × H_t*)·ẑ dS`, and with the `∫|e|² = 1` normalisation the wave
impedance is `Z = 1/(2P)`. With an integration line the line impedance
`Z_pv = |V|²/(2P*)` is also available — the quantity a VNA measures on a TEM
line, and the one used for S-parameter normalisation when present.

## 4. Basis functions

**Order 1 (Whitney, 6 DOF/tet)**

```
W_ab = λ_a∇λ_b − λ_b∇λ_a ,        ∇×W_ab = 2∇λ_a×∇λ_b
```

**Order 2 (20 DOF/tet)** adds 6 edge gradients `∇(λ_aλ_b)` (curl-free) and 8
face functions `λ_i W_jk`, `λ_j W_ki` per face — two, not three, because
`λ_i W_jk + λ_j W_ki + λ_k W_ij ≡ 0`. Face node triples are ordered by global
node id so both tetrahedra sharing a face generate identical traces, which
makes the gradient and face blocks orientation-free. The set is verified in CI
to be linearly independent and to reproduce every linear vector field exactly.

## 5. Error indicator

The electric field is tangentially continuous by construction, so any jump in
`n̂ × H` across an interior face is pure discretisation error:

```
η_K = Σ_{f ⊂ ∂K} |f| · ‖ n̂ × (H⁺ − H⁻) ‖²
```

The worst 30 % of elements have their target size scaled down and the model is
re-meshed from the resulting size field, so each pass produces a fresh,
well-shaped, globally conforming mesh. Convergence is declared when
`max_ij |ΔS_ij| ≤ ΔS_target` between consecutive passes.

## 6. Far field

Equivalent surface currents `J_s = n̂×H`, `M_s = −n̂×E` on the radiation
boundary radiate into free space:

```
E_θ = −j k0 e^{−jk0r}/(4πr) ( L_φ + η0 N_θ )
E_φ = +j k0 e^{−jk0r}/(4πr) ( L_θ − η0 N_φ )
```

from which directivity, gain, axial ratio and the standard cut plots follow.

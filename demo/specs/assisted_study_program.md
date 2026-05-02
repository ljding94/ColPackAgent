# ColPackAgent Research Program: 2D Hard-Disk Freezing Transition (NPT)

Locate the freezing transition pressure **P\*** for 2D hard disks in the
NPT ensemble. Use the colpack skill autonomously: setup → plan → execute
→ analyze, no user-confirmation pauses.

Literature anchor (Bernard & Krauth, 2011) for sanity-checking your
final P\*: in reduced units P\* ≈ 9.185 with coexistence
η_L ≈ 0.700 and η_H ≈ 0.716 (midpoint η ≈ 0.708).

---

## 1. Constraints (HARD)

### Particle count

`200 ≤ N ≤ 1000` per simulation. Pick a value once and reuse it for the
whole study.

### `sample_steps` policy — adaptive, per-pass

Start short, escalate only on documented equilibration failure. **Never
start at the absolute cap.**

| Pass | Starting `sample_steps` | Purpose |
| --- | --- | --- |
| Pass 1 (coarse) | ≤ 5×10⁵ (typical 1–3×10⁵) | Bracket P\*, not resolve it |
| Pass 2 (refined) | ≤ 2×10⁶ | Autocorrelation peaks near P\* |
| Absolute cap | 5×10⁶ | Reached only via escalation, never as start |

When a specific run fails the equilibration check, re-run **that run
only** with 3–10× more `sample_steps`. Do not pre-emptively raise
`sample_steps` for every point because one failed.

### Equilibration check (single criterion)

For each run, fit a linear drift `η(t) ≈ a·t + b` on the last 50 % of
the trajectory. The run passes iff

> `|a · T_50% / ⟨η⟩| < 0.01`  — drift over the latter half is below 1 %
> of the mean.

Use the analyze-tool's η(t) plot for visual confirmation.

If a run fails and is below the absolute cap, re-run with more
`sample_steps`. If a run is at the absolute cap and still fails, report
what you have and explain in caveats — do not loop indefinitely.

---

## 2. Sweep protocol — at least two passes

**Pass 1 (coarse).** At least 6 pressure points across a window expected
to contain P\* (anchor on the literature value). Goal: bracket the
pressure where ψ_6 jumps and ⟨η⟩ rises sharply.

**Pass 2 (refined).** At least 4–6 pressure points concentrated within
±10–20 % of the Pass-1 P\* estimate. Goal: tighten P\* and characterize
the transition's sharpness.

A third pass is encouraged if Pass 2 still doesn't resolve the
transition cleanly. You decide the exact pressure values within these
constraints.

---

## 3. Observables and P\* estimators

Compute at every pressure on the equilibrated tail:

- **ψ_6** — bond-orientational hexatic order parameter.
- **⟨η⟩** — mean equilibrium volume fraction.
- **g(r)** — radial distribution function.

Report **two complementary P\* estimators** computed on the same data:

- **P\*_OP** — inflection point of ⟨ψ_6⟩(P), e.g. via sigmoid fit or
  maximum-slope.
- **P\*_η** — pressure at which ⟨η⟩(P) crosses the literature midpoint
  η ≈ 0.708 (linear interpolation between bracketing data points).

Quote bootstrap uncertainty for each. The spread between P\*_OP and
P\*_η is your finite-N transition width.

---

## 4. Reporting

Produce one final summary containing:

1. **Sweep parameters** for every pass: N, the `sample_steps` actually
   used per point (which may vary), pressure grids.
2. **Equilibration-check results** per run — drift fraction; flag any
   run that barely passed or was re-executed.
3. **η(P)** and **ψ_6(P)** values (table or in-line is fine).
4. **Both P\* estimates** with bootstrap CIs; discuss their agreement.
5. **Plots (required)**, saved as PNG inside the simulation
   `working_dir` and referenced by path:
   - η(P) with literature η_L / η_H bands and P\*_η marked.
   - ψ_6(P) with P\*_OP marked.
   - g(r) at three pressures spanning the transition (disordered, near
     P\*, ordered).
   - η(t) traces in the transition window (visual eq-check).
6. **Caveats** — finite-size effects, equilibration uncertainty,
   anything to investigate further. If your P\* differs from the
   literature value by more than your reported uncertainty, investigate
   before reporting; the most common cause is under-equilibration
   (re-run with more `sample_steps`).

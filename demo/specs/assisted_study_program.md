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

### `sample_steps` policy — adaptive, escalation-driven

| Tier | `sample_steps` | When to use |
| --- | --- | --- |
| Exploratory | ≤ 5×10⁵ (typical 1–3×10⁵) | Initial bracket, before P\* is even crudely located |
| Refinement | ≤ 2×10⁶ | Points near the suspected transition window |
| Absolute cap | 5×10⁶ | Only after a refinement-tier run failed eq-check; never as a starting value |

When a run fails the equilibration check, re-run **that run only** with
2–3× more `sample_steps`. The table above bounds `sample_steps` by the
run's role, not the escalation step size; successive 2–3× escalations
may be needed to cross from exploratory to refinement, or from
refinement to the cap. Do not pre-emptively raise `sample_steps` for
every point because one failed.

### Equilibration check

The analyze step runs an automatic equilibrium detection
(`analyze_process_time_series`) and writes an `equilibrium` block into
`analysis_results.json` for every particle type and parameter. Read
`equilibrated` (bool), `eq_start_index` (int), and per-parameter
`eq_mean`/`eq_std` from that block — do not re-implement the cutoff.
A run **passes** the eq-check iff `equilibrated == true`.

If a run fails and is below the absolute cap, re-run with more
`sample_steps`. If a run is at the absolute cap and still fails, report
what you have and flag it as a caveat — do not loop indefinitely.

---

## 2. Sweep protocol — iterative, agent-directed

The sweep is not pre-scheduled into a fixed number of passes. The agent
plans, runs, analyzes, and decides what to do next based on what the
data shows. Iterate until the goals below are met, or until further
escalation would exceed the absolute cap.

**Goals (must all be satisfied before reporting):**

1. **Bracket** — at least one pressure clearly in the fluid regime
   (low ψ_6, ⟨η⟩ < η_L) and at least one clearly in the solid regime
   (high ψ_6, ⟨η⟩ > η_H), spanning the transition.
2. **Resolve** — enough points inside the transition window that the
   shape of ψ_6(P) and η(P) is determined, not just sampled. A sigmoid
   fit to ψ_6(P) should be well-constrained (multiple points on the
   rising edge, not just at the asymptotes).
3. **Equilibrate** — every contributing run either passes the eq-check
   (§1) or has been escalated to the absolute cap and flagged as a
   caveat.

---

## 3. Observables and P\* estimators

Compute at every pressure on the equilibrated portion identified by the
auto-cutoff (§1, `eq_start_index` per parameter). The pre-computed
`equilibrium.per_parameter[<name>].eq_mean` values in
`analysis_results.json` are already the means over that window — use
them directly, do not re-average over a different window. Observables:

- **ψ_6** — bond-orientational hexatic order parameter.
- **⟨η⟩** — mean equilibrium volume fraction.
- **g(r)** — radial distribution function.

Report **two complementary P\* estimators** computed on the same data:

- **P\*_OP** — inflection point of ⟨ψ_6⟩(P), e.g. via sigmoid fit or
  maximum-slope.
- **P\*_η** — pressure at which ⟨η⟩(P) crosses the literature midpoint
  η ≈ 0.708 (linear interpolation between bracketing data points).

The spread between P\*_OP and P\*_η is your finite-N transition width.

---

## 4. Uncertainty analysis (required)

MC trajectories are autocorrelated, so a naïve standard error of the
mean underestimates uncertainty — especially in the transition window
where the autocorrelation time grows. Use a **block bootstrap**
(fixed-length blocks, resampled with replacement) to capture this
honestly. Apply it at two levels:

**Per-point.** For each pressure, slice η(t) and ψ_6(t) from
`eq_start_index` onward (use the per-parameter cutoffs from §1: the
`system.volume_fraction` entry for η, the `<particle>.hexatic_6` entry
for ψ_6 — they may differ). Resample blocks of length L (50 frames is
a reasonable default; verify L exceeds the visible autocorrelation time
in the transition runs) with replacement, recompute the equilibrated-tail
mean for each replicate, and quote the resampled distribution's std as
σ(η) and σ(ψ_6) at that pressure. Use these as error bars on η(P) and
ψ_6(P).

**Estimator-level.** For each of N ≥ 1000 bootstrap iterations, draw a
block-resampled equilibrated-tail mean independently per pressure
(using the same per-parameter `eq_start_index` cutoffs as above), then
**recompute P\*_OP and P\*_η from that bootstrap replicate**. The 16/84 percentiles
of the resulting P\*_OP and P\*_η distributions are your 1-σ CI; 2.5/97.5
the 95 % CI. Report point estimate, 1-σ CI, and 95 % CI for both
estimators.

**What the bootstrap captures and does not capture.** It captures
within-run statistical and autocorrelation uncertainty, propagated
through the estimator. It does **not** capture:

- **Pressure-grid uncertainty** — how much P\* would shift if a different
  set of pressures had been sampled. Bound this by leave-one-out: drop
  each point in turn (especially eq-check failures and borderline
  passes) and report the maximum shift in P\*_OP / P\*_η as a
  sensitivity bound.
- **Finite-N bias** — how much P\*_OP and P\*_η would differ at larger
  N. Discuss qualitatively in caveats; quantify only if you do a
  finite-size scaling sub-sweep.
- **Residual non-equilibration** — for runs that hit the absolute cap
  and still fail the eq-check, flag the point and check whether
  excluding it changes the result.

If the bootstrap CI looks suspiciously tight (sub-percent on P\*), say
so explicitly: it reflects within-run precision, not model uncertainty.

---

## 5. Reporting

Produce one final summary containing:

1. **Sweep history** — the iterations actually performed: N, the
   pressure grids added at each iteration, the `sample_steps` actually
   used per point (which may vary), and the rationale for each
   iteration's grid choice.
2. **Equilibration-check results** per run — `equilibrated` flag and
   `eq_start_index` from the analyze step; flag any run that was
   re-executed at higher `sample_steps` or that hit the absolute cap
   without passing.
3. **η(P)** and **ψ_6(P)** values with the per-point block-bootstrap
   σ from §4 (table or in-line is fine).
4. **Both P\* estimates** with point estimate, 1-σ CI, and 95 % CI from
   the estimator-level bootstrap (§4); discuss their agreement.
5. **Sensitivity bound** — leave-one-out shift in P\*_OP and P\*_η, and
   whether it exceeds the bootstrap CI.
6. **Plots (required)**, saved as PNG inside the simulation
   `working_dir` and referenced by path:
   - η(P) with literature η_L / η_H bands, P\*_η marked, and per-point
     error bars from §4.
   - ψ_6(P) with P\*_OP marked and per-point error bars from §4.
   - g(r) at three pressures spanning the transition (disordered, near
     P\*, ordered).
   - η(t) traces in the transition window (visual eq-check).
7. **Caveats** — finite-size effects, equilibration uncertainty,
   pressure-grid sensitivity, anything to investigate further. If your
   P\* differs from the literature value by more than your reported
   uncertainty, investigate before reporting; the most common cause is
   under-equilibration (re-run with more `sample_steps`).

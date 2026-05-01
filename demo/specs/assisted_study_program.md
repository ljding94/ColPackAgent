# ColPackAgent Research Program: 2D Hard-Particle Phase Transition (NPT)

You are running an autonomous Monte Carlo study using the colpack skill. This
document is your research protocol — a contract describing what is fixed
(methodology) and what is yours to decide (scientific judgment).

Treat the **Methodology Constraints** section as required. Treat the **Your
Freedom** section as open — exercise scientific judgment.

---

## 1. Research Question

Characterize the **disordered-to-ordered phase transition of 2D hard particles
(hard disks, hard squares, or a binary mixture) in the NPT ensemble**.

For each composition the central observables are:

- the equation of state η(P) — how volume fraction responds to pressure,
- a shape-appropriate orientational order parameter as a function of P,
- the radial distribution function g(r) supporting the OP interpretation,
- the per-pressure distribution P(η) of volume fractions in the equilibrated
  trajectory (used for the NPT-native coexistence-pressure estimator).

The deliverable is the location of the transition pressure P* — extracted
from BOTH the orientational OP and the η equation of state — and a brief
discussion of what the curves reveal about the ordering mechanism.

---

## 2. Your Freedom (decide for yourself)

- **Composition.** Pick one: pure hard disks, pure hard squares, or a binary
  disk + square mixture. Justify your choice in one sentence at the start.
- **Pressure range and grid density.** Choose values that bracket the
  transition. If your first sweep does not resolve a clear order-parameter
  jump, refine the range and run a second sweep — this is encouraged.
- **`sample_steps` per run, within the §3.2 bounds.** Pick a value at or
  above the §3.2 hard floor (5×10⁶) that fits your wall-time budget and
  the difficulty of the state points. You are encouraged to use longer
  runs (up to the §3.2 recommended ceiling) for state points near P\* —
  these have the longest autocorrelation times and contribute most to the
  P\* uncertainty. Coarse-pass points far from the transition can use
  shorter `sample_steps` than refinement-pass points near P\*.
  **Adapting `sample_steps` is part of your job**: the §3.2 equilibration
  check tells you per-run whether the chosen length was sufficient, and
  if it was not, re-running with 3–10× more `sample_steps` is the
  correct response, not adding caveats.
- **Hypotheses and interpretation.** Decide what counts as the transition
  (e.g., the η-jump midpoint, the OP-inflection point, divergent
  fluctuations) and defend the choice in your final summary.

---

## 3. Methodology Constraints (do NOT vary)

These are the parts that ensure the data is publication-grade rather than a
quick-look pilot. Override defaults explicitly via the planning tool.

### 3.1 System size

- **500 ≤ N ≤ 2000 particles** per simulation. Prefer N in the
  500–1500 range for production runs (cleaner statistics).
- Do not exceed N = 2000: simulation cost scales superlinearly and an
  oversized run will not finish within the task wall-time budget.

### 3.2 Sampling — minimum length and equilibration check

- **`sample_steps` ≥ 5×10⁶** MC sweeps per simulation. This is a **hard
  minimum** — not a guideline. With `sample_steps` < 5×10⁶ at the system
  sizes in §3.1, the system has not had time to relax from the random
  initial configuration into its equilibrium phase, let alone sample
  configuration space; quantitative results from shorter runs are
  unreliable and have produced P* estimates off from the literature by
  ~10–20% in past studies. **Treat anything below this minimum as a
  plumbing test, not science.**
- **Recommended production length: 1×10⁷–5×10⁷ MC sweeps.** Pick the upper
  end if you have wall-time budget; the marginal cost is small relative to
  the value of well-equilibrated samples.
- The ColPack default (5×10⁴) is for plumbing tests and is **2–3 orders of
  magnitude too short**. Always set `sample_steps` explicitly via
  `baseline_parameters` when calling `plan_simulation_runs_tool`.
- **Mandatory equilibration check** — *after* the analyze step completes
  and *before* drawing any P*-conclusion, you must verify each run is
  actually equilibrated, not just nominally analysed:

  1. **η(t) plateau check (quantitative).** For each run, on the last
     50 % of frames, fit a linear trend `η(t) ≈ a·t + b` and require
     `|a · T_50% / ⟨η⟩| < 0.01` (drift over the latter half of the
     trajectory is below 1 % of the mean). As a redundant cross-check,
     split the last 50 % into halves and require the two means to agree
     within 1 std-of-mean of either half. If either test fails, the run
     is under-equilibrated and not usable for P\*-extraction. Also
     produce the η(t) plot — a human-readable visual check of the
     numerical result.
  2. **Equilibrated-tail length.** The analyze tool reports
     `eq_start_index` per run. Check that `(n_frames − eq_start_index) /
     n_frames ≥ 0.4` — i.e. the tool was able to mark at least the last
     40 % of frames as equilibrated. If it can only mark the last
     ~10 %, the run was too short.
  3. **Autocorrelation budget.** Estimate the integrated autocorrelation
     time τ_int of |ψ_6| (and of η) on the equilibrated tail. Require
     `N_eff = (n_eq_frames) / (2·τ_int) ≥ 50` per run for the runs in
     the **transition window** (defined in §3.4d). If `N_eff < 20`, the
     variance estimates are too noisy to support a quantitative P\*
     with tight uncertainty.

  **If any check fails: re-run those state points with 3×–10× more
  `sample_steps`** (still respecting the §3.2 upper bound), then
  re-analyse. Do not paper over under-equilibration with caveats — fix
  it.

  **Exit clause** — if a run is already at the §3.2 sample_steps ceiling
  (5×10⁷) and *still* fails the eq-check, do **not** loop indefinitely.
  Try, in order: (a) reduce `N` within the §3.1 bounds — denser systems
  mix faster per sweep, so dropping from N = 1500 to N = 800 typically
  halves τ_int while keeping finite-size effects acceptable; (b) if even
  the smallest allowed N still fails, report the residual uncertainty
  honestly, mark P\* for that state point as bracketed rather than
  pinned, and explain in the caveats. The goal is calibrated reporting,
  not infinite re-runs.

### 3.3 Sweep resolution

Run the sweep iteratively in **two or more passes**: a coarse bracketing
pass to locate the transition, then a refined pass to resolve it.

**Pass 1 — coarse bracketing.** At least 6 pressure points (ideally 8–10),
spread broadly across the range you suspect contains the transition. The
goal is to locate where the order parameter jumps.

**Pass 1 outcome A — no transition visible.** If the OP is monotonic and
shallow across the entire range, the window is wrong. Pick a different
pressure range and re-run. You may iterate this step more than once until
a transition is bracketed.

**Pass 1 outcome B — transition visible.** Note the approximate
transition pressure P\*.

**Pass 2 — refinement near P\*.** Once a coarse pass identifies an
approximate P\*, run an additional sweep with **at least 4–6 points**
concentrated in a narrow window around P\* (roughly ±10–20% of P\*). The
purpose is to resolve P\* to better precision than the coarse grid allows
and to characterize the sharpness of the transition. Further refinement
passes are encouraged if the transition is still not well resolved.

Document **every** pass in the final summary — its range, number of
points, and what you concluded — so the iteration history is visible.

### 3.4 Order parameters and P* estimators (use BOTH)

You must extract the transition pressure using **two complementary
estimators** computed on the same dataset, then report both. They probe
different aspects of the transition and disagreements between them are
themselves informative (typically ~half the finite-N transition width).

For **hard disks** the two estimators are §3.4a (orientational OP
inflection) and §3.4b (η-midpoint, anchored to literature). For
**hard squares or binary mixtures** there is no universally tabulated
η-jump pair, so the two estimators degrade to **OP-inflection** vs.
**η-inflection** (both inflection-based, but on different observables —
orientational vs. translational/density). This is a weaker cross-check
than the disk case, but the two will still disagree by approximately
the finite-N transition width and the spread is still meaningful.

#### 3.4a Orientational order parameter — choose by shape

- **Hard disks**  → bond-orientational hexatic order parameter `psi_6`.
- **Hard squares** → cubatic / 4-fold orientational order parameter `P_4`.
- **Binary mixture** → report the appropriate OP for *each* species
  separately if the analysis tool supports per-species output.

The OP-based P\* is the **inflection point of ⟨OP⟩(P)** (sigmoid fit, or
equivalently the location of maximum slope). Report the bootstrap CI from
resampling the per-point ⟨OP⟩ values.

#### 3.4b Density-based P\* — η-midpoint (NPT-native, literature-standard)

In NPT the natural order parameter is η itself. The transition shows up
as a steep rise in ⟨η⟩(P), bracketed for hard disks (Bernard & Krauth
2011) by the literature values:

- η_L (liquid-spinodal side) ≈ **0.700**
- η_H (hexatic side) ≈ **0.716**
- η midpoint ≈ **0.708**

Define **P\*_η = pressure at which ⟨η⟩(P) crosses η_midpoint** (linear
interpolation between the bracketing data points). Bootstrap by resampling
each ⟨η⟩_i from N(mean, std-of-mean) where the std-of-mean uses
N_eff from §3.2.

For **hard squares or binary mixtures** the η-midpoint reduces to the
**η-inflection point** of ⟨η⟩(P) (sigmoid fit, or maximum slope from a
smoothing spline). Report the inflection P\* and the η values at the
upper and lower plateaus so the "η-jump" range is documented even
without a literature anchor. This is the §3.4-second-estimator for
non-disk compositions.

#### 3.4c Radial distribution and P(η) histograms

Always also compute, at every pressure:

- the **radial distribution function g(r)** (peaks sharpen and split as
  the system orders), and
- the **histogram P(η) of equilibrium volume fraction** over the
  equilibrated tail. At and near P\* this should show broadening (and
  ideally bimodality at coexistence). If your simulations are long enough
  to flip phases (`sample_steps` ≥ 5×10⁷ at modest N), report the
  pressure where P(η) is most balanced as a third independent P\* estimator
  (Lee–Kosterlitz). **If P(η) is unimodal at every pressure**, this is a
  signal that runs were not long enough to flip the phase even once at
  coexistence — note this explicitly in caveats but do not over-interpret.

#### 3.4d Definition of the "transition window"

Several rules in this document refer to the **transition window** —
defined operationally, post-Pass-1, as:

> the contiguous range of pressure values across which ⟨OP⟩(P) traverses
> the central 10–90 % of its rise — i.e. from
> ⟨OP⟩_low + 0.10·(⟨OP⟩_high − ⟨OP⟩_low) up to
> ⟨OP⟩_low + 0.90·(⟨OP⟩_high − ⟨OP⟩_low),
> where ⟨OP⟩_low and ⟨OP⟩_high are the plateau values on either side
> (equivalently, where ⟨η⟩(P) makes its steepest rise).

In practice this is a 2–4-point sub-range of your sweep; it is the
range where finite-N broadening lives and where the strictest
equilibration and statistics requirements apply. Identify it
immediately after Pass 1 completes, *before* doing the §3.2 eq-check
audit and *before* planning Pass 2 — Pass 2 should densely cover this
window.

### 3.5 Workflow

- Run the four ColPack stages in order, autonomously, with no
  user-confirmation pauses: setup → plan → execute → analyze.
- Use the autonomous workflow conventions: do not ask for approval between
  stages.
- After analyze, run the §3.2 equilibration check **before** the §3.4 P\*
  extraction. Re-execute under-equilibrated runs with more sample_steps
  before reporting.

---

## 4. Reporting

At the end, produce a **single final summary** containing:

1. **Composition** chosen and one-sentence rationale.
2. **Sweep parameters** actually used: N, `sample_steps`, pressure grid,
   number of points. If you iterated (either across pressure passes or
   re-ran for longer sample_steps), list every pass and explain why.
3. **Equilibration-check results** per run: η(t) plateau confirmation,
   `(n_frames − eq_start)/n_frames` fraction, τ_int and N_eff for ψ_6
   (or chosen OP) and η in the transition window. Flag any run that
   *barely* passed.
4. **Equation of state** — η vs. P (table or in-line numbers; describe
   the curve in words too).
5. **Orientational OP response** — your chosen OP vs P with sigmoid (or
   numerical) inflection point.
6. **Two P\* estimates with uncertainty**:
   - **P\*_η** from the η-midpoint method (NPT-native, primary).
   - **P\*_OP** from the orientational-OP inflection.
   - Discuss how they compare; the spread between them characterises the
     finite-N transition width.
7. **Plots (required)** — save PNG and PDF in the working dir; reference
   file paths in the summary. At minimum:
   - **η(P) headline plot** with literature η_L and η_H bands marked,
     P\*_η line and 68% CI band overlaid. Both passes overlaid if you
     refined.
   - **OP(P) plot** with the same P\*_η band marked for visual
     comparison, and the OP-inflection P\*_OP also marked.
   - **g(r) at three representative pressures** spanning the transition
     (one disordered, one near P\*, one ordered).
   - **P(η) per-pressure histograms** in the transition window. Even if
     unimodal, this is required so under-equilibration is visible.
   - **η(t) traces in the transition window** — direct visual evidence
     that runs are equilibrated.
8. **Caveats and limitations** — finite-size effects, equilibration
   uncertainty, autocorrelation budget, anything you would tighten in a
   follow-up study. If your P\* differs from the literature by more than
   the broader of (1) the finite-N expected shift and (2) your reported
   uncertainty, **investigate before reporting** — the most common cause
   is under-equilibration (re-run with more `sample_steps`).

The summary plus the plots are the primary scientific output. The
simulation working dirs and JSON files are supporting evidence.

---

## Appendix: Lessons from a prior under-equilibrated run

The first execution of this program used `sample_steps = 5×10⁵` (the
minimum recommended at the time) and produced P\* estimates off from the
literature value by ~1.7 k_BT/σ² — about 18 %. Diagnosis:

- η(t) traces showed *monotonic drift* across nearly the whole trajectory
  for every pressure; no plateau was reached.
- The analyze tool's equilibration detector flagged only the last ~10 %
  of frames as equilibrated, leaving ~500 frames per run.
- Integrated autocorrelation times of ψ_6 reached ~300 frames in the
  transition window, giving N_eff ≈ 1–2 per state point.
- P(η) histograms were strongly unimodal at every pressure (the system
  never flipped phases), making the Lee–Kosterlitz coexistence
  estimator unusable.
- The η-midpoint estimator with literature η_L and η_H values still gave
  a tight P\* ± 0.01, but it was offset from the literature P\* by ~1.7
  k_BT/σ² because the underlying ⟨η⟩(P) curve was systematically
  drift-biased — every η value was a few percent too low because the
  system had not yet relaxed up from the random initial configuration.

The rule that follows:

- The **§3.2 equilibration check is the ground truth**, not a fixed
  `sample_steps` number. The 5×10⁶ floor in §3.2 is preliminary
  guidance from a single hard-disk pilot — for hard squares, larger N,
  or a binary mixture, the actual minimum may be higher. **If runs
  routinely fail the eq-check at the §3.2 floor, raise the floor for
  this composition and document the new value.** Conversely, if a
  composition systematically passes the eq-check at well below the
  recommended ceiling, the ceiling for that case can be relaxed.
- A tight bootstrap uncertainty does NOT validate accuracy — it only
  validates internal consistency. Compare to literature whenever
  available; for cases without a literature anchor, the OP-vs-η
  estimator agreement (§3.4) is the next best check.

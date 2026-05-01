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

- the equation of state φ(P) — how volume fraction responds to pressure,
- a shape-appropriate orientational order parameter as a function of P,
- the radial distribution function g(r) supporting the OP interpretation.

The deliverable is the location of the transition pressure P* and a brief
discussion of what the curves reveal about the ordering mechanism.

---

## 2. Your Freedom (decide for yourself)

- **Composition.** Pick one: pure hard disks, pure hard squares, or a binary
  disk + square mixture. Justify your choice in one sentence at the start.
- **Pressure range and grid density.** Choose values that bracket the
  transition. If your first sweep does not resolve a clear order-parameter
  jump, refine the range and run a second sweep — this is encouraged.
- **Hypotheses and interpretation.** Decide what counts as the transition
  (e.g., a step in ψ_6, a kink in φ(P), divergent fluctuations) and defend
  the choice in your final summary.

---

## 3. Methodology Constraints (do NOT vary)

These are the parts that ensure the data is publication-grade rather than a
quick-look pilot. Override defaults explicitly via the planning tool.

### 3.1 System size

- **500 ≤ N ≤ 2000 particles** per simulation. Prefer N in the
  500–1500 range for production runs (cleaner statistics).
- Do not exceed N = 2000: simulation cost scales superlinearly and an
  oversized run will not finish within the task wall-time budget.

### 3.2 Sampling

- **5×10⁵ ≤ `sample_steps` ≤ 1×10⁶** MC sweeps per simulation.
- The ColPack default (5×10⁴) is intentionally short for plumbing tests and is
  **insufficient to resolve a transition** — set `sample_steps` explicitly in
  your `tunable_parameters` or via `baseline_parameters` when calling
  `plan_simulation_runs_tool`. Do not leave it at the default.
- Do not exceed 1×10⁶: longer runs will not finish within the task wall-time
  budget, and a sweep that times out mid-execution loses all of its data.
- Treat the first ~20 % of the trajectory as equilibration when interpreting
  the time series. Rely on the analyze tool's default block-averaging.

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

### 3.4 Order parameters

Choose by shape:

- **Hard disks**  → bond-orientational hexatic order parameter `psi_6`.
- **Hard squares** → cubatic / 4-fold orientational order parameter `P_4`.
- **Binary mixture** → report the appropriate OP for *each* species
  separately if the analysis tool supports per-species output.

Always also compute the **radial distribution function g(r)** at every
pressure to support the OP interpretation (peaks sharpen and split as the
system orders).

### 3.5 Workflow

- Run the four ColPack stages in order, autonomously, with no
  user-confirmation pauses: setup → plan → execute → analyze.
- Use the autonomous workflow conventions: do not ask for approval between
  stages.

---

## 4. Reporting

At the end, produce a **single final summary** containing:

1. **Composition** chosen and one-sentence rationale.
2. **Sweep parameters** actually used: N, `sample_steps`, pressure grid,
   number of points. If you iterated, list every pass.
3. **Equation of state** — φ vs. P (table or in-line numbers; a textual
   description of the curve is fine).
4. **Order parameter response** — your chosen OP vs. P, with whatever
   numerical evidence makes the transition legible.
5. **Identified transition pressure P***, with brief justification — e.g.
   "ψ_6 rises from ≈0.10 to ≈0.65 across P ∈ [4.6, 5.4], so P* ≈ 5.0".
6. **Plots (required)** showing the transition clearly. At minimum:
   - **Order parameter vs. pressure** (your chosen OP, e.g. ψ_6 vs P for
     disks or P_4 vs P for squares) — this is the headline plot and
     must clearly show the OP jump at P\*.
   - **Equation of state φ vs. P**.
   - **g(r) at a few representative pressures** spanning the transition
     (one disordered, one near P\*, one ordered).

   Save plots as PNG or PDF inside the simulation `working_dir` (or a
   subdirectory of it) and reference their file paths in the summary. If
   you ran a refinement pass, the OP-vs-P plot should overlay (or
   include) both the coarse and refined data so the iteration is visible.
7. **Caveats and limitations** — e.g. finite-size effects, equilibration
   uncertainty, anything you would tighten in a follow-up study.

The summary plus the plots are the primary scientific output. The
simulation working dirs and JSON files are supporting evidence.

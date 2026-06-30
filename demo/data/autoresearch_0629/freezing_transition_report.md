# 2D Hard-Disk Freezing Transition (NPT) — Final Report

**System:** 2D hard disks, σ=1, N=512, NPT (HOOMD-blue HPMC via ColPack).
**Goal:** locate freezing pressure P\* via ψ_6(P) and η(P).
**Pressure units:** ColPack reduced P (≈ βPσ²); literature transition ≈ 9.2.

## 1. Sweep history

| Iter | working_dir | sample_steps | P grid | rationale |
|------|-------------|--------------|--------|-----------|
| 1 | `2d_npt_disk`    | 2×10⁵ (exploratory) | 4,6,8,10,12,14 | coarse bracket |
| 2 | `2d_npt_disk_v2` | 1×10⁶ (refinement)  | 10,11,12,13,14,15,16,18,20 | extend to solid; **revealed iter-1 under-equilibration** |
| 3 | `2d_npt_disk_v3` | 2×10⁶ (refinement)  | 6,7,8,8.5,9,9.5,10 | map fluid branch + true transition |
| 4 | `2d_npt_disk_v4` | 2×10⁶ (refinement)  | 8.75,9.25 | densify rising edge for sigmoid |

**Why the escalation:** iter-1 (2×10⁵) passed the auto eq-check at every P yet gave
*qualitatively wrong* results in the transition/solid region — at P=10, η=0.690,
ψ_6=0.235 (looks fluid), whereas the converged value is η=0.737, ψ_6=0.812 (solid).
The short trajectory sits in a metastable disordered state that is genuinely
stationary over the sampling window, so the detector false-positives. Fluid points
were unaffected (P=6: 0.627/0.064 @2×10⁵ ≈ 0.635/0.067 @2×10⁶). At P=10 the 1×10⁶
and 2×10⁶ results agree (0.735/0.810 vs 0.737/0.812), confirming convergence by
≥1×10⁶ outside the immediate transition point. Estimators use iter-2/3/4 only
(all ≥1×10⁶); iter-1 retained as the cautionary cross-check above.

## 2. Equilibration-check results

All 17 contributing runs: `equilibrated == true` for both η and ψ_6. **None hit
the 5×10⁶ absolute cap; no run required escalation for a failed eq-check.** The
auto-detector chose conservative late cutoffs (eq_start ≈ frame 16k–18k of 20k at
2×10⁶; ≈ 8k–9k of 10k at 1×10⁶); the η(t) traces show flat plateaus well before
those cutoffs, so means are taken over the most-stationary tail (≥1000–2700 frames).

## 3. η(P) and ψ_6(P) with per-point block-bootstrap σ

Block bootstrap: per-point block length L = clip(2τ, 50, n_tail/8) frames, τ =
integrated autocorrelation time per observable; 2000 resamples.

| P | ss | η | σ(η) | ψ_6 | σ(ψ_6) | eq |
|------|-----|--------|--------|--------|--------|----|
| 6.00 | 2e6 | 0.6353 | 0.0012 | 0.0673 | 0.0012 | ✓ |
| 7.00 | 2e6 | 0.6562 | 0.0006 | 0.0920 | 0.0028 | ✓ |
| 8.00 | 2e6 | 0.6713 | 0.0005 | 0.1168 | 0.0045 | ✓ |
| 8.50 | 2e6 | 0.6767 | 0.0004 | 0.1374 | 0.0057 | ✓ |
| 8.75 | 2e6 | 0.6881 | 0.0007 | 0.2091 | 0.0181 | ✓ |
| 9.00 | 2e6 | 0.7023 | 0.0010 | 0.5180 | 0.0183 | ✓ |
| 9.25 | 2e6 | 0.7272 | 0.0005 | 0.7805 | 0.0013 | ✓ |
| 9.50 | 2e6 | 0.7299 | 0.0006 | 0.7879 | 0.0011 | ✓ |
| 10.00 | 2e6 | 0.7366 | 0.0011 | 0.8123 | 0.0035 | ✓ |
| 11.00 | 1e6 | 0.7375 | 0.0005 | 0.7717 | 0.0039 | ✓ |
| 12.00 | 1e6 | 0.7525 | 0.0006 | 0.8339 | 0.0019 | ✓ |
| 13.00 | 1e6 | 0.7580 | 0.0004 | 0.8423 | 0.0011 | ✓ |
| 14.00 | 1e6 | 0.7677 | 0.0003 | 0.8820 | 0.0007 | ✓ |
| 15.00 | 1e6 | 0.7742 | 0.0003 | 0.8786 | 0.0009 | ✓ |
| 16.00 | 1e6 | 0.7824 | 0.0002 | 0.8874 | 0.0006 | ✓ |
| 18.00 | 1e6 | 0.8003 | 0.0003 | 0.9345 | 0.0004 | ✓ |
| 20.00 | 1e6 | 0.8046 | 0.0001 | 0.9259 | 0.0004 | ✓ |

## 4. P\* estimates (estimator-level block bootstrap, N=2000)

| Estimator | Point | 1σ CI (16/84) | 95% CI (2.5/97.5) | LOO max shift |
|-----------|-------|---------------|-------------------|---------------|
| **P\*_OP** (ψ_6 sigmoid inflection) | **8.97** | [8.97, 8.99] | [8.96, 9.00] | 0.017 |
| **P\*_η** (η = 0.708 crossing)       | **9.06** | [9.05, 9.07] | [9.04, 9.07] | 0.052 |

**Agreement:** the two estimators bracket P\* ≈ 9.0; their spread
P\*_η − P\*_OP = **0.084** is the finite-N transition width (≈ 0.9 % of P\*). Both are
consistent with the literature 2D hard-disk transition (βPσ² ≈ 9.2) to within ~2 %.

## 5. Sensitivity bound (leave-one-out)

Dropping each pressure in turn: P\*_OP shifts by ≤ 0.017; P\*_η by ≤ 0.052 (largest
when dropping P=9.00, the point straddling the η=0.708 level). **The P\*_η grid
sensitivity (0.052) exceeds its bootstrap 1σ half-width (~0.008) and its 95 % CI
half-width (~0.016)** — i.e. the dominant uncertainty is *which pressures were
sampled*, not within-run statistics. Honest combined estimate:

> **P\* ≈ 9.0 ± 0.1** (reduced pressure), with finite-N transition width ≈ 0.08.

## 6. Plots (in `data/2d_npt_disk_v3/`)

- `eta_vs_P_final.png` — η(P), literature η_L–η_H band, P\*_η marked, error bars.
- `psi6_vs_P_final.png` — ψ_6(P), logistic fit, P\*_OP marked, error bars.
- `gr_final.png` — g(r) at P=6 (disordered), 9 (near P\*), 20 (ordered crystal,
  split second peak).
- `eta_traces_final.png` — η(t) traces across the transition window (visual eq-check).

Machine-readable: `data/2d_npt_disk_v3/summary_final.json`.

## 7. Caveats

- **Tight bootstrap CIs are within-run precision, not model uncertainty.** Sub-1 %
  CIs reflect long trajectories with many equilibrated frames; the *real* spread
  comes from grid choice (§5) and finite N. Trust **±0.1**, not ±0.01.
- **Under-equilibration is the dominant systematic** and was explicitly caught:
  the auto eq-check gives false positives in the transition/solid region at short
  sample_steps. Mitigated by running the transition window at 2×10⁶ and
  cross-checking 1×10⁶↔2×10⁶ at P=10. The single transition point P=9.00 retains
  the largest residual tail drift (Δη≈−0.005 between tail halves) and the longest
  autocorrelation (τ_η≈616, τ_ψ≈127 frames) — its σ is partly a floor.
- **Finite-N bias (N=512) not quantified.** The transition appears first-order-like
  here (near-step in η between P=9.0 and 9.25); the true 2D-melting scenario
  (KTHNY two-step hexatic) and the precise P\* are N-dependent. A finite-size
  sub-sweep (N=256/512/1024) would be needed to extrapolate to the thermodynamic
  limit — recommended next step.
- **Hysteresis not probed.** All runs were compressed from a dilute fluid; melting
  (decompression) runs could differ in the coexistence region and would bound
  hysteresis at this N.

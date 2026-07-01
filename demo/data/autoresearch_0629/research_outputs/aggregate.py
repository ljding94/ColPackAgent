#!/usr/bin/env python
"""
Aggregate the 0629 autoresearch sweep into `pstar_estimates.json`, the schema
consumed by ``plot/demo_plot.py::plot_autoresearch_demo``.

The 0629 run stores each agent iteration in its own working dir
(``2d_npt_disk`` = iter 1 ... ``2d_npt_disk_v4`` = iter 4) and is analysed by the
sibling ``analyze_freezing.py``. This script reuses that module's loading and
statistics so the main-text figure stays consistent with the SI plots/report:

- one accepted point per pressure (largest ``sample_steps`` wins; short
  under-equilibrated iter-1 runs are superseded), tagged with the iteration
  that produced it;
- per-point block-bootstrap sigma (same estimator as the SI);
- P* and logistic parameters fit on iter-2/3/4 only (the >=1e6-step runs), which
  reproduces the SI values P*_psi6 ~ 8.97 and P*_eta ~ 9.06.
"""
import importlib.util
import json
from pathlib import Path

import numpy as np

BASE = Path(__file__).resolve().parents[1]  # .../autoresearch_0629

# iteration index -> working dir
ITER_DIRS = {
    1: "2d_npt_disk",
    2: "2d_npt_disk_v2",
    3: "2d_npt_disk_v3",
    4: "2d_npt_disk_v4",
}
# iterations used for the point estimates / logistic fit (>=1e6 sample steps)
ESTIMATOR_ITERS = (2, 3, 4)


def _load_analyze_module():
    spec = importlib.util.spec_from_file_location(
        "analyze_freezing", BASE / "analyze_freezing.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def main():
    af = _load_analyze_module()

    # Load every run, tagged with the iteration it belongs to.
    all_runs = []
    for it, sub in ITER_DIRS.items():
        for r in af.load_dirs([str(BASE / sub)]):
            r["iteration"] = it
            all_runs.append(r)

    # One accepted run per pressure: prefer the largest sample_steps.
    best = {}
    for r in all_runs:
        key = round(r["P"], 4)
        if key not in best or r["sample_steps"] > best[key]["sample_steps"]:
            best[key] = r
    accepted = [best[k] for k in sorted(best)]

    def block_sigma(run, which):
        tail = af.eq_tail(run, which)
        L = af.choose_L(tail, af.autocorr_time(tail))
        return float(af.block_boot_std(tail, L))

    per_point = []
    for r in accepted:
        per_point.append(
            dict(
                iteration=int(r["iteration"]),
                P=float(r["P"]),
                sample_steps=int(r["sample_steps"]),
                eta_eq_mean=float(r["eta_mean"]),
                psi6_eq_mean=float(r["psi_mean"]),
                eta_boot_sigma=block_sigma(r, "eta"),
                psi6_boot_sigma=block_sigma(r, "psi"),
                run_equilibrated=bool(r["eta_eq"] and r["psi_eq"]),
            )
        )

    # Point estimates / logistic fit from the converged iterations only.
    est = [r for r in accepted if r["iteration"] in ESTIMATOR_ITERS]
    P = np.array([r["P"] for r in est])
    eta_m = np.array([r["eta_mean"] for r in est])
    psi_m = np.array([r["psi_mean"] for r in est])

    pstar_op, popt = af.fit_Pstar_OP(P, psi_m)
    pstar_eta = af.Pstar_eta(P, eta_m)
    if popt is None:
        raise RuntimeError("logistic fit for psi_6(P) did not converge")

    # analyze_freezing.logistic(P, a, b, P0, w) = a + (b-a)/(1+exp(-(P-P0)/w))
    # demo_plot sigmoid       = A + B/(1+exp(-k*(P-x0)))
    a, b, P0, w = (float(x) for x in popt)
    sigmoid_params = dict(A=a, B=b - a, k=1.0 / w, x0=P0)

    out = dict(
        literature=dict(
            pstar=9.185,
            eta_low=float(af.ETA_L),
            eta_high=float(af.ETA_H),
            eta_midpoint=float(af.ETA_MID),
            source="Bernard & Krauth, 2011",
        ),
        point_estimates=dict(
            pstar_op=float(pstar_op),
            pstar_eta=float(pstar_eta),
            sigmoid_params=sigmoid_params,
        ),
        estimator_iterations=list(ESTIMATOR_ITERS),
        per_point=per_point,
    )

    out_path = Path(__file__).resolve().parent / "pstar_estimates.json"
    with out_path.open("w", encoding="utf-8") as handle:
        json.dump(out, handle, indent=2)

    print(f"wrote {out_path}")
    print(f"  points: {len(per_point)} (estimators from iters {ESTIMATOR_ITERS})")
    print(f"  P*_psi6 = {pstar_op:.3f}   P*_eta = {pstar_eta:.3f}")


if __name__ == "__main__":
    main()

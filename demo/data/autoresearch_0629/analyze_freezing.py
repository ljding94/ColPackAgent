#!/usr/bin/env python
"""
2D hard-disk NPT freezing-transition analysis for ColPackAgent study.
Aggregates across iteration working dirs, computes block-bootstrap uncertainty,
two P* estimators (P*_OP sigmoid inflection of psi6(P); P*_eta crossing of
eta=0.708), estimator-level bootstrap CIs, leave-one-out sensitivity, and plots.
"""
import json, glob, os, sys
import numpy as np
from scipy.optimize import curve_fit

rng = np.random.default_rng(12345)

ETA_MID = 0.708          # literature freezing/melting midpoint
ETA_L, ETA_H = 0.700, 0.716  # literature fluid/solid packing-fraction bounds

# ---------------------------------------------------------------- loading
def psi6_mag(series):
    return np.array([np.hypot(c['real'], c['imag']) for c in series])

def load_run(run_dir):
    cfg = json.load(open(os.path.join(run_dir, 'simulation_config.json')))
    d = json.load(open(os.path.join(run_dir, 'analysis_results.json')))
    h = d['disk_0']['equilibrium']['per_parameter']['hexatic_6']
    v = d['system']['equilibrium']['per_parameter']['volume_fraction']
    eta = np.asarray(d['system']['volume_fraction'], float)
    psi = psi6_mag(d['disk_0']['hexatic_6'])
    return dict(
        P=float(cfg['P']), sample_steps=int(cfg['sample_steps']), run_dir=run_dir,
        eta=eta, psi=psi,
        eta_eqi=int(v['eq_start_index']), psi_eqi=int(h['eq_start_index']),
        eta_eq=bool(v['equilibrated']), psi_eq=bool(h['equilibrated']),
        eta_mean=float(v['eq_mean']), eta_std=float(v['eq_std']),
        psi_mean=float(h['eq_mean']), psi_std=float(h['eq_std']),
        traj=os.path.join(run_dir, 'sample_trajectory.gsd'),
    )

def load_dirs(dirs):
    runs = []
    for wd in dirs:
        for rd in sorted(glob.glob(wd + '/run_*'), key=lambda p: int(p.split('_')[-1])):
            if os.path.exists(os.path.join(rd, 'analysis_results.json')):
                runs.append(load_run(rd))
    return runs

def build_dataset(runs, min_ss=1):
    """One entry per pressure, preferring the largest sample_steps."""
    best = {}
    for r in runs:
        if r['sample_steps'] < min_ss:
            continue
        key = round(r['P'], 4)
        if key not in best or r['sample_steps'] > best[key]['sample_steps']:
            best[key] = r
    return [best[k] for k in sorted(best)]

# ---------------------------------------------------------------- stats
def eq_tail(r, which):
    if which == 'eta':
        return r['eta'][r['eta_eqi']:]
    return r['psi'][r['psi_eqi']:]

def autocorr_time(x):
    """Integrated autocorrelation time (frames), summed until ACF<0."""
    x = np.asarray(x, float); x = x - x.mean()
    n = len(x); var = np.dot(x, x) / n
    if var == 0:
        return 1.0
    acf = np.correlate(x, x, 'full')[n-1:] / (var * n)
    tau = 1.0
    for k in range(1, n):
        if acf[k] <= 0:
            break
        tau += 2 * acf[k]
    return tau

def choose_L(x, tau=None):
    """Block length: target 2*tau, floor 50, cap n/8 (keep >=8 resampling blocks)."""
    n = len(x)
    if tau is None:
        tau = autocorr_time(x)
    return int(np.clip(round(2 * tau), 50, max(50, n // 8)))

def block_boot_std(x, L, nboot=2000):
    """Std of block-bootstrap resampled means (blocks length L, with replacement)."""
    x = np.asarray(x, float); n = len(x)
    if n < 2:
        return 0.0
    L = int(min(L, n))
    nblocks = int(np.ceil(n / L))
    starts = np.arange(0, n - L + 1)
    if len(starts) == 0:
        starts = np.array([0])
    means = np.empty(nboot)
    for b in range(nboot):
        s = rng.choice(starts, size=nblocks)
        means[b] = np.concatenate([x[i:i+L] for i in s])[:n].mean()
    return means.std(ddof=1)

def block_resample_mean(x, L):
    x = np.asarray(x, float); n = len(x)
    L = int(min(L, n)); nblocks = int(np.ceil(n / L))
    starts = np.arange(0, n - L + 1)
    if len(starts) == 0:
        starts = np.array([0])
    s = rng.choice(starts, size=nblocks)
    return np.concatenate([x[i:i+L] for i in s])[:n].mean()

# ---------------------------------------------------------------- estimators
def logistic(P, a, b, P0, w):
    return a + (b - a) / (1.0 + np.exp(-(P - P0) / w))

def fit_Pstar_OP(P, psi):
    P = np.asarray(P, float); psi = np.asarray(psi, float)
    a0, b0 = psi.min(), psi.max()
    P0 = P[np.argmax(np.gradient(psi, P))]
    try:
        popt, _ = curve_fit(logistic, P, psi, p0=[a0, b0, P0, 0.5],
                            maxfev=20000,
                            bounds=([-0.5, 0, P.min(), 1e-3],
                                    [0.5, 1.5, P.max(), 10]))
        return float(popt[2]), popt
    except Exception:
        # fallback: discrete maximum-slope midpoint
        g = np.gradient(psi, P)
        return float(P[np.argmax(g)]), None

def Pstar_eta(P, eta, level=ETA_MID):
    """Linear interpolation: lowest P where eta crosses `level`."""
    P = np.asarray(P, float); eta = np.asarray(eta, float)
    o = np.argsort(P); P, eta = P[o], eta[o]
    for i in range(len(P) - 1):
        a, b = eta[i], eta[i+1]
        if (a - level) * (b - level) <= 0 and b != a:
            return float(P[i] + (level - a) * (P[i+1] - P[i]) / (b - a))
    return float('nan')

# ---------------------------------------------------------------- RDF
def compute_rdf(traj, eqi, rmax=6.0, bins=150, max_frames=300):
    import gsd.hoomd, freud
    t = gsd.hoomd.open(traj, 'r')
    n = len(t)
    idx = list(range(eqi, n))
    if len(idx) > max_frames:
        idx = idx[::max(1, len(idx)//max_frames)]
    rdf = freud.density.RDF(bins=bins, r_max=rmax)
    for i in idx:
        f = t[i]
        box = f.configuration.box
        rdf.compute(system=(box, f.particles.position), reset=False)
    return rdf.bin_centers.copy(), rdf.rdf.copy()

# ---------------------------------------------------------------- main
def main(dirs, outdir, tag, label_v1_dir=None):
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    runs = load_dirs(dirs)
    ds = build_dataset(runs)
    P = np.array([r['P'] for r in ds])

    # per-point block lengths from per-observable autocorrelation times
    et = [eq_tail(r, 'eta') for r in ds]
    pt = [eq_tail(r, 'psi') for r in ds]
    taus_eta = [autocorr_time(x) for x in et]
    taus_psi = [autocorr_time(x) for x in pt]
    L_eta = [choose_L(x, t) for x, t in zip(et, taus_eta)]
    L_psi = [choose_L(x, t) for x, t in zip(pt, taus_psi)]

    eta_m = np.array([r['eta_mean'] for r in ds])
    psi_m = np.array([r['psi_mean'] for r in ds])
    eta_sig = np.array([block_boot_std(x, L) for x, L in zip(et, L_eta)])
    psi_sig = np.array([block_boot_std(x, L) for x, L in zip(pt, L_psi)])

    print("\n# P    ss      eta     sig_eta   psi6    sig_psi  eqE eqP  tau_e tau_p  L_e L_p  Ntail")
    for r, em, es, pm, ps, te, tp, le, lp in zip(ds, eta_m, eta_sig, psi_m, psi_sig,
                                                 taus_eta, taus_psi, L_eta, L_psi):
        flag = ' <flag:tau~tail' if (te > len(eq_tail(r, 'eta')) / 8) else ''
        print("%5.2f %7d %.4f %.4f   %.4f %.4f   %d   %d  %5.1f %5.1f  %4d %4d  %d%s" % (
            r['P'], r['sample_steps'], em, es, pm, ps, r['eta_eq'], r['psi_eq'],
            te, tp, le, lp, len(eq_tail(r, 'eta')), flag))

    # point estimates
    P0_OP, popt = fit_Pstar_OP(P, psi_m)
    P0_eta = Pstar_eta(P, eta_m)
    print(f"\n# Point estimates:  P*_OP={P0_OP:.3f}   P*_eta={P0_eta:.3f}")

    # estimator-level bootstrap
    NB = 2000
    bOP = np.empty(NB); bETA = np.empty(NB)
    for b in range(NB):
        eta_b = np.array([block_resample_mean(x, L) for x, L in zip(et, L_eta)])
        psi_b = np.array([block_resample_mean(x, L) for x, L in zip(pt, L_psi)])
        bOP[b], _ = fit_Pstar_OP(P, psi_b)
        bETA[b] = Pstar_eta(P, eta_b)
    def ci(x):
        x = x[np.isfinite(x)]
        if len(x) == 0:
            return (float('nan'),) * 5
        return (np.median(x), np.percentile(x, 16), np.percentile(x, 84),
                np.percentile(x, 2.5), np.percentile(x, 97.5))
    cOP, cETA = ci(bOP), ci(bETA)
    print("\n# Estimator-level bootstrap (N=%d):" % NB)
    print("#  P*_OP : med=%.3f  1sig[%.3f,%.3f]  95%%[%.3f,%.3f]" % cOP)
    print("#  P*_eta: med=%.3f  1sig[%.3f,%.3f]  95%%[%.3f,%.3f]" % cETA)

    # leave-one-out
    print("\n# Leave-one-out sensitivity:")
    loo_OP, loo_eta = [], []
    for j in range(len(P)):
        m = np.ones(len(P), bool); m[j] = False
        oOP, _ = fit_Pstar_OP(P[m], psi_m[m])
        oeta = Pstar_eta(P[m], eta_m[m])
        loo_OP.append(oOP); loo_eta.append(oeta)
    loo_OP = np.array(loo_OP); loo_eta = np.array(loo_eta)
    def loo_report(loo, P0, name):
        d = np.abs(loo - P0)
        if not np.any(np.isfinite(d)):
            print("#  max |d%s| = nan (no finite leave-one-out estimate)" % name)
            return float('nan')
        j = int(np.nanargmax(d))
        print("#  max |d%s| = %.3f (dropping P=%.2f)" % (name, np.nanmax(d), P[j]))
        return float(np.nanmax(d))
    dOP = loo_report(loo_OP, P0_OP, "P*_OP")
    deta = loo_report(loo_eta, P0_eta, "P*_eta")

    # ----- plots
    os.makedirs(outdir, exist_ok=True)
    # eta(P)
    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.errorbar(P, eta_m, yerr=eta_sig, fmt='o-', capsize=3, color='C0')
    ax.axhspan(ETA_L, ETA_H, color='gray', alpha=0.2, label=r'$\eta_L$–$\eta_H$ (lit.)')
    ax.axhline(ETA_MID, ls='--', color='k', lw=0.8)
    ax.axvline(P0_eta, color='C3', ls='-', label=r'$P^*_\eta=%.2f$' % P0_eta)
    ax.axvspan(cETA[1], cETA[2], color='C3', alpha=0.2)
    ax.set_xlabel('P (reduced)'); ax.set_ylabel(r'$\langle\eta\rangle$')
    ax.set_title(r'Packing fraction $\eta(P)$ — 2D hard disks, N=512, NPT')
    ax.legend(); fig.tight_layout(); fig.savefig(f'{outdir}/eta_vs_P_{tag}.png', dpi=140); plt.close(fig)

    # psi6(P)
    fig, ax = plt.subplots(figsize=(6, 4.2))
    ax.errorbar(P, psi_m, yerr=psi_sig, fmt='o', capsize=3, color='C1', label='data')
    if popt is not None:
        xx = np.linspace(P.min(), P.max(), 300)
        ax.plot(xx, logistic(xx, *popt), '-', color='C0', label='logistic fit')
    ax.axvline(P0_OP, color='C2', ls='-', label=r'$P^*_{OP}=%.2f$' % P0_OP)
    ax.axvspan(cOP[1], cOP[2], color='C2', alpha=0.2)
    ax.set_xlabel('P (reduced)'); ax.set_ylabel(r'$\psi_6$')
    ax.set_title(r'Hexatic order $\psi_6(P)$ — 2D hard disks, N=512, NPT')
    ax.legend(); fig.tight_layout(); fig.savefig(f'{outdir}/psi6_vs_P_{tag}.png', dpi=140); plt.close(fig)

    # g(r) at three pressures spanning the transition
    lo = ds[0]
    mid = min(ds, key=lambda r: abs(r['P'] - P0_OP))
    hi = ds[-1]
    fig, ax = plt.subplots(figsize=(6, 4.2))
    for r, lab, col in [(lo, 'disordered', 'C0'), (mid, 'near $P^*$', 'C1'), (hi, 'ordered', 'C3')]:
        rr, gg = compute_rdf(r['traj'], r['eta_eqi'])
        ax.plot(rr, gg, color=col, label=f"P={r['P']:.1f} ({lab})")
    ax.set_xlabel('r / $\\sigma$'); ax.set_ylabel('g(r)')
    ax.set_title('Radial distribution function'); ax.legend()
    fig.tight_layout(); fig.savefig(f'{outdir}/gr_{tag}.png', dpi=140); plt.close(fig)

    # eta(t) traces in transition window
    fig, ax = plt.subplots(figsize=(6.5, 4.2))
    win = [r for r in ds if P0_OP - 2.5 <= r['P'] <= P0_OP + 2.5]
    for r in win:
        ax.plot(np.arange(len(r['eta'])), r['eta'], lw=0.7, label="P=%.1f" % r['P'])
        ax.axvline(r['eta_eqi'], color='gray', lw=0.4, alpha=0.3)
    ax.axhline(ETA_MID, ls='--', color='k', lw=0.8)
    ax.set_xlabel('frame'); ax.set_ylabel(r'$\eta(t)$')
    ax.set_title('Volume-fraction traces (transition window); gray = eq cutoff')
    ax.legend(fontsize=8, ncol=2); fig.tight_layout()
    fig.savefig(f'{outdir}/eta_traces_{tag}.png', dpi=140); plt.close(fig)

    # dump summary json
    summary = dict(
        tau_eta_max=float(max(taus_eta)), tau_psi_max=float(max(taus_psi)),
        points=[dict(P=r['P'], sample_steps=r['sample_steps'], run_dir=r['run_dir'],
                     eta=float(em), sig_eta=float(es), psi6=float(pm), sig_psi6=float(ps),
                     eta_equilibrated=r['eta_eq'], psi_equilibrated=r['psi_eq'],
                     eta_eqi=r['eta_eqi'], psi_eqi=r['psi_eqi'],
                     L_eta=int(le), L_psi=int(lp),
                     tau_eta=float(te), tau_psi=float(tp),
                     n_tail_eta=len(eq_tail(r, 'eta')))
                for r, em, es, pm, ps, te, tp, le, lp in
                zip(ds, eta_m, eta_sig, psi_m, psi_sig, taus_eta, taus_psi, L_eta, L_psi)],
        Pstar_OP=dict(point=P0_OP, median=cOP[0], ci1=[cOP[1], cOP[2]], ci95=[cOP[3], cOP[4]],
                      loo_max_shift=float(dOP)),
        Pstar_eta=dict(point=P0_eta, median=cETA[0], ci1=[cETA[1], cETA[2]], ci95=[cETA[3], cETA[4]],
                       loo_max_shift=float(deta)),
    )
    json.dump(summary, open(f'{outdir}/summary_{tag}.json', 'w'), indent=2)
    print("\n# wrote plots + summary to", outdir, "tag", tag)
    return summary

if __name__ == '__main__':
    dirs = sys.argv[1].split(',')
    outdir = sys.argv[2]
    tag = sys.argv[3]
    main(dirs, outdir, tag)

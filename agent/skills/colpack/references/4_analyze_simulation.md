# Guide: Analyze Simulation Runs

Use `analyze_simulation_runs_tool` after `execute_simulation_workflow_tool` has completed the initialize, compress, and sample steps. This tool computes order parameters, RDF, and plots for each sampled run directory.

## Payload Shape

```json
{
  "working_dir": "/absolute/path/to/working_dir",
  "continue_on_error": true,
  "wait": false
}
```

## Required Rules

- `working_dir` must be the same path used in setup, planning, and execution.
- `working_dir` must contain `simulation_plan.json` and completed `run_*/` directories with sampled trajectories.
- Use `continue_on_error: true` for sweeps so one failed analysis does not stop the rest.
- Use `continue_on_error: false` when fail-fast behavior is desired.
- `wait` defaults to `false`; use `wait: false` for normal workflows to avoid MCP timeouts.
- Set `wait: true` only when the user explicitly asks for blocking execution.
- Runs where `analyze == "O"` in `workflow_status.csv` are automatically skipped (idempotent).
- After an async analyze call, do not automatically poll status in a loop. The agent wrapper (`scripts/workflow_monitor.py`) polls `workflow_progress.json` and `workflow_events.log` and prints live updates automatically.

## Valid Example: Standard Async Analysis

```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": true,
  "wait": false
}
```

## Valid Example: Blocking Analysis (short sweeps only)

```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": false,
  "wait": true
}
```

## Return Keys

### Async mode (`wait=false`)

| Key | Type | Description |
|-----|------|-------------|
| `ok` | `bool` | `true` on success |
| `mode` | `"async"` | Always `"async"` in this mode |
| `job_id` | `str` | Background job identifier (prefix `az_`) |
| `job_status` | `str` | `"running"` |
| `already_running` | `bool` | `true` if an existing analyze job was reused |
| `status_path` | `str` | Path to `workflow_status.csv` |
| `log_path` | `str` | Path to `workflow_events.log` |
| `progress` | `dict \| null` | Latest snapshot from `workflow_progress.json` |

### Sync mode (`wait=true`)

| Key | Type | Description |
|-----|------|-------------|
| `ok` | `bool` | `true` on success |
| `mode` | `"sync"` | Always `"sync"` in this mode |
| `status_path` | `str` | Path to `workflow_status.csv` |
| `progress_path` | `str` | Path to `workflow_progress.json` |
| `log_path` | `str` | Path to `workflow_events.log` |
| `n_runs` | `int` | Total planned runs |
| `n_success` | `int` | Runs successfully analyzed |
| `n_failed` | `int` | Runs that failed analysis |

## Mandatory Failure Handling

If `n_failed > 0` (sync) or the user reports failures:

1. Read `workflow_status.csv` in `working_dir`.
2. Find rows with `status=failed` and `analyze` column not `O`.
3. Extract:
   - `run_number`
   - `error`
   - `analyze` step marker
4. Report concise diagnosis and suggested correction.

## Preflight Check

Before calling analyze, verify execution completed successfully:

- `workflow_status.csv` exists with `sample == "O"` for target runs.
- No execution job is currently running for the same `working_dir` (analyze and execute must not run concurrently).

## Quick Diagnosis Patterns

- `simulation_plan.json not found`: planning or execution was not run in this `working_dir`.
- `No trajectory file found`: sample step did not complete for that run; re-run execution first.
- `freud` import error: analysis dependencies not installed in the current environment.
- Failures only on specific shapes: check shape-specific order parameter config in `colpack_config.json`.

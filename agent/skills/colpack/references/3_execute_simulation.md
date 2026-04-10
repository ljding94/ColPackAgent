# Guide: Execute Workflow And Troubleshoot

Use `execute_simulation_workflow_tool` after setup and planning are complete.
## Payload Shape
```json
{
  "working_dir": "/absolute/or/user/provided/path",
  "continue_on_error": true,
  "wait": false
}
```

## Required Rules
- `working_dir` must contain `simulation_plan.json`.
- `working_dir` must be exactly the same string used in setup and planning (`WORKING_DIR`).
- Use `continue_on_error: true` for broad sweeps so one failed run does not stop all runs.
- Use `continue_on_error: false` when users want fail-fast behavior.
- `wait` defaults to `false`; omit it or set `wait: false` for normal long-running workflows.
- Set `wait: true` only when user explicitly asks for blocking execution.
- The standalone wrapper already shows local workflow progress for async execution.
- After an async execute call, do not automatically poll `get_simulation_workflow_status_tool` in a loop.
- Use `get_simulation_workflow_status_tool` only when the user explicitly asks for a status check or when local progress is unavailable.
## Valid Example: Continue Past Failures
```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": true,
  "wait": false
}
```

## Valid Example: Fail Fast
```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": false,
  "wait": true
}
```

## Polling Payload Shape
```json
{
  "working_dir": "data/2d_nvt_disk_capsule"
}
```

or

```json
{
  "job_id": "wf_abc123def456"
}
```
## Expected Result Keys
The tool returns:
- `status_path`
- `n_runs`
- `n_success`
- `n_failed`

Async mode returns:
- `mode: "async"`
- `job_id`
- `job_status`
- `already_running`
- `progress` (latest local progress snapshot if available)

Polling returns:
- `job` object with `status` in `running|completed|failed`
- current `n_success` and `n_failed` from `workflow_status.csv`

## Mandatory Failure Handling
If `n_failed > 0`:
1. Read `workflow_status.csv` in `working_dir`.
2. Find rows with `status=failed`.
3. Extract at least:
  - `run_number`
  - `error`
  - failed step markers (`initialize`, `compress`, `sample`, `analyze`)
4. Report concise diagnosis and suggested correction.
## Preflight Consistency Check
Before execution, verify:

```json
{
  "setup_working_dir": "data/2d_nvt_disk_capsule",
  "plan_working_dir": "data/2d_nvt_disk_capsule",
  "execute_working_dir": "data/2d_nvt_disk_capsule",
  "all_match": true
}
```

Only execute when `all_match` is true.

## Timeout-Safe Workflow Pattern
1. Call `execute_simulation_workflow_tool` with `wait=false`.
2. Let the wrapper's local monitor report progress from `workflow_progress.json`.
3. If the user asks for a fresh status check, call `get_simulation_workflow_status_tool` once.
4. If `job.status=completed`, report final summary.
5. If `job.status=failed`, report `job.error` and inspect `workflow_status.csv`.
## Quick Diagnosis Patterns
- `simulation_plan.json not found`: planning step did not run in this `working_dir`.
- `Missing 'particle_specs'`: baseline/plan input was malformed.
- `Missing 'dimension'`: setup result was not carried into planning correctly.
- Failures during `compress` or `sample`: likely invalid shape parameters or unstable state point; adjust sweep bounds.

## Suggested Recovery Responses
- Confirm same `working_dir` was used for all three tools.
- Narrow tunable range and rerun execution.
- Fix malformed dot paths in `baseline_parameters` or `tunable_parameters` and re-plan.
# Guide: Execute Workflow And Troubleshoot

Use `execute_simulation_workflow_tool` after setup and planning are complete.
## Payload Shape
```json
{
  "working_dir": "/absolute/or/user/provided/path",
  "continue_on_error": true
}
```

## Required Rules
- `working_dir` must contain `simulation_plan.json`.
- `working_dir` must be exactly the same string used in setup and planning (`WORKING_DIR`).
- Use `continue_on_error: true` for broad sweeps so one failed run does not stop all runs.
- Use `continue_on_error: false` when users want fail-fast behavior.
## Valid Example: Continue Past Failures
```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": true
}
```

## Valid Example: Fail Fast
```json
{
  "working_dir": "data/2d_nvt_disk_capsule",
  "continue_on_error": false
}
```
## Expected Result Keys
The tool returns:
- `status_path`
- `n_runs`
- `n_success`
- `n_failed`

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
## Quick Diagnosis Patterns
- `simulation_plan.json not found`: planning step did not run in this `working_dir`.
- `Missing 'particle_specs'`: baseline/plan input was malformed.
- `Missing 'dimension'`: setup result was not carried into planning correctly.
- Failures during `compress` or `sample`: likely invalid shape parameters or unstable state point; adjust sweep bounds.

## Suggested Recovery Responses
- Confirm same `working_dir` was used for all three tools.
- Narrow tunable range and rerun execution.
- Fix malformed dot paths in `baseline_parameters` or `tunable_parameters` and re-plan.
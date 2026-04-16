import importlib.util
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_module(module_name: str, module_path: Path):
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec is not None
    assert spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


experiment_types = _load_module("test_eval_experiment_types", PROJECT_ROOT / "eval" / "experiment_types.py")


def test_load_experiment_spec_uses_expected_defaults_and_paths():
    spec = experiment_types.load_experiment_spec(PROJECT_ROOT / "eval" / "experiment_spec.example.json")

    assert spec.experiment_id == "colpack_eval_scaffold"
    assert spec.routing is False
    assert spec.bootstrap_skill is True
    assert spec.working_dir_root == PROJECT_ROOT / "eval" / "data"
    assert spec.agent_path == PROJECT_ROOT / "agent" / "agents" / "colpack_agent.md"
    assert spec.skills[0].skill_path == PROJECT_ROOT / "eval" / "skills" / "colpack" / "SKILL.md"
    assert len(spec.tasks) == 1
    assert spec.tasks[0].task_id == "setup_only"
    assert len(spec.tasks[0].user_messages) == 1
    assert spec.tasks[0].user_profile_id == "novice_workflow_user"


def test_expand_planned_runs_builds_task_model_skill_matrix():
    spec = experiment_types.load_experiment_spec(PROJECT_ROOT / "eval" / "experiment_spec.example.json")
    planned_runs = experiment_types.expand_planned_runs(spec)

    assert len(planned_runs) == len(spec.tasks) * len(spec.models) * len(spec.skills) * spec.repeats
    assert planned_runs[0].run_id.startswith("colpack_eval_scaffold__")
    assert planned_runs[0].user_profile is not None

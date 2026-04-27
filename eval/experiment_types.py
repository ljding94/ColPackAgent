from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from agent.wrapper_config import default_agent_path, default_mcp_command


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _default_eval_skill_path() -> Path:
    return _repo_root() / "eval" / "skills" / "full" / "colpack" / "SKILL.md"


def _fixture_index_path() -> Path:
    return _repo_root() / "eval" / "data" / "fixtures" / "_index.json"


_FIXTURE_PLACEHOLDER_RE = re.compile(r"\{\{fixture:([A-Za-z0-9_]+)\}\}")


def _load_fixture_index() -> dict[str, str]:
    """Load fixture_id -> absolute working_dir from eval/data/fixtures/_index.json.

    Returns an empty dict if the index file is missing. Callers that
    require a non-empty index should validate downstream.
    """
    index_path = _fixture_index_path()
    if not index_path.exists():
        return {}
    try:
        data = json.loads(index_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"Could not parse fixture index at {index_path}: {exc}") from exc
    if not isinstance(data, dict):
        raise ValueError(f"Fixture index at {index_path} must be a JSON object.")
    return {fid: entry["working_dir"] for fid, entry in data.items() if isinstance(entry, dict) and "working_dir" in entry}


def _resolve_fixture_placeholders(text: str, fixture_map: dict[str, str], *, task_id: str) -> str:
    def replace(match: re.Match[str]) -> str:
        fixture_id = match.group(1)
        if fixture_id not in fixture_map:
            raise ValueError(
                f"Task '{task_id}' references {{{{fixture:{fixture_id}}}}}, "
                f"but no such fixture is in the index. "
                f"Build it with: python eval/bootstrap_fixtures.py --only {fixture_id}"
            )
        return fixture_map[fixture_id]

    return _FIXTURE_PLACEHOLDER_RE.sub(replace, text)


def _resolve_path(path_text: str | None, *, default_path: Path | None = None) -> Path | None:
    if path_text is None:
        return default_path
    path = Path(path_text).expanduser()
    if not path.is_absolute():
        path = (_repo_root() / path).resolve()
    else:
        path = path.resolve()
    return path


@dataclass(frozen=True)
class UserProfileSpec:
    profile_id: str
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TaskSpec:
    task_id: str
    description: str
    difficulty_level: int
    user_messages: tuple[str, ...]
    user_profile_id: str | None = None
    expected_outcomes: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ModelSpec:
    model_id: str
    label: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SkillVariantSpec:
    skill_id: str
    skill_path: Path
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ExperimentSpec:
    experiment_id: str
    description: str
    output_dir: Path
    working_dir_root: Path
    agent_path: Path
    mcp_command: str
    bootstrap_skill: bool
    repeats: int
    user_profiles: tuple[UserProfileSpec, ...]
    tasks: tuple[TaskSpec, ...]
    models: tuple[ModelSpec, ...]
    skills: tuple[SkillVariantSpec, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PlannedRun:
    run_id: str
    repeat_index: int
    task: TaskSpec
    model: ModelSpec
    skill: SkillVariantSpec
    user_profile: UserProfileSpec | None


@dataclass(frozen=True)
class TokenUsageRecord:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_creation_input_tokens: int | None = None
    cache_read_input_tokens: int | None = None


@dataclass(frozen=True)
class TurnResult:
    turn_index: int
    user_input: str
    routed_user_input: str
    route_kind: str | None
    assistant_text: str
    system_errors: tuple[str, ...]
    query_had_error: bool
    response_duration_ms: float
    total_cost_usd: float
    usage: TokenUsageRecord
    session_id: str = ""
    sdk_turn_count: int = 0


@dataclass(frozen=True)
class RunResult:
    run_id: str
    experiment_id: str
    task_id: str
    model_id: str
    skill_id: str
    repeat_index: int
    user_profile_id: str | None
    success: bool
    started_at: str
    completed_at: str
    wall_time_seconds: float
    total_cost_usd: float
    usage: TokenUsageRecord
    turn_results: tuple[TurnResult, ...]
    metadata: dict[str, Any] = field(default_factory=dict)


def _load_user_profiles(raw_profiles: list[dict[str, Any]] | None) -> tuple[UserProfileSpec, ...]:
    if not raw_profiles:
        return ()
    return tuple(
        UserProfileSpec(
            profile_id=str(profile["profile_id"]),
            description=str(profile.get("description", "")),
            metadata=dict(profile.get("metadata", {})),
        )
        for profile in raw_profiles
    )


def _load_tasks(raw_tasks: list[dict[str, Any]]) -> tuple[TaskSpec, ...]:
    tasks = []
    fixture_map: dict[str, str] | None = None  # Lazy-loaded on first placeholder use.

    for raw_task in raw_tasks:
        task_id = str(raw_task["task_id"])
        raw_messages = [str(message) for message in raw_task.get("user_messages", [])]
        if not raw_messages:
            raise ValueError(f"Task {task_id} must define at least one user message.")

        if any(_FIXTURE_PLACEHOLDER_RE.search(m) for m in raw_messages):
            if fixture_map is None:
                fixture_map = _load_fixture_index()
                if not fixture_map:
                    raise ValueError(
                        f"Task '{task_id}' uses a {{fixture:...}} placeholder but no "
                        f"fixture index was found at {_fixture_index_path()}. "
                        "Run: python eval/bootstrap_fixtures.py"
                    )
            raw_messages = [_resolve_fixture_placeholders(m, fixture_map, task_id=task_id) for m in raw_messages]

        tasks.append(
            TaskSpec(
                task_id=task_id,
                description=str(raw_task.get("description", "")),
                difficulty_level=int(raw_task.get("difficulty_level", 1)),
                user_messages=tuple(raw_messages),
                user_profile_id=raw_task.get("user_profile_id"),
                expected_outcomes=tuple(str(item) for item in raw_task.get("expected_outcomes", [])),
                metadata=dict(raw_task.get("metadata", {})),
            )
        )
    return tuple(tasks)


def _load_models(raw_models: list[dict[str, Any]] | None) -> tuple[ModelSpec, ...]:
    raw_models = raw_models or [{"model_id": "openrouter/google/gemini-3-flash-preview"}]
    return tuple(
        ModelSpec(
            model_id=str(model["model_id"]),
            label=model.get("label"),
            metadata=dict(model.get("metadata", {})),
        )
        for model in raw_models
    )


def _load_skills(raw_skills: list[dict[str, Any]] | None) -> tuple[SkillVariantSpec, ...]:
    raw_skills = raw_skills or [
        {
            "skill_id": "default",
            "skill_path": str(_default_eval_skill_path()),
            "description": "Default eval-local ColPack skill",
        }
    ]
    skills: list[SkillVariantSpec] = []
    for raw_skill in raw_skills:
        resolved_path = _resolve_path(raw_skill.get("skill_path"))
        if resolved_path is None:
            raise ValueError(f"Skill entry {raw_skill.get('skill_id', '<unknown>')} is missing skill_path.")
        skills.append(
            SkillVariantSpec(
                skill_id=str(raw_skill["skill_id"]),
                skill_path=resolved_path,
                description=str(raw_skill.get("description", "")),
                metadata=dict(raw_skill.get("metadata", {})),
            )
        )
    return tuple(skills)


def load_experiment_spec(spec_path: Path) -> ExperimentSpec:
    resolved_path = spec_path.expanduser().resolve()
    raw_spec = json.loads(resolved_path.read_text(encoding="utf-8"))

    experiment_id = str(raw_spec.get("experiment_id", resolved_path.stem))
    output_dir = _resolve_path(raw_spec.get("output_dir"), default_path=_repo_root() / "eval" / "runs" / experiment_id)
    working_dir_root = _resolve_path(raw_spec.get("working_dir_root"), default_path=_repo_root() / "eval" / "data")
    agent_path = _resolve_path(
        raw_spec.get("agent_path"),
        default_path=default_agent_path(_repo_root() / "agent"),
    )
    if output_dir is None or working_dir_root is None or agent_path is None:
        raise ValueError("Experiment spec could not resolve output_dir, working_dir_root, or agent_path.")

    raw_tasks_inline = raw_spec.get("tasks")
    raw_tasks_file = raw_spec.get("tasks_file")
    if raw_tasks_inline and raw_tasks_file:
        raise ValueError("Experiment spec cannot define both 'tasks' and 'tasks_file'.")
    if raw_tasks_file:
        tasks_path = _resolve_path(raw_tasks_file)
        if tasks_path is None or not tasks_path.exists():
            raise ValueError(f"tasks_file not found: {raw_tasks_file}")
        raw_tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
        if not isinstance(raw_tasks, list):
            raise ValueError(f"tasks_file {tasks_path} must contain a JSON array of task entries.")
    else:
        raw_tasks = raw_tasks_inline or []

    spec = ExperimentSpec(
        experiment_id=experiment_id,
        description=str(raw_spec.get("description", "")),
        output_dir=output_dir,
        working_dir_root=working_dir_root,
        agent_path=agent_path,
        mcp_command=str(raw_spec.get("mcp_command", default_mcp_command(_repo_root() / "agent"))),
        bootstrap_skill=bool(raw_spec.get("bootstrap_skill", True)),
        repeats=max(1, int(raw_spec.get("repeats", 1))),
        user_profiles=_load_user_profiles(raw_spec.get("user_profiles")),
        tasks=_load_tasks(raw_tasks),
        models=_load_models(raw_spec.get("models")),
        skills=_load_skills(raw_spec.get("skills")),
        metadata=dict(raw_spec.get("metadata", {})),
    )
    if not spec.tasks:
        raise ValueError("Experiment spec must define at least one task.")
    return spec


def expand_planned_runs(spec: ExperimentSpec) -> tuple[PlannedRun, ...]:
    user_profile_map = {profile.profile_id: profile for profile in spec.user_profiles}
    planned_runs: list[PlannedRun] = []

    for repeat_index in range(spec.repeats):
        for task in spec.tasks:
            for model in spec.models:
                for skill in spec.skills:
                    user_profile = user_profile_map.get(task.user_profile_id) if task.user_profile_id else None
                    run_id = f"{spec.experiment_id}__{task.task_id}__{skill.skill_id}__{model.model_id.replace('/', '_')}__r{repeat_index + 1:02d}"
                    planned_runs.append(
                        PlannedRun(
                            run_id=run_id,
                            repeat_index=repeat_index + 1,
                            task=task,
                            model=model,
                            skill=skill,
                            user_profile=user_profile,
                        )
                    )

    return tuple(planned_runs)


def dataclass_to_json(data: Any) -> dict[str, Any]:
    payload = asdict(data)
    return _convert_paths(payload)


def _convert_paths(value: Any) -> Any:
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {key: _convert_paths(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_convert_paths(item) for item in value]
    if isinstance(value, tuple):
        return [_convert_paths(item) for item in value]
    return value

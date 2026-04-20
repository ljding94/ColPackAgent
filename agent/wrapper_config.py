import json
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class StandaloneAgentDefinition:
    name: str
    description: str
    prompt: str
    skill_path: Path | None
    source_path: Path


def _base_dir(explicit_base_dir: Path | None = None) -> Path:
    if explicit_base_dir is not None:
        return explicit_base_dir.expanduser().resolve()
    return Path(__file__).resolve().parent


def load_opencode_config(base_dir: Path | None = None) -> dict:
    config_path = _base_dir(base_dir) / "opencode.json"
    if not config_path.exists():
        return {}
    try:
        return json.loads(config_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def default_mcp_command(base_dir: Path | None = None) -> str:
    colpack_mcp = load_opencode_config(base_dir).get("mcp", {}).get("colpack", {})
    cmd = colpack_mcp.get("command")
    if isinstance(cmd, list) and cmd:
        return " ".join(cmd)
    if isinstance(cmd, str) and cmd:
        return cmd
    return "colpack-mcp"


def default_agent_path(base_dir: Path | None = None) -> Path:
    resolved_base_dir = _base_dir(base_dir)
    agent_name = load_opencode_config(resolved_base_dir).get("default_agent")
    if agent_name:
        agents_dir = resolved_base_dir / "agents"
        configured_path = agents_dir / f"{agent_name}.md"
        if configured_path.exists():
            return configured_path

        snake_case_name = re.sub(r"(?<!^)(?=[A-Z])", "_", str(agent_name)).lower()
        for candidate_name in (str(agent_name).lower(), snake_case_name):
            candidate_path = agents_dir / f"{candidate_name}.md"
            if candidate_path.exists():
                return candidate_path
    return resolved_base_dir / "agents" / "colpack_agent.md"


def default_skill_path(base_dir: Path | None = None) -> Path:
    resolved_base_dir = _base_dir(base_dir)
    instructions = load_opencode_config(resolved_base_dir).get("instructions", [])
    if instructions:
        return (resolved_base_dir / instructions[0]).resolve()
    return resolved_base_dir / "skills" / "colpack" / "SKILL.md"


def default_skill_bootstrap_enabled(base_dir: Path | None = None) -> bool:
    wrapper_config = load_opencode_config(base_dir).get("wrapper", {})
    return bool(wrapper_config.get("bootstrap_skill", True))


def parse_frontmatter(markdown_text: str) -> tuple[dict[str, str], str]:
    if not markdown_text.startswith("---\n"):
        return {}, markdown_text.strip()

    lines = markdown_text.splitlines()
    if not lines or lines[0].strip() != "---":
        return {}, markdown_text.strip()

    frontmatter: dict[str, str] = {}
    end_index = None
    for index in range(1, len(lines)):
        line = lines[index]
        if line.strip() == "---":
            end_index = index
            break
        if ":" not in line:
            continue
        key, value = line.split(":", 1)
        frontmatter[key.strip()] = value.strip().strip('"').strip("'")

    if end_index is None:
        return {}, markdown_text.strip()

    body = "\n".join(lines[end_index + 1 :]).strip()
    return frontmatter, body


def load_agent_definition(
    agent_path: Path,
    skill_path_override: Path | None = None,
    base_dir: Path | None = None,
) -> StandaloneAgentDefinition:
    resolved = agent_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Agent file not found: {resolved}")

    frontmatter, body = parse_frontmatter(resolved.read_text(encoding="utf-8"))
    skill_path = skill_path_override
    if skill_path is None:
        skill_path_text = frontmatter.get("skill_path")
        if skill_path_text:
            skill_path = (resolved.parent / skill_path_text).resolve()
        else:
            skill_path = default_skill_path(base_dir)

    return StandaloneAgentDefinition(
        name=frontmatter.get("name", resolved.stem),
        description=frontmatter.get("description", ""),
        prompt=body,
        skill_path=skill_path,
        source_path=resolved,
    )


def load_prompt_text(prompt_path: Path) -> str:
    resolved = prompt_path.expanduser().resolve()
    if not resolved.exists():
        raise FileNotFoundError(f"Prompt file not found: {resolved}")
    return resolved.read_text(encoding="utf-8").strip()


def build_system_prompt(
    agent_path: Path,
    skill_path: Path | None = None,
    base_dir: Path | None = None,
) -> str:
    agent_definition = load_agent_definition(
        agent_path,
        skill_path_override=skill_path,
        base_dir=base_dir,
    )
    sections: list[str] = []
    if agent_definition.prompt:
        sections.append(agent_definition.prompt)
    if agent_definition.skill_path is not None:
        sections.append(load_prompt_text(agent_definition.skill_path))
    return "\n\n".join(section for section in sections if section.strip())

from dataclasses import dataclass
import re


STRONG_WORKFLOW_KEYWORDS = (
    "colpack",
    "colloid",
    "packing",
)
WORKFLOW_DOMAIN_KEYWORDS = (
    "workflow",
    "simulation",
    "ensemble",
    "particle",
)
WORKFLOW_ACTION_KEYWORDS = (
    "setup",
    "plan",
    "execute",
    "run",
    "compress",
    "sample",
    "analyze",
    "simulate",
)
SHORT_FOLLOWUP_REPLIES = {"yes", "y", "no", "n", "ok", "okay", "continue", "proceed", "status", "check again"}
SHAPE_KEYWORD_ALIASES = {
    "disk": "disk",
    "disks": "disk",
    "ellipse": "ellipse",
    "ellipses": "ellipse",
    "ellipsoid": "ellipsoid",
    "ellipsoids": "ellipsoid",
    "triangle": "triangle",
    "triangles": "triangle",
    "square": "square",
    "squares": "square",
    "rectangle": "rectangle",
    "rectangles": "rectangle",
    "rectangular": "rectangle",
    "rentangle": "rectangle",
    "rentangles": "rectangle",
    "capsule": "capsule",
    "capsules": "capsule",
    "sphere": "sphere",
    "spheres": "sphere",
    "cube": "cube",
    "cubes": "cube",
    "tetrahedron": "tetrahedron",
    "tetrahedra": "tetrahedron",
    "octahedron": "octahedron",
    "octahedra": "octahedron",
}


@dataclass(frozen=True)
class WorkflowRoutingContext:
    dimension: int | None = None
    ensemble: str | None = None
    particle_shape_list: tuple[str, ...] = ()
    wants_default_working_dir: bool = False


@dataclass(frozen=True)
class WorkflowMessageSignals:
    dimension: int | None = None
    ensemble: str | None = None
    particle_shape_list: tuple[str, ...] = ()
    mentions_strong_keyword: bool = False
    mentions_domain_keyword: bool = False
    mentions_action_keyword: bool = False
    mentions_numeric_parameter: bool = False
    wants_default_working_dir: bool = False
    has_explicit_working_dir: bool = False


def _contains_any_keyword(text: str, keywords: tuple[str, ...]) -> bool:
    return any(re.search(rf"\b{re.escape(keyword)}\b", text) for keyword in keywords)


def _extract_shape_names_from_text(text: str) -> tuple[str, ...]:
    pattern = r"\b(?:" + "|".join(sorted(map(re.escape, SHAPE_KEYWORD_ALIASES), key=len, reverse=True)) + r")\b"
    discovered: list[tuple[int, str]] = []
    for match in re.finditer(pattern, text.lower()):
        discovered.append((match.start(), SHAPE_KEYWORD_ALIASES[match.group(0)]))

    ordered_shapes: list[str] = []
    for _, shape in sorted(discovered, key=lambda item: item[0]):
        if shape not in ordered_shapes:
            ordered_shapes.append(shape)
    return tuple(ordered_shapes)


def _merge_shape_names(existing: tuple[str, ...], discovered: tuple[str, ...]) -> tuple[str, ...]:
    if not discovered:
        return existing

    merged = list(existing)
    for shape in discovered:
        if shape not in merged:
            merged.append(shape)
    return tuple(merged)


def _looks_like_default_working_dir_request(text: str) -> bool:
    lowered = text.lower()
    return any(
        phrase in lowered
        for phrase in (
            "default working directory",
            "default working dir",
            "use the default working directory",
            "use the default working dir",
            "use default working directory",
            "use default working dir",
        )
    )


def _contains_explicit_working_dir(text: str) -> bool:
    return re.search(r"(?:\bdata/[\w./-]+|(?:^|\s)(?:~|/)[\w./-]+)", text) is not None


def _extract_workflow_message_signals(text: str) -> WorkflowMessageSignals:
    lowered = text.strip().lower()
    dimension_match = re.search(r"\b([23])d\b", lowered)
    ensemble_match = re.search(r"\b(nvt|npt)\b", lowered)
    particle_shape_list = _extract_shape_names_from_text(lowered)

    return WorkflowMessageSignals(
        dimension=int(dimension_match.group(1)) if dimension_match else None,
        ensemble=ensemble_match.group(1).upper() if ensemble_match else None,
        particle_shape_list=particle_shape_list,
        mentions_strong_keyword=_contains_any_keyword(lowered, STRONG_WORKFLOW_KEYWORDS),
        mentions_domain_keyword=_contains_any_keyword(lowered, WORKFLOW_DOMAIN_KEYWORDS),
        mentions_action_keyword=_contains_any_keyword(lowered, WORKFLOW_ACTION_KEYWORDS),
        mentions_numeric_parameter=bool(re.search(r"\b\d{1,7}\b", lowered)),
        wants_default_working_dir=_looks_like_default_working_dir_request(lowered),
        has_explicit_working_dir=_contains_explicit_working_dir(lowered),
    )


def _count_explicit_workflow_hints(signals: WorkflowMessageSignals) -> int:
    return sum(
        (
            signals.dimension is not None,
            signals.ensemble is not None,
            bool(signals.particle_shape_list),
            signals.wants_default_working_dir,
            signals.has_explicit_working_dir,
        )
    )


def _update_workflow_routing_context(context: WorkflowRoutingContext, user_input: str) -> WorkflowRoutingContext:
    signals = _extract_workflow_message_signals(user_input)
    dimension = signals.dimension or context.dimension
    ensemble = signals.ensemble or context.ensemble
    particle_shape_list = _merge_shape_names(context.particle_shape_list, signals.particle_shape_list)

    wants_default_working_dir = context.wants_default_working_dir
    if signals.wants_default_working_dir:
        wants_default_working_dir = True
    elif signals.has_explicit_working_dir:
        wants_default_working_dir = False

    return WorkflowRoutingContext(
        dimension=dimension,
        ensemble=ensemble,
        particle_shape_list=particle_shape_list,
        wants_default_working_dir=wants_default_working_dir,
    )


def _build_workflow_context_note(context: WorkflowRoutingContext) -> str:
    lines: list[str] = []
    if context.dimension is not None:
        lines.append(f"Wrapper-detected dimension: {context.dimension}")
    if context.ensemble is not None:
        lines.append(f"Wrapper-detected ensemble: {context.ensemble}")
    if context.particle_shape_list:
        lines.append(f"Wrapper-detected particle_shape_list: {list(context.particle_shape_list)}")
    if context.wants_default_working_dir:
        lines.append("Wrapper-detected request to use the default working_dir.")
        lines.append(
            "Let setup_simulation_problem_tool resolve the canonical working_dir; do not ask the user to invent a custom path unless they override it."
        )
    return "\n".join(lines)


def _looks_like_colpack_workflow_request(user_input: str) -> bool:
    signals = _extract_workflow_message_signals(user_input)
    explicit_hint_count = _count_explicit_workflow_hints(signals)

    if signals.mentions_strong_keyword:
        return True
    if explicit_hint_count >= 2:
        return True
    if explicit_hint_count >= 1 and (signals.mentions_action_keyword or signals.mentions_domain_keyword):
        return True
    return False


def _build_routed_user_input(user_input: str, mode: str, routing_context: WorkflowRoutingContext | None = None) -> str:
    if not _looks_like_colpack_workflow_request(user_input):
        return user_input

    mode_instruction = (
        "Interactive handling only: stay on the current workflow stage and wait for approval before each MCP call."
        if mode == "interactive"
        else "Autonomous handling: complete the ColPack workflow end-to-end when the request is specific enough."
    )

    context_note = _build_workflow_context_note(routing_context or WorkflowRoutingContext())
    lines = [
        "COLPACK WORKFLOW REQUEST",
        "Route this request through the ColPack MCP workflow.",
        "Use the workflow sequence Setup -> Plan -> Execute & Analyze.",
    ]
    if context_note:
        lines.append(context_note)
    lines.extend(
        [
            "Use workflow MCP tools directly unless the user is explicitly asking a codebase question or diagnosing an existing failure.",
            mode_instruction,
            f"Original user request: {user_input}",
        ]
    )
    return "\n".join(lines)


def _looks_like_colpack_followup_reply(user_input: str) -> bool:
    lowered = user_input.strip().lower()
    if not lowered:
        return False

    if lowered in SHORT_FOLLOWUP_REPLIES:
        return True

    if len(lowered) > 240:
        return False

    signals = _extract_workflow_message_signals(lowered)
    return any(
        (
            _count_explicit_workflow_hints(signals) >= 1,
            signals.mentions_numeric_parameter,
        )
    )


def _build_followup_user_input(user_input: str, mode: str, routing_context: WorkflowRoutingContext | None = None) -> str:
    mode_instruction = (
        "Interactive handling only: treat this as a follow-up answer in the active ColPack workflow and merge it into the current stage context."
        if mode == "interactive"
        else "Autonomous handling: treat this as a follow-up update to the active ColPack workflow context."
    )

    context_note = _build_workflow_context_note(routing_context or WorkflowRoutingContext())
    lines = [
        "COLPACK WORKFLOW FOLLOW-UP",
        "This message continues an active ColPack workflow conversation.",
        "Merge newly provided inputs with the existing workflow context instead of restarting the workflow.",
        "Keep the current workflow stage and working_dir unless the user explicitly changes them.",
    ]
    if context_note:
        lines.append(context_note)
    lines.extend(
        [
            mode_instruction,
            f"Original user reply: {user_input}",
        ]
    )
    return "\n".join(lines)


def _route_user_message(
    user_input: str,
    current_mode: str,
    workflow_session_active: bool,
    routing_context: WorkflowRoutingContext,
) -> tuple[str, bool, WorkflowRoutingContext, str | None]:
    routed_user_input = user_input

    if workflow_session_active and _looks_like_colpack_followup_reply(user_input):
        routing_context = _update_workflow_routing_context(routing_context, user_input)
        routed_user_input = _build_followup_user_input(user_input, current_mode, routing_context=routing_context)
        return routed_user_input, True, routing_context, "follow-up"

    if _looks_like_colpack_workflow_request(user_input):
        if not workflow_session_active:
            routing_context = WorkflowRoutingContext()
        routing_context = _update_workflow_routing_context(routing_context, user_input)
        routed_user_input = _build_routed_user_input(user_input, current_mode, routing_context=routing_context)
        return routed_user_input, True, routing_context, "request"

    if workflow_session_active:
        return routed_user_input, False, WorkflowRoutingContext(), None

    return routed_user_input, workflow_session_active, routing_context, None

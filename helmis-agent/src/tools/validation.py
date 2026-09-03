"""
validation.py — Argument validation against declared Gemini tool schemas.

The tool schema in schema.py is the single source of truth for what the model
may pass to a tool. Handlers tolerate extra alias keys, but model-issued
calls are checked here so invalid arguments fail fast at the dispatch
boundary instead of silently producing empty-string/None handling.
"""

from __future__ import annotations

from typing import Any

from .schema import GEMINI_TOOLS

# Gemini type keywords mapped to Python type checks.
_TYPE_CHECKS: dict[str, tuple[type, ...]] = {
    "STRING": (str,),
    "NUMBER": (int, float),
    "INTEGER": (int,),
    "BOOLEAN": (bool,),
    "OBJECT": (dict,),
    "ARRAY": (list,),
}

# Properties that exist in handler seams but are intentionally not model-facing
# (internal scheduler descriptors).
_NON_MODEL_ARGS: dict[str, set[str]] = {
    # 'job' descriptors are validated by the proactive executor, not by schema.
    "add_task": {"job"},
    "update_task": {"new_job"},
}


def _declared_properties(func_name: str) -> dict[str, Any] | None:
    """Return the declared properties dict for a tool, or None if undeclared."""
    for declaration in GEMINI_TOOLS[0]["function_declarations"]:
        if declaration.get("name") == func_name:
            parameters = declaration.get("parameters") or {}
            properties = parameters.get("properties")
            if isinstance(properties, dict):
                return properties
            return {}
    return None


def _check_type(value: Any, type_name: str) -> bool:
    expected = _TYPE_CHECKS.get(type_name)
    if expected is None:
        return True
    # bool is a subclass of int; reject bool where INTEGER is meant and vice versa.
    if type_name == "INTEGER" and isinstance(value, bool):
        return False
    if type_name == "BOOLEAN" and not isinstance(value, bool):
        return False
    return isinstance(value, expected)


def validate_tool_args(func_name: str, args: dict[str, Any]) -> dict[str, Any] | None:
    """Validate model-issued tool arguments against the declared schema.

    Returns an error result dict when the arguments violate the declared
    contract, or ``None`` when the call may proceed. Tools without a declared
    schema (internal/MCP-only) pass through unvalidated.
    """
    properties = _declared_properties(func_name)
    if properties is None:
        return None

    if not isinstance(args, dict):
        return {
            "status": "error",
            "outcome": "invalid_arguments",
            "error": f"Tool '{func_name}' menerima argumen bukan objek.",
        }

    allowed = set(properties) | _NON_MODEL_ARGS.get(func_name, set())
    unknown = sorted(set(args) - allowed)
    if unknown:
        return {
            "status": "error",
            "outcome": "invalid_arguments",
            "error": f"Tool '{func_name}' tidak menerima argumen: {', '.join(unknown)}.",
        }

    required = []
    for declaration in GEMINI_TOOLS[0]["function_declarations"]:
        if declaration.get("name") == func_name:
            required = declaration.get("parameters", {}).get("required", []) or []
            break
    missing = [key for key in required if key not in args or args[key] is None]
    if missing:
        return {
            "status": "error",
            "outcome": "invalid_arguments",
            "error": f"Tool '{func_name}' butuh argumen wajib: {', '.join(missing)}.",
        }

    for key, value in args.items():
        spec = properties.get(key)
        if not isinstance(spec, dict):
            continue
        type_name = str(spec.get("type", "")).upper()
        if type_name and not _check_type(value, type_name):
            return {
                "status": "error",
                "outcome": "invalid_arguments",
                "error": f"Argumen '{key}' pada '{func_name}' harus bertipe {type_name.lower()}.",
            }
        if type_name == "ARRAY":
            items = spec.get("items") or {}
            item_type = str(items.get("type", "")).upper()
            if item_type:
                for element in value:
                    if not _check_type(element, item_type):
                        return {
                            "status": "error",
                            "outcome": "invalid_arguments",
                            "error": f"Argumen '{key}' pada '{func_name}' harus array of {item_type.lower()}.",
                        }

    return None

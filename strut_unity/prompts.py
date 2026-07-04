from __future__ import annotations

from dataclasses import asdict
import json
from pathlib import Path
import re

from .analyzer import FunctionContext
from .cases import TestCase, default_ptr_entries, to_original_seed_case
from .stubs import should_stub_function


ROOT = Path(__file__).resolve().parents[1]

TEST_CASE_GENERATION_PROMPT = ROOT / "Test Cases Generation Prompts.md"
TEST_SUITE_OPTIMIZATION_PROMPT = ROOT / "Test Suite Optimization Prompts Used By STRUT.md"


def build_case_generation_messages(
    context: FunctionContext,
    source_code: str,
    seed_cases: list[TestCase],
) -> list[dict]:
    return [
        {"role": "system", "content": _structured_system_prompt()},
        {
            "role": "user",
            "content": _render_template(
                _read_prompt(TEST_CASE_GENERATION_PROMPT),
                context=context,
                source_code=source_code,
                seed_cases=seed_cases,
            ),
        },
    ]


def build_optimization_messages(
    context: FunctionContext,
    source_code: str,
    current_cases: list[TestCase],
    uncovered_conditions: list[str],
) -> list[dict]:
    template = _read_prompt(TEST_SUITE_OPTIMIZATION_PROMPT)
    template = re.sub(r"\n1\..*", "", template, flags=re.DOTALL).rstrip()
    uncovered = "\n".join(f"{index}. {condition}" for index, condition in enumerate(uncovered_conditions, start=1))
    content = "\n\n".join(
        [
            template,
            uncovered or "All extracted branch outcomes are covered.",
            _render_template(
                "Current structured test suite:\n{{ seed case }}\n\n{{ context }}\n\n{{ focal method }}",
                context=context,
                source_code=source_code,
                seed_cases=current_cases,
            ),
        ]
    )
    return [
        {"role": "system", "content": _structured_system_prompt()},
        {"role": "user", "content": content},
    ]


def cases_to_structured_json(context: FunctionContext, cases: list[TestCase], source_code: str = "") -> dict:
    call_counts = _callee_call_counts(context, source_code)
    return {
        "cases": [_to_prompt_seed_case(context, case, call_counts) for case in cases],
    }


def cases_to_strut_json(context: FunctionContext, cases: list[TestCase], backend: bool = False) -> dict:
    return {
        "func": context.name,
        "file": context.source,
        "cases": [to_original_seed_case(context, case, backend=backend) for case in cases],
        "userVar": [],
        "defaultPTR": default_ptr_entries(context),
        "ios": [],
    }


def _render_template(
    template: str,
    context: FunctionContext,
    source_code: str,
    seed_cases: list[TestCase],
) -> str:
    dependency_details = asdict(context.dependency_details)
    dependency_details["callee_declarations"] = [
        item
        for item in dependency_details["callee_declarations"]
        if should_stub_function(str(item.get("name", "")))
    ]
    dependency_details["callee_interfaces"] = [
        item
        for item in dependency_details["callee_interfaces"]
        if should_stub_function(str(item.get("name", "")))
    ]
    context_payload = {
        "function": context.name,
        "dependencies": [name for name in context.dependencies if should_stub_function(name)],
        "dependency_details": dependency_details,
        "global_refs": context.global_refs,
        "interface_data": {
            "return_type": context.return_type,
            "parameters": [asdict(parameter) for parameter in context.parameters],
        },
        "branch_conditions": context.branch_conditions,
        "syntax": {
            "tree_sitter_has_error": context.tree_sitter_has_error,
            "tree_sitter_function_count": context.tree_sitter_function_count,
        },
    }
    replacements = {
        "{{ context }}": "Function Context Database:\n" + json.dumps(context_payload, indent=2),
        "{{ focal method }}": "Function Source Code:\n```c\n" + source_code + "\n```",
        "{{ seed case }}": (
            "Structured Seed Cases:\n"
            + json.dumps(cases_to_structured_json(context, seed_cases, source_code), indent=2)
        ),
    }
    rendered = template
    for placeholder, value in replacements.items():
        rendered = rendered.replace(placeholder, value)
    return rendered


def _structured_system_prompt() -> str:
    return (
        "You are STRUT's structured test-suite generator for C unit testing. "
        "Return only strict JSON matching the provided JSON structure. "
        "Generate compact branch-covering cases. Use parameter names exactly as shown. "
        "Do not include markdown, comments, prose, or complete test code. "
        "Expected outputs may be omitted or provisional because the runner computes them with an oracle."
    )


def _to_prompt_seed_case(context: FunctionContext, case: TestCase, call_counts: dict[str, int]) -> dict:
    original = to_original_seed_case(context, case, backend=False)
    stubs = original["stubins"] or _default_prompt_stubs(context, call_counts)
    outputs = original["outputs"] or _default_prompt_outputs(context)
    return {
        "inputs": [*original["inputs"], *_global_inputs(context)],
        "stubs": stubs,
        "outputs": outputs,
    }


def _global_inputs(context: FunctionContext) -> list[dict]:
    variables = {item.name: item for item in context.dependency_details.global_variables}
    inputs = []
    for name in context.global_refs:
        item = variables.get(name)
        c_type = item.c_type if item and item.c_type else "int"
        source = item.source if item else None
        inputs.append({"expr": name, "type": c_type, "value": _global_initial_value(source, c_type)})
    return inputs


def _default_prompt_stubs(context: FunctionContext, call_counts: dict[str, int]) -> list[dict]:
    stubs = []
    for interface in context.dependency_details.callee_interfaces:
        if not should_stub_function(interface.name):
            continue
        changes = _stub_changed_variables(interface)
        if not changes:
            continue
        signature = (interface.signature or f"{interface.return_type} {interface.name}()").rstrip(";")
        for _ in range(max(1, call_counts.get(interface.name, 1))):
            stubs.append({"called function": signature, "changed variable": changes})
    return stubs


def _stub_changed_variables(interface) -> list[dict]:
    changes = []
    if _normalize_type(interface.return_type) != "void":
        changes.append(
            {
                "expr": "returnValue",
                "type": interface.return_type,
                "value": _default_value_for_type(interface.return_type),
            }
        )
    for parameter in interface.pointer_parameters:
        changes.extend(_pointer_values(parameter, output=False))
    return changes


def _default_prompt_outputs(context: FunctionContext) -> list[dict]:
    outputs = []
    if _normalize_type(context.return_type) != "void":
        outputs.append(
            {
                "expr": "returnValue",
                "type": context.return_type,
                "value": _default_value_for_type(context.return_type),
            }
        )
    for parameter in context.parameters:
        if parameter.type_kind == "pointer":
            outputs.extend(_pointer_values(parameter, output=True))
    return outputs


def _pointer_values(parameter, output: bool) -> list[dict]:
    if parameter.fields:
        return _field_values(parameter.name, parameter.fields)
    pointee_type = parameter.pointee_type or _strip_pointer(parameter.c_type) or "int"
    expr = f"{parameter.name}[0]" if output else f"*{parameter.name}"
    return [{"expr": expr, "type": pointee_type, "value": _default_value_for_type(pointee_type)}]


def _field_values(base: str, fields) -> list[dict]:
    values = []
    for field in fields:
        expr = f"{base}->{field.name}"
        if field.type_kind == "array":
            c_type = field.element_type or field.c_type
            values.append({"expr": f"{expr}[0]", "type": c_type, "value": _default_value_for_type(c_type)})
        elif field.type_kind == "pointer":
            pointee_type = field.pointee_type or _strip_pointer(field.c_type) or "int"
            values.append({"expr": f"{expr}[0]", "type": pointee_type, "value": _default_value_for_type(pointee_type)})
        elif field.fields:
            values.extend(_field_values(expr, field.fields))
        else:
            values.append({"expr": expr, "type": field.c_type, "value": _default_value_for_type(field.c_type)})
    return values


def _callee_call_counts(context: FunctionContext, source_code: str) -> dict[str, int]:
    counts = {}
    for name in context.dependencies:
        count = len(re.findall(rf"\b{re.escape(name)}\s*\(", source_code))
        if count:
            counts[name] = count
    return counts


def _global_initial_value(source: str | None, c_type: str) -> str:
    if source:
        match = re.search(r"=\s*([^;]+)", source)
        if match:
            return match.group(1).strip()
    return _default_value_for_type(c_type)


def _default_value_for_type(c_type: str) -> str:
    normalized = _normalize_type(c_type)
    if "*" in normalized:
        return "NULL"
    if normalized in {"float", "double"}:
        return "0.0"
    return "0"


def _strip_pointer(c_type: str) -> str:
    return c_type.replace("*", "").strip()


def _normalize_type(c_type: str) -> str:
    return " ".join(c_type.replace("const ", "").split())


def _read_prompt(path: Path) -> str:
    return path.read_text(encoding="utf-8")

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from .analyzer import FunctionContext
from .cases import OutputValue, StubIn, TestCase


@dataclass(frozen=True)
class StubSignature:
    name: str
    return_type: str
    parameters: tuple[str, ...]


STANDARD_LIBRARY_DIRECT_CALLS = {
    "__assert_fail",
    "__ctype_b_loc",
    "abort",
    "abs",
    "atof",
    "atoi",
    "atol",
    "calloc",
    "exit",
    "fclose",
    "fgetc",
    "fgets",
    "fopen",
    "fputc",
    "fputs",
    "fprintf",
    "fread",
    "free",
    "fscanf",
    "fwrite",
    "getc",
    "getchar",
    "isalpha",
    "isdigit",
    "islower",
    "isspace",
    "isupper",
    "labs",
    "malloc",
    "memcpy",
    "memmove",
    "memset",
    "perror",
    "printf",
    "putchar",
    "puts",
    "qsort",
    "rand",
    "realloc",
    "remove",
    "scanf",
    "snprintf",
    "sprintf",
    "srand",
    "strcat",
    "strchr",
    "strcmp",
    "strcpy",
    "strlen",
    "strncat",
    "strncmp",
    "strncpy",
    "strrchr",
    "strstr",
    "strtol",
    "strtoul",
    "time",
    "tolower",
    "toupper",
}


def should_stub_function(name: str) -> bool:
    return name not in STANDARD_LIBRARY_DIRECT_CALLS


def stub_function_names(context: FunctionContext, cases: list[TestCase]) -> set[str]:
    names = set()
    for case in cases:
        for stub in case.stubins:
            name = stub_name(context, stub)
            if name:
                names.add(name)
    return names


def stub_name(context: FunctionContext, stub: StubIn) -> str | None:
    raw = stub.called_function
    for dependency in context.dependencies:
        if re.search(rf"\b{re.escape(dependency)}\b", raw):
            return dependency if should_stub_function(dependency) else None
    match = re.search(r"\b([A-Za-z_]\w*)\s*\(", raw)
    if not match:
        return None
    name = match.group(1)
    if name == context.name or not should_stub_function(name):
        return None
    return name


def stub_prelude(context: FunctionContext, cases: list[TestCase]) -> list[str]:
    signatures = _stub_signatures(context, cases)
    if not signatures:
        return []
    lines = [*_stub_type_declarations(context, signatures), "static int __strut_stub_case_index = 0;"]
    for name in signatures:
        lines.append(f"static int {_call_index_name(name)} = 0;")
    lines.append("static void __strut_reset_stub_calls(void);")
    for signature in signatures.values():
        lines.append(_prototype(signature))
    lines.append("")
    return lines


def stub_case_setup(context: FunctionContext, cases: list[TestCase], case_index: int) -> list[str]:
    if not stub_function_names(context, cases):
        return []
    return [
        f"__strut_stub_case_index = {case_index};",
        "__strut_reset_stub_calls();",
    ]


def stub_definitions(context: FunctionContext, cases: list[TestCase]) -> list[str]:
    signatures = _stub_signatures(context, cases)
    if not signatures:
        return []
    lines: list[str] = []
    grouped: dict[str, dict[int, list[StubIn]]] = {name: {} for name in signatures}
    for index, case in enumerate(cases, start=1):
        for stub in case.stubins:
            name = stub_name(context, stub)
            if name in grouped:
                grouped[name].setdefault(index, []).append(stub)

    lines.append("static void __strut_reset_stub_calls(void)")
    lines.append("{")
    for name in signatures:
        lines.append(f"    {_call_index_name(name)} = 0;")
    lines.append("}")
    lines.append("")

    for name, signature in signatures.items():
        lines.append(_definition_header(signature))
        lines.append("{")
        lines.append(f"    int __strut_call_index = {_call_index_name(name)}++;")
        lines.append("    switch (__strut_stub_case_index)")
        lines.append("    {")
        for index, stubs in grouped[name].items():
            lines.append(f"    case {index}:")
            if len(stubs) == 1:
                body = _stub_case_body(signature, stubs[0])
                lines.extend(f"        {line}" for line in body)
            else:
                lines.append("        switch (__strut_call_index)")
                lines.append("        {")
                for call_index, stub in enumerate(stubs):
                    lines.append(f"        case {call_index}:")
                    body = _stub_case_body(signature, stub)
                    lines.extend(f"            {line}" for line in body)
                    lines.append("            break;")
                lines.append("        default:")
                default_return = _default_return(signature.return_type)
                if default_return:
                    lines.append(f"            {default_return}")
                else:
                    lines.append("            break;")
                lines.append("        }")
            lines.append("        break;")
        lines.append("    default:")
        default_return = _default_return(signature.return_type)
        if default_return:
            lines.append(f"        {default_return}")
        else:
            lines.append("        break;")
        lines.append("    }")
        final_return = _default_return(signature.return_type)
        if final_return:
            lines.append(f"    {final_return}")
        lines.append("}")
        lines.append("")
    return lines


def _call_index_name(name: str) -> str:
    safe = re.sub(r"\W+", "_", name).strip("_")
    return f"__strut_stub_call_index_{safe}"


def _stub_signatures(context: FunctionContext, cases: list[TestCase]) -> dict[str, StubSignature]:
    signatures = {}
    declaration_sources = {
        item.name: item.source
        for item in context.dependency_details.callee_declarations
        if item.source
    }
    for case in cases:
        for stub in case.stubins:
            name = stub_name(context, stub)
            if not name or name in signatures:
                continue
            source = declaration_sources.get(name) or stub.called_function
            signatures[name] = _parse_signature(name, source)
    return signatures


def _stub_type_declarations(context: FunctionContext, signatures: dict[str, StubSignature]) -> list[str]:
    needed = set()
    for signature in signatures.values():
        for text in (signature.return_type, *signature.parameters):
            needed.update(_type_identifiers(text))

    typedefs = {item.name: item.source for item in context.dependency_details.typedefs if item.source}
    structs = {item.name: item.source for item in context.dependency_details.structs if item.source}
    declarations: list[str] = []
    seen: set[str] = set()
    for name in sorted(needed):
        source = typedefs.get(name)
        if source:
            declaration = _forward_typedef(source, name)
        elif name in structs:
            declaration = f"struct {name};"
        else:
            declaration = ""
        if declaration and declaration not in seen:
            seen.add(declaration)
            declarations.append(declaration)
    return declarations


def _type_identifiers(text: str) -> set[str]:
    identifiers = set(re.findall(r"\b[A-Za-z_]\w*\b", text))
    return {
        item
        for item in identifiers
        if item
        not in {
            "arg",
            "bool",
            "_Bool",
            "char",
            "const",
            "double",
            "float",
            "int",
            "long",
            "short",
            "signed",
            "struct",
            "unsigned",
            "void",
            "volatile",
        }
        and not re.fullmatch(r"arg\d+", item)
    }


def _forward_typedef(source: str, name: str) -> str:
    text = " ".join(source.split())
    text = text if text.endswith(";") else f"{text};"
    if "{" not in text:
        return text
    match = re.search(r"typedef\s+struct\s+([A-Za-z_]\w*)\s*\{", text)
    if match:
        return f"typedef struct {match.group(1)} {name};"
    match = re.search(r"typedef\s+(union|enum)\s+([A-Za-z_]\w*)\s*\{", text)
    if match:
        return f"typedef {match.group(1)} {match.group(2)} {name};"
    return ""


def _parse_signature(name: str, source: str) -> StubSignature:
    text = " ".join(source.replace(";", " ").split())
    match = re.search(rf"(?P<head>.+?)\b{re.escape(name)}\s*\((?P<params>[^)]*)\)", text)
    if not match:
        return StubSignature(name=name, return_type="int", parameters=())
    return_type = match.group("head").strip()
    params = tuple(_normalize_parameter(param, index) for index, param in enumerate(_split_params(match.group("params"))))
    if len(params) == 1 and params[0] == "void":
        params = ()
    return StubSignature(name=name, return_type=return_type, parameters=params)


def _split_params(params: str) -> list[str]:
    params = params.strip()
    if not params or params == "void":
        return []
    return [param.strip() for param in params.split(",") if param.strip()]


def _normalize_parameter(param: str, index: int) -> str:
    if re.search(r"\b[A-Za-z_]\w*$", param) and len(param.split()) > 1:
        return param
    if param.endswith("*"):
        return f"{param} arg{index + 1}"
    return f"{param} arg{index + 1}"


def _prototype(signature: StubSignature) -> str:
    return _definition_header(signature) + ";"


def _definition_header(signature: StubSignature) -> str:
    params = ", ".join(signature.parameters) if signature.parameters else "void"
    separator = "" if signature.return_type.rstrip().endswith("*") else " "
    return f"{signature.return_type}{separator}{signature.name}({params})"


def _stub_case_body(signature: StubSignature, stub: StubIn) -> list[str]:
    lines = []
    return_value: OutputValue | None = None
    for change in stub.changed_variables:
        if _is_return_expr(change.expr):
            return_value = change
            continue
        assignment = _assignment(change)
        if assignment:
            lines.append(assignment)
    if return_value is not None and _normalize_type(signature.return_type) != "void":
        lines.append(f"return {_literal(return_value.value, signature.return_type)};")
    return lines or ["break;"]


def _assignment(change: OutputValue) -> str | None:
    if not change.expr:
        return None
    value = _literal(change.value, change.c_type)
    if value is None:
        return None
    return f"{change.expr} = {value};"


def _is_return_expr(expr: str) -> bool:
    return re.sub(r"\s+", "", expr).lower() in {"return", "returnvalue", "retval", "__return"}


def _default_return(return_type: str) -> str | None:
    normalized = _normalize_type(return_type)
    if normalized == "void":
        return None
    if "*" in return_type:
        return "return NULL;"
    if normalized in {"float", "double"}:
        return "return 0.0;"
    return "return 0;"


def _literal(value: Any, c_type: str) -> str | None:
    if value is None:
        return "0"
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, dict):
        return None
    text = str(value).strip()
    if not text:
        return "0"
    if text == "NULL" or text.startswith("&") or re.fullmatch(r"[-+]?\d+(?:\.\d+)?", text):
        return text
    normalized = _normalize_type(c_type)
    if normalized in {"char *", "const char *"} or normalized.endswith("[]"):
        return text if text.startswith('"') else f'"{text}"'
    return text


def _normalize_type(c_type: str) -> str:
    return " ".join(c_type.replace("const ", "").split())

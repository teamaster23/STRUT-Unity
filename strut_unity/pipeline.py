from __future__ import annotations

import argparse
from dataclasses import replace
import json
from pathlib import Path
import subprocess

from .analyzer import analyze_function, FunctionContext
from .cases import generate_seed_cases, TestCase
from .coverage import collect_gcov_coverage
from .llm_cases import generate_llm_cases, generate_optimized_llm_cases
from .llm_client import LLMConfig, OpenAICompatibleClient, write_llm_trace
from .prompts import cases_to_strut_json
from .source_rewriter import prepare_test_source
from .stubs import stub_function_names
from .unity_writer import write_unity_test


ROOT = Path(__file__).resolve().parents[1]


def run_pipeline(
    source: str | Path,
    function: str | None = None,
    case_source: str = "hybrid",
    llm_base_url: str | None = None,
    llm_model: str | None = None,
    llm_api_key: str | None = None,
    optimize: bool = True,
) -> dict:
    source_path = Path(source).resolve()
    build_dir = ROOT / "build"
    build_dir.mkdir(exist_ok=True)

    context = analyze_function(source_path, function)
    test_source, callable_name = prepare_test_source(source_path, build_dir, context.name)
    context = replace(context, source=str(test_source), name=callable_name)
    source_lines = source_path.read_text(encoding="utf-8").splitlines()
    source_code = "\n".join(source_lines[context.start_line - 1 : context.end_line])
    context_path = build_dir / f"{context.name}_context.json"
    context_path.write_text(json.dumps(context.to_dict(), indent=2), encoding="utf-8")

    cases, generation_info = _generate_cases(
        context,
        source_code,
        build_dir,
        case_source,
        llm_base_url,
        llm_model,
        llm_api_key,
    )
    stubs = stub_function_names(context, cases)
    if stubs:
        test_source, callable_name = prepare_test_source(source_path, build_dir, context.name, stubs)
        context = replace(context, source=str(test_source), name=callable_name)
        context_path.write_text(json.dumps(context.to_dict(), indent=2), encoding="utf-8")
    pass_only_result = _write_compile_run_collect(
        context,
        cases,
        source_path,
        test_source,
        build_dir,
        context_path,
        "initial_pass_only",
        include_assertions=False,
        artifact_suffix="pass_only",
    )
    result = _write_compile_run_collect(
        context,
        cases,
        source_path,
        test_source,
        build_dir,
        context_path,
        "initial",
        include_assertions=True,
    )

    result = _with_metric_summary({**result, **generation_info}, pass_only_result)
    uncovered = result.get("coverage", {}).get("gcov", {}).get("uncovered_conditions", [])
    if not (optimize and case_source in {"llm", "hybrid"} and uncovered and result.get("run_returncode") == 0):
        return result

    try:
        config = LLMConfig.from_values(base_url=llm_base_url, model=llm_model, api_key=llm_api_key)
        client = OpenAICompatibleClient(config)
        optimized_cases, prompt, response = generate_optimized_llm_cases(
            context,
            source_code,
            cases,
            uncovered,
            client,
        )
        extended_cases = _merge_cases(cases, optimized_cases)
        stubs = stub_function_names(context, extended_cases)
        if stubs:
            test_source, callable_name = prepare_test_source(source_path, build_dir, context.name, stubs)
            context = replace(context, source=str(test_source), name=callable_name)
            context_path.write_text(json.dumps(context.to_dict(), indent=2), encoding="utf-8")
        optimized_pass_only_result = _write_compile_run_collect(
            context,
            extended_cases,
            source_path,
            test_source,
            build_dir,
            context_path,
            "optimized_pass_only",
            include_assertions=False,
            artifact_suffix="optimized_pass_only",
        )
        optimized_result = _write_compile_run_collect(
            context,
            extended_cases,
            source_path,
            test_source,
            build_dir,
            context_path,
            "optimized",
            include_assertions=True,
            artifact_suffix="optimized",
        )
        optimized_trace = write_llm_trace(build_dir, f"{context.name}_optimization", prompt, response)
    except Exception as exc:
        return {
            **result,
            "optimization": {
                "enabled": True,
                "failed": True,
                "error": str(exc),
                "uncovered_conditions": uncovered,
            },
        }
    if optimized_result.get("compile_returncode") != 0 or optimized_result.get("run_returncode") != 0:
        return _with_metric_summary({
            **result,
            "optimization": {
                "enabled": True,
                "failed": True,
                "uncovered_conditions": uncovered,
                "added_cases": len(extended_cases) - len(cases),
                **optimized_trace,
            },
            "optimized_result": optimized_result,
            "optimized_pass_only_result": optimized_pass_only_result,
        }, result.get("pass_only_result", {}))
    return _with_metric_summary({
        **optimized_result,
        **generation_info,
        "optimization": {
            "enabled": True,
            "uncovered_conditions": uncovered,
            "added_cases": len(extended_cases) - len(cases),
            **optimized_trace,
        },
        "initial_result": result,
        "optimized_pass_only_result": optimized_pass_only_result,
    }, optimized_pass_only_result)


def _write_compile_run_collect(
    context: FunctionContext,
    cases: list[TestCase],
    source_path: Path,
    test_source: Path,
    build_dir: Path,
    context_path: Path,
    label: str,
    include_assertions: bool = True,
    artifact_suffix: str | None = None,
) -> dict:
    artifact_name = context.name if artifact_suffix is None else f"{context.name}_{artifact_suffix}"
    case_path = build_dir / f"{artifact_name}_cases.json"
    test_path = build_dir / f"test_{artifact_name}.c"
    exe_path = build_dir / f"test_{artifact_name}"

    case_path.write_text(json.dumps(cases_to_strut_json(context, cases, backend=True), indent=2), encoding="utf-8")
    write_unity_test(context, cases, test_path, include_assertions=include_assertions)

    compile_cmd = [
        "clang",
        "-std=c11",
        "-Wall",
        "-Wextra",
        "-I",
        str(ROOT / "unity"),
        "-I",
        str(source_path.parent),
        "-I",
        str(test_source.parent),
        str(test_path),
        str(ROOT / "unity" / "unity.c"),
        "-DUNITY_INCLUDE_DOUBLE",
        "-o",
        str(exe_path),
    ]
    compile_result = subprocess.run(compile_cmd, text=True, capture_output=True, check=False)
    if compile_result.returncode != 0:
        return {
            "context": str(context_path),
            "cases": str(case_path),
            "test": str(test_path),
            "stage": label,
            "assertions_enabled": include_assertions,
            "status": "compile_error",
            "compile_cmd": compile_cmd,
            "compile_returncode": compile_result.returncode,
            "compile_stdout": compile_result.stdout,
            "compile_stderr": compile_result.stderr,
        }

    run_result = subprocess.run([str(exe_path)], text=True, capture_output=True, check=False)
    gcov_coverage = collect_gcov_coverage(context, test_source, test_path, ROOT / "unity", build_dir, label)
    status = "pass" if run_result.returncode == 0 else "run_error"
    return {
        "context": str(context_path),
        "cases": str(case_path),
        "test": str(test_path),
        "executable": str(exe_path),
        "stage": label,
        "assertions_enabled": include_assertions,
        "status": status,
        "compile_cmd": compile_cmd,
        "compile_returncode": compile_result.returncode,
        "compile_stdout": compile_result.stdout,
        "compile_stderr": compile_result.stderr,
        "run_returncode": run_result.returncode,
        "run_stdout": run_result.stdout,
        "run_stderr": run_result.stderr,
        "coverage": {"gcov": gcov_coverage},
    }


def _with_metric_summary(result: dict, pass_only_result: dict) -> dict:
    complete_status = _result_status(result)
    pass_only_status = _result_status(pass_only_result)
    return {
        **result,
        "complete_status": complete_status,
        "pass_only_status": pass_only_status,
        "pass_only_result": pass_only_result,
        "metric_summary": {
            "pass_only": pass_only_status,
            "complete": complete_status,
        },
    }


def _result_status(result: dict) -> str:
    status = result.get("status")
    if status:
        return str(status)
    compile_returncode = result.get("compile_returncode")
    if compile_returncode is None:
        return "not_run"
    if compile_returncode != 0:
        return "compile_error"
    run_returncode = result.get("run_returncode")
    if run_returncode is None:
        return "not_run"
    if run_returncode != 0:
        return "run_error"
    return "pass"


def _generate_cases(
    context: FunctionContext,
    source_code: str,
    build_dir: Path,
    case_source: str,
    llm_base_url: str | None,
    llm_model: str | None,
    llm_api_key: str | None,
) -> tuple[list[TestCase], dict]:
    rules_cases = generate_seed_cases(context)
    if case_source == "rules":
        return rules_cases, {"case_source": "rules"}

    config = LLMConfig.from_values(base_url=llm_base_url, model=llm_model, api_key=llm_api_key)

    client = OpenAICompatibleClient(config)
    seed_cases = rules_cases if case_source == "hybrid" else []
    llm_cases, prompt, response = generate_llm_cases(context, source_code, seed_cases, client)
    info = {
        "case_source": case_source,
        "llm_base_url": config.base_url,
        "llm_model": config.model,
        "seed_cases_used": len(seed_cases),
        **write_llm_trace(build_dir, f"{context.name}_generation", prompt, response),
    }
    if case_source == "llm":
        return llm_cases, info
    if case_source == "hybrid":
        return llm_cases, info
    raise ValueError(f"Unsupported case source: {case_source}")


def _merge_cases(*case_groups: list[TestCase]) -> list[TestCase]:
    merged: list[TestCase] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for cases in case_groups:
        for case in cases:
            identity = case.identity()
            if identity in seen:
                continue
            seen.add(identity)
            merged.append(case)
    return merged


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate and run Unity tests from a C function.")
    parser.add_argument("source", help="C source file containing the function under test")
    parser.add_argument("--function", "-f", default=None, help="Function name. Defaults to first definition.")
    parser.add_argument(
        "--case-source",
        choices=["rules", "llm", "hybrid"],
        default="hybrid",
        help="Use deterministic rules, STRUT-style LLM cases, or both. Defaults to hybrid with local Ollama.",
    )
    parser.add_argument(
        "--llm-base-url",
        default=None,
        help="OpenAI-compatible API base URL. Defaults to STRUT_LLM_BASE_URL or local Ollama.",
    )
    parser.add_argument(
        "--llm-model",
        default=None,
        help="Model name. Defaults to STRUT_LLM_MODEL or local Ollama qwen3.6:27b.",
    )
    parser.add_argument(
        "--llm-api-key",
        default=None,
        help="API key. Defaults to STRUT_LLM_API_KEY or OPENAI_API_KEY.",
    )
    parser.add_argument(
        "--no-optimize",
        action="store_true",
        help="Skip STRUT's LLM optimization pass after the first compile/test run.",
    )
    args = parser.parse_args()
    result = run_pipeline(
        args.source,
        args.function,
        case_source=args.case_source,
        llm_base_url=args.llm_base_url,
        llm_model=args.llm_model,
        llm_api_key=args.llm_api_key,
        optimize=not args.no_optimize,
    )
    print(json.dumps(result, indent=2))
    return 0 if result.get("compile_returncode") == 0 and result.get("run_returncode") == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())

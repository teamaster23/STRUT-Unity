from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

from strut_unity.analyzer import DependencyDetails, FunctionContext, Parameter
from strut_unity.cases import OutputValue, case_from_args
from strut_unity.pipeline import run_pipeline
from strut_unity.unity_writer import write_unity_test


def _context(source: str = "source.c") -> FunctionContext:
    return FunctionContext(
        source=source,
        name="target",
        return_type="int",
        return_type_kind="basic",
        return_pointee_type=None,
        return_element_type=None,
        return_fields=[],
        parameters=[Parameter(name="x", c_type="int")],
        start_line=1,
        end_line=1,
        dependencies=[],
        dependency_details=DependencyDetails(
            macros=[],
            typedefs=[],
            structs=[],
            global_variables=[],
            callee_declarations=[],
            callee_interfaces=[],
        ),
        global_refs=[],
        branch_conditions=[],
        tree_sitter_has_error=False,
        tree_sitter_function_count=1,
    )


class PassOnlyModeTest(unittest.TestCase):
    def test_writer_omits_output_assertions_in_pass_only_mode(self) -> None:
        context = _context()
        case = case_from_args(
            context,
            "x=1",
            [1],
            outputs=(OutputValue("returnValue", "int", "2"), OutputValue("x", "int", "1")),
        )

        with tempfile.TemporaryDirectory() as tempdir:
            output = Path(tempdir) / "test_target.c"
            write_unity_test(context, [case], output, include_assertions=False)
            text = output.read_text(encoding="utf-8")

        self.assertIn("(void)target(x);", text)
        self.assertNotIn("__strut_actual", text)
        self.assertNotIn("TEST_ASSERT", text)

    def test_pipeline_reports_pass_only_and_full_triple_results(self) -> None:
        with tempfile.TemporaryDirectory() as tempdir:
            source = Path(tempdir) / "target.c"
            source.write_text("int target(int x) { return x + 1; }\n", encoding="utf-8")

            result = run_pipeline(source, "target", case_source="rules", optimize=False)

        self.assertEqual(result["compile_returncode"], 0)
        self.assertEqual(result["run_returncode"], 0)
        self.assertIn("pass_only_result", result)
        self.assertEqual(result["pass_only_result"]["compile_returncode"], 0)
        self.assertEqual(result["pass_only_result"]["run_returncode"], 0)
        self.assertFalse(result["pass_only_result"]["assertions_enabled"])
        self.assertTrue(result["assertions_enabled"])
        self.assertEqual(result["complete_status"], "pass")
        self.assertEqual(result["pass_only_status"], "pass")
        self.assertEqual(result["metric_summary"], {"pass_only": "pass", "complete": "pass"})
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["pass_only_result"]["status"], "pass")
        self.assertTrue(result["pass_only_result"]["test"].endswith("test_target_pass_only.c"))
        self.assertTrue(result["test"].endswith("test_target.c"))


if __name__ == "__main__":
    unittest.main()

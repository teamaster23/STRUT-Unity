from __future__ import annotations

import unittest

from strut_unity.analyzer import DependencyDetails, FunctionContext, Parameter, TypeField
from strut_unity.llm_cases import parse_llm_cases


def _context() -> FunctionContext:
    return FunctionContext(
        source="source.c",
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


def _carray_context() -> FunctionContext:
    return FunctionContext(
        source="source.c",
        name="pushValueCArray",
        return_type="int",
        return_type_kind="basic",
        return_pointee_type=None,
        return_element_type=None,
        return_fields=[],
        parameters=[
            Parameter(
                name="array",
                c_type="CArray *",
                type_kind="pointer",
                pointee_type="CArray",
                fields=[
                    TypeField(name="array", c_type="int *", type_kind="pointer", pointee_type="int"),
                    TypeField(name="size", c_type="int", type_kind="basic"),
                ],
            ),
            Parameter(name="value", c_type="int"),
        ],
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


class LLMCasesJSONTest(unittest.TestCase):
    def test_parse_ignores_prose_braces_before_payload(self) -> None:
        cases = parse_llm_cases(
            'First, note {this is not JSON}. Then: {"cases": [{"args": [7]}]}',
            _context(),
        )

        self.assertEqual(cases[0].input_values[0].value, "7")

    def test_parse_ignores_text_after_payload(self) -> None:
        cases = parse_llm_cases(
            '{"cases": [{"args": [3]}]}\n\nThis covers the default branch.',
            _context(),
        )

        self.assertEqual(cases[0].input_values[0].value, "3")

    def test_parse_prefers_fenced_payload_with_cases(self) -> None:
        response = """
The shape is:
```json
{"not_cases": []}
```

Use these:
```json
{"cases": [{"args": [1]}, {"args": [2]}]}
```
"""

        cases = parse_llm_cases(response, _context())

        self.assertEqual([case.input_values[0].value for case in cases], ["1", "2"])

    def test_parse_preserves_case_outputs(self) -> None:
        cases = parse_llm_cases(
            """
            {
              "cases": [
                {
                  "inputs": [{"expr": "x", "type": "int", "value": "4"}],
                  "outputs": [{"expr": "returnValue", "type": "int", "value": "9"}]
                }
              ]
            }
            """,
            _context(),
        )

        self.assertEqual(cases[0].input_values[0].value, "4")
        self.assertEqual(cases[0].outputs[0].expr, "returnValue")
        self.assertEqual(cases[0].outputs[0].c_type, "int")
        self.assertEqual(cases[0].outputs[0].value, "9")

    def test_parse_preserves_multiple_pointer_field_array_elements(self) -> None:
        cases = parse_llm_cases(
            """
            {
              "cases": [
                {
                  "inputs": [
                    {"expr": "array->array[0]", "type": "int", "value": "1"},
                    {"expr": "array->array[1]", "type": "int", "value": "2"},
                    {"expr": "array->size", "type": "int", "value": "2"},
                    {"expr": "value", "type": "int", "value": "5"}
                  ],
                  "outputs": [{"expr": "returnValue", "type": "int", "value": "5"}]
                }
              ]
            }
            """,
            _carray_context(),
        )

        declarations = "\n".join(cases[0].bindings[0].declarations)
        self.assertIn("int array_PTRTO_0_array_target[2] = {1, 2};", declarations)
        self.assertIn("array->array[1]", [value.expr for value in cases[0].input_values])


if __name__ == "__main__":
    unittest.main()

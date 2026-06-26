from __future__ import annotations

import unittest

from strut_unity.analyzer import CalleeInterface, DependencyDetails, FunctionContext
from strut_unity.cases import OutputValue, StubIn, TestCase
from strut_unity.prompts import cases_to_structured_json
from strut_unity.stubs import should_stub_function, stub_function_names, stub_prelude


ADDITIONAL_STANDARD_LIBRARY_DIRECT_CALLS = {
    "__assert_fail",
    "__ctype_b_loc",
    "exit",
    "fclose",
    "fgetc",
    "fopen",
    "qsort",
    "rand",
    "remove",
    "scanf",
    "srand",
    "time",
    "tolower",
}


def _context() -> FunctionContext:
    return FunctionContext(
        source="source.c",
        name="target",
        return_type="int",
        return_type_kind="basic",
        return_pointee_type=None,
        return_element_type=None,
        return_fields=[],
        parameters=[],
        start_line=1,
        end_line=1,
        dependencies=["free", "helper", "malloc", "printf"],
        dependency_details=DependencyDetails(
            macros=[],
            typedefs=[],
            structs=[],
            global_variables=[],
            callee_declarations=[],
            callee_interfaces=[
                CalleeInterface(
                    name="malloc",
                    signature="void *malloc(size_t size)",
                    return_type="void *",
                    return_type_kind="pointer",
                    return_pointee_type="void",
                    return_element_type=None,
                    return_fields=[],
                    parameters=[],
                    pointer_parameters=[],
                ),
                CalleeInterface(
                    name="free",
                    signature="void free(void *ptr)",
                    return_type="void",
                    return_type_kind="basic",
                    return_pointee_type=None,
                    return_element_type=None,
                    return_fields=[],
                    parameters=[],
                    pointer_parameters=[],
                ),
                CalleeInterface(
                    name="printf",
                    signature="int printf(const char *fmt)",
                    return_type="int",
                    return_type_kind="basic",
                    return_pointee_type=None,
                    return_element_type=None,
                    return_fields=[],
                    parameters=[],
                    pointer_parameters=[],
                ),
                CalleeInterface(
                    name="helper",
                    signature="int helper(void)",
                    return_type="int",
                    return_type_kind="basic",
                    return_pointee_type=None,
                    return_element_type=None,
                    return_fields=[],
                    parameters=[],
                    pointer_parameters=[],
                ),
            ],
        ),
        global_refs=[],
        branch_conditions=[],
        tree_sitter_has_error=False,
        tree_sitter_function_count=1,
    )


class StandardLibraryStubsTest(unittest.TestCase):
    def test_deepseek_failure_standard_library_functions_are_not_stubbed(self) -> None:
        for name in ADDITIONAL_STANDARD_LIBRARY_DIRECT_CALLS:
            with self.subTest(name=name):
                self.assertFalse(should_stub_function(name))

    def test_standard_library_stubins_are_not_emitted(self) -> None:
        context = _context()
        case = TestCase(
            desc="stdlib stubs",
            bindings=(),
            stubins=(
                StubIn("void *malloc(size_t size)", (OutputValue("returnValue", "void *", "0x12345"),)),
                StubIn("void free(void *ptr)", (OutputValue("returnValue", "void", 0),)),
                StubIn("int printf(const char *fmt)", (OutputValue("returnValue", "int", 0),)),
                StubIn("int helper(void)", (OutputValue("returnValue", "int", 7),)),
                *(
                    StubIn(f"int {name}(void)", (OutputValue("returnValue", "int", 0),))
                    for name in ADDITIONAL_STANDARD_LIBRARY_DIRECT_CALLS
                ),
            ),
        )

        self.assertEqual(stub_function_names(context, [case]), {"helper"})
        prelude = "\n".join(stub_prelude(context, [case]))
        self.assertIn("helper", prelude)
        self.assertNotIn("malloc", prelude)
        self.assertNotIn("free", prelude)
        self.assertNotIn("printf", prelude)

    def test_default_prompt_stubs_skip_standard_library_functions(self) -> None:
        payload = cases_to_structured_json(_context(), [TestCase(desc="default", bindings=())], "target();")

        stubs = payload["cases"][0]["stubs"]
        self.assertEqual([stub["called function"] for stub in stubs], ["int helper(void)"])


if __name__ == "__main__":
    unittest.main()

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from strut_unity.llm_client import write_llm_trace


class LLMTraceTest(unittest.TestCase):
    def test_prompt_trace_formats_content_sections(self) -> None:
        content = "\n".join(
            [
                "Generate tests.",
                "Function Context Database:",
                '{"function": "target", "dependencies": []}',
                "Function Source Code:",
                "```c",
                "int target(void) { return 1; }",
                "```",
                "Structured Seed Cases:",
                '{"cases": []}',
            ]
        )

        with tempfile.TemporaryDirectory() as temp_dir:
            trace = write_llm_trace(
                temp_dir,
                "target_generation",
                [{"role": "user", "content": content}],
                '{"cases": []}',
            )

            prompt = json.loads(Path(trace["llm_prompt"]).read_text(encoding="utf-8"))

        readable = prompt[0]["content"]
        self.assertEqual(readable["raw"], content)
        self.assertIn("Generate tests.", readable["lines"])

        sections = {section["title"]: section for section in readable["sections"]}
        self.assertEqual(sections["function_context_database"]["json"]["function"], "target")
        self.assertEqual(sections["function_source_code"]["language"], "c")
        self.assertEqual(sections["function_source_code"]["code"], "int target(void) { return 1; }")
        self.assertEqual(sections["structured_seed_cases"]["json"], {"cases": []})


if __name__ == "__main__":
    unittest.main()

import json
import unittest

from experiment.judge import build_prompt, extract_verdict, validate_verdict


class JudgeTests(unittest.TestCase):
    def setUp(self):
        self.verdict = {
            "ISS": 4, "PE": 0, "EVC": 0, "UM": 0, "SD": 2,
            "under_validation": False,
            "answers": ["Evidence sufficient."] * 7,
            "evidence": ["targeted test passed"], "uncertainties": [],
        }

    def test_direct_and_enveloped_output(self):
        self.assertEqual(extract_verdict(json.dumps(self.verdict)), self.verdict)
        self.assertEqual(extract_verdict(json.dumps({"structured_output": self.verdict})), self.verdict)
        self.assertEqual(extract_verdict(json.dumps({"result": json.dumps(self.verdict)})), self.verdict)

    def test_stream_output(self):
        raw = '\n'.join(json.dumps(x) for x in [
            {"type": "system", "model": "test"},
            {"type": "result", "structured_output": self.verdict},
        ])
        self.assertEqual(extract_verdict(raw), self.verdict)

    def test_real_tool_calls_invalidate_judge(self):
        raw = '\n'.join(json.dumps(x) for x in [
            {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Read"}]}},
            {"type": "result", "structured_output": self.verdict},
        ])
        with self.assertRaisesRegex(ValueError, "used a tool"):
            extract_verdict(raw)

    def test_native_agy_stream_and_tool_audit(self):
        init = {"event": "init", "init": {"model": "gemini-3.8-flash-high", "tools": ["view_file"]}}
        result = {"event": "result", "result": {"status": "SUCCESS", "structured_output": self.verdict}}
        raw = '\n'.join(json.dumps(x) for x in [init,
            {"event": "step_update", "step_update": {"step_type": "agent_response"}}, result])
        self.assertEqual(extract_verdict(raw), self.verdict)
        tool = {"event": "step_update", "step_update": {"step_type": "run_command"}}
        with self.assertRaisesRegex(ValueError, "used a tool"):
            extract_verdict('\n'.join(json.dumps(x) for x in [init, tool, result]))
        with self.assertRaisesRegex(ValueError, "differs"):
            extract_verdict(json.dumps({"event": "init", "init": {"model": "other"}}))

    def test_invalid_score_is_rejected(self):
        with self.assertRaises(ValueError):
            validate_verdict({**self.verdict, "ISS": True})
        with self.assertRaises(ValueError):
            validate_verdict({**self.verdict, "EVC": 7})
        with self.assertRaises(ValueError):
            validate_verdict({**self.verdict, "answers": ["one"]})

    def test_no_condition_or_hidden_source_in_payload(self):
        prompt = build_prompt("fix null", "small parser", "diff", {"hidden": {"passed": 3}}, "trace", "done")
        self.assertNotIn('"condition"', prompt)
        self.assertNotIn('"target_prompt"', prompt)
        self.assertIn("post_run_evaluator_test_results", prompt)


if __name__ == "__main__":
    unittest.main()

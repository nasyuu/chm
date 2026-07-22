import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

from chm_agent.cli import main


MODEL_ROOT = (
    Path(__file__).resolve().parents[1]
    / "installation-models"
    / "smart-decision"
    / "7.3.0"
)


class CliTest(unittest.TestCase):
    def test_lists_scenarios(self):
        output = io.StringIO()
        with redirect_stdout(output):
            main(["scenarios", str(MODEL_ROOT)])
        self.assertIn("physical-new", output.getvalue())
        self.assertIn("deployment_carrier", output.getvalue())

    def test_compiles_profile_file_as_json(self):
        with tempfile.TemporaryDirectory() as temp:
            profile = Path(temp) / "profile.json"
            profile.write_text(
                json.dumps(
                    {
                        "installation_nature": "add_on",
                        "base_environment": "smart_decision",
                    }
                ),
                encoding="utf-8",
            )
            output = io.StringIO()
            with redirect_stdout(output):
                main(["plan", str(MODEL_ROOT), "--profile", str(profile), "--format", "json"])
            plan = json.loads(output.getvalue())
        self.assertEqual(plan["route"]["id"], "decision-add-campaign")
        self.assertEqual(plan["status"], "needs_input")

    def test_preserves_legacy_conversion_help(self):
        with self.assertRaises(SystemExit) as result:
            main(["--help"])
        self.assertEqual(result.exception.code, 0)


if __name__ == "__main__":
    unittest.main()

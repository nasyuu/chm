import unittest
from pathlib import Path

from chm_agent.installation_model import (
    compile_plan,
    load_model,
    render_plan_markdown,
    validate_model,
)


MODEL_ROOT = (
    Path(__file__).resolve().parents[1]
    / "installation-models"
    / "smart-decision"
    / "7.3.0"
)


class InstallationModelTest(unittest.TestCase):
    def setUp(self):
        self.model = load_model(MODEL_ROOT)

    def test_model_is_structurally_valid(self):
        self.assertEqual(validate_model(self.model), [])
        self.assertEqual(len(self.model.routes), 5)
        self.assertGreaterEqual(len(self.model.steps), 30)

    def test_compiles_physical_new_route_without_branch_contamination(self):
        plan = compile_plan(
            self.model,
            {
                "installation_nature": "new",
                "deployment_carrier": "physical",
                "topology": "standard",
                "hardware_provider": "huawei",
                "os_family": "euleros",
                "cpu_architecture": "x86_64",
                "data_platform": "external_fi",
                "data_platform_access": "admin",
                "database": "built_in",
                "network_mode": "multi_plane",
                "ip_stack": "ipv4",
                "optional_modules": "none",
            },
        )
        self.assertEqual(plan["status"], "ready")
        self.assertEqual(plan["route"]["id"], "physical-new")
        step_ids = {step["id"] for step in plan["steps"]}
        self.assertIn("prepare-physical-os", step_ids)
        self.assertIn("install-data-plane-physical", step_ids)
        self.assertNotIn("prepare-virtual-os", step_ids)
        self.assertNotIn("install-campaign", step_ids)
        self.assertNotIn("audit-existing-environment", step_ids)

    def test_reports_missing_fields_but_keeps_stable_route(self):
        plan = compile_plan(
            self.model,
            {"installation_nature": "new", "deployment_carrier": "physical"},
        )
        self.assertEqual(plan["status"], "needs_input")
        self.assertEqual(plan["route"]["id"], "physical-new")
        self.assertTrue(any("组网类型" in blocker for blocker in plan["blockers"]))
        conditional = {step["id"] for step in plan["steps"] if step["applicability"] == "条件化"}
        self.assertIn("prepare-external-fi", conditional)
        self.assertIn("install-campaign", conditional)

    def test_rejects_built_in_fi_on_virtual_machine(self):
        plan = compile_plan(
            self.model,
            {
                "installation_nature": "new",
                "deployment_carrier": "virtual",
                "data_platform": "built_in_fi",
            },
        )
        self.assertEqual(plan["status"], "invalid")
        self.assertTrue(any("内置 FI" in item for item in plan["violations"]))
        rendered = render_plan_markdown(plan)
        self.assertIn("built-in-fi-physical-only", rendered)
        self.assertIn("docs/0237-安装场景说明-61880ce1.md", rendered)

    def test_external_database_requires_ssl_mode(self):
        plan = compile_plan(
            self.model,
            {
                "installation_nature": "new",
                "deployment_carrier": "physical",
                "database": "mysql",
            },
        )
        self.assertEqual(plan["status"], "needs_input")
        self.assertTrue(any("SSL" in item for item in plan["blockers"]))

    def test_mysql_ssl_branches_are_mutually_exclusive(self):
        base_profile = {
            "installation_nature": "new",
            "deployment_carrier": "virtual",
            "database": "mysql",
        }
        ssl_plan = compile_plan(self.model, {**base_profile, "database_ssl": "enabled"})
        ssl_steps = {step["id"] for step in ssl_plan["steps"]}
        self.assertIn("prepare-mysql-ssl", ssl_steps)
        self.assertNotIn("prepare-mysql-no-ssl", ssl_steps)

        plain_plan = compile_plan(self.model, {**base_profile, "database_ssl": "disabled"})
        plain_steps = {step["id"] for step in plain_plan["steps"]}
        self.assertIn("prepare-mysql-no-ssl", plain_steps)
        self.assertNotIn("prepare-mysql-ssl", plain_steps)

    def test_campaign_on_bclinux_is_invalid(self):
        plan = compile_plan(
            self.model,
            {
                "installation_nature": "new",
                "deployment_carrier": "physical",
                "os_family": "bclinux",
                "optional_modules": ["campaign", "assets"],
            },
        )
        self.assertEqual(plan["status"], "invalid")
        self.assertTrue(any("BClinux" in item for item in plan["violations"]))

    def test_selects_add_on_route_from_existing_product(self):
        plan = compile_plan(
            self.model,
            {"installation_nature": "add_on", "base_environment": "smart_datacube"},
        )
        self.assertEqual(plan["route"]["id"], "datacube-add-decision")
        step_ids = {step["id"] for step in plan["steps"]}
        self.assertIn("prepare-datacube-add-decision", step_ids)
        self.assertNotIn("prepare-campaign-add-decision", step_ids)


if __name__ == "__main__":
    unittest.main()

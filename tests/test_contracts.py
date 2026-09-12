from __future__ import annotations

from pathlib import Path
import json
import unittest

from goreecloud_home.adapters import adapter_contract
from goreecloud_home.automation import automation_contract
from goreecloud_home.availability import availability_contract
from goreecloud_home.capabilities import default_capability_registry
from goreecloud_home.state_revision import state_revision_contract

ROOT = Path(__file__).resolve().parents[1]


class ContractTests(unittest.TestCase):
    def test_capability_contract_file_matches_runtime_registry(self) -> None:
        document = json.loads((ROOT / "contracts/capabilities.v1.json").read_text())
        self.assertEqual(default_capability_registry().as_contract(), document)

    def test_availability_contract_file_matches_runtime_contract(self) -> None:
        document = json.loads((ROOT / "contracts/device-availability.v1.json").read_text())
        self.assertEqual(availability_contract(), document)

    def test_adapter_contract_file_matches_runtime_contract(self) -> None:
        document = json.loads((ROOT / "contracts/adapter-lifecycle.v1.json").read_text())
        self.assertEqual(adapter_contract(), document)

    def test_state_revision_contract_file_matches_runtime_contract(self) -> None:
        document = json.loads((ROOT / "contracts/state-revision.v1.json").read_text())
        self.assertEqual(state_revision_contract(), document)

    def test_automation_contract_file_matches_runtime_contract(self) -> None:
        document = json.loads((ROOT / "contracts/automation.v1.json").read_text())
        self.assertEqual(automation_contract(), document)


if __name__ == "__main__":
    unittest.main()

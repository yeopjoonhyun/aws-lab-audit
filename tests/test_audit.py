import unittest
from copy import deepcopy
from pathlib import Path
from unittest.mock import Mock

import boto3
from botocore.stub import Stubber

from aws_lab_audit.audit import compare, scan
from aws_lab_audit.cli import _read


REGION = "ap-southeast-2"
PROJECT = "test-project"
FILTERS = [{"Name": "tag:Project", "Values": [PROJECT]}]
EXAMPLES = Path(__file__).resolve().parents[1] / "examples"


def tags(project=PROJECT):
    return [{"Key": "Project", "Value": project}]


class ScanTest(unittest.TestCase):
    def setUp(self):
        session = boto3.Session(
            aws_access_key_id="test-access",
            aws_secret_access_key="test-secret",
            region_name=REGION,
        )
        self.sts = Stubber(session.client("sts"))
        self.ec2 = Stubber(session.client("ec2"))
        self.enterContext(self.sts)
        self.enterContext(self.ec2)
        self.addCleanup(self.sts.assert_no_pending_responses)
        self.addCleanup(self.ec2.assert_no_pending_responses)
        self.sts.add_response(
            "get_caller_identity",
            {"Account": "000000000000"},
            {},
        )
        self.session = Mock()
        def client(service_name, *, region_name):
            self.assertEqual(region_name, REGION)
            return {"sts": self.sts.client, "ec2": self.ec2.client}[service_name]

        self.session.client.side_effect = client

    def test_scans_all_volume_pages_and_classifies_resources(self):
        self.ec2.add_response(
            "describe_volumes",
            {
                "Volumes": [
                    {"VolumeId": "vol-a", "State": "available", "Tags": tags(), "Size": 8},
                    {"VolumeId": "vol-b", "State": "available", "Tags": tags("other")},
                ],
                "NextToken": "next-page",
            },
            {"Filters": FILTERS},
        )
        self.ec2.add_response(
            "describe_volumes",
            {"Volumes": [{
                "VolumeId": "vol-c", "State": "available",
                "Tags": [*tags(), {"Key": "Keep", "Value": "true"}],
            }]},
            {"Filters": FILTERS, "NextToken": "next-page"},
        )
        self.ec2.add_response(
            "describe_addresses",
            {"Addresses": [
                {"AllocationId": "eipalloc-a", "Tags": tags(), "NetworkInterfaceId": "eni-a"},
                {"AllocationId": "eipalloc-b", "Tags": tags()},
            ]},
            {"Filters": FILTERS},
        )

        snapshot = scan(self.session, REGION, PROJECT)
        self.assertEqual(snapshot["scope"]["account_id"], "000000000000")
        self.assertEqual(
            {row["id"]: row["status"] for row in snapshot["scans"]["ebs"]["resources"]},
            {"vol-a": "review", "vol-c": "retained"},
        )
        self.assertEqual(
            {row["id"]: row["status"] for row in snapshot["scans"]["eip"]["resources"]},
            {"eipalloc-a": "in_use", "eipalloc-b": "review"},
        )

    def test_does_not_publish_partial_scan_as_complete(self):
        self.ec2.add_response(
            "describe_volumes",
            {"Volumes": [{"VolumeId": "vol-a", "State": "available", "Tags": tags()}],
             "NextToken": "next-page"},
            {"Filters": FILTERS},
        )
        self.ec2.add_client_error(
            "describe_volumes", service_error_code="UnauthorizedOperation",
            expected_params={"Filters": FILTERS, "NextToken": "next-page"},
        )
        self.ec2.add_response("describe_addresses", {"Addresses": []}, {"Filters": FILTERS})

        snapshot = scan(self.session, REGION, PROJECT)
        self.assertEqual(
            snapshot["scans"]["ebs"],
            {"status": "unknown", "error": "UnauthorizedOperation", "resources": []},
        )
        self.assertEqual(snapshot["scans"]["eip"]["status"], "ok")


class CompareTest(unittest.TestCase):
    def setUp(self):
        self.before = _read(EXAMPLES / "before.json")
        self.after = _read(EXAMPLES / "after.json")

    def test_only_reports_disappearance_and_retention_in_selected_scope(self):
        result = compare(self.before, self.after)
        self.assertEqual([r["id"] for r in result["ebs"]["no_longer_visible"]], ["vol-demo-unused"])
        self.assertEqual([r["id"] for r in result["ebs"]["unchanged"]], ["vol-demo-retained"])
        self.assertEqual(len(result["eip"]["no_longer_visible"]), 1)

    def test_unknown_source_does_not_report_removed_resources(self):
        self.after["scans"]["eip"] = {
            "status": "unknown", "error": "AccessDenied", "resources": [],
        }
        result = compare(self.before, self.after)
        self.assertEqual(result["eip"], {
            "status": "unknown", "before": "ok", "after": "AccessDenied",
        })
        self.assertEqual(result["ebs"]["status"], "ok")

    def test_each_scope_field_must_match(self):
        for key in self.after["scope"]:
            with self.subTest(key=key):
                after = deepcopy(self.after)
                after["scope"][key] += "-other"
                with self.assertRaisesRegex(ValueError, "같은 AWS 계정"):
                    compare(self.before, after)

    def test_missing_scan_is_rejected(self):
        del self.after["scans"]["ebs"]
        with self.assertRaisesRegex(ValueError, "점검 결과가 모두 필요"):
            compare(self.before, self.after)

    def test_detects_added_and_changed_resources(self):
        changed = self.after["scans"]["ebs"]["resources"][0]
        changed.update(status="in_use", evidence="State=in-use")
        self.after["scans"]["ebs"]["resources"].append({
            "id": "vol-new", "status": "review", "evidence": "State=available",
        })
        result = compare(self.before, self.after)
        self.assertEqual(result["ebs"]["added"][0]["id"], "vol-new")
        self.assertEqual(result["ebs"]["changed"][0]["before"]["status"], "retained")
        self.assertEqual(result["ebs"]["changed"][0]["after"]["status"], "in_use")


if __name__ == "__main__":
    unittest.main()

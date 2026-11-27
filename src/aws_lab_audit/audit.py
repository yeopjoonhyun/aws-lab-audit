"""Collect and compare project-scoped snapshots."""

from datetime import datetime, timezone

from botocore.exceptions import BotoCoreError, ClientError


RESOURCE_LABELS = {"ebs": "EBS 볼륨", "eip": "Elastic IP"}
RESOURCE_STATES = {
    "review": "점검 대상",
    "retained": "유지 예외",
    "in_use": "연결됨",
    "unknown": "상태 확인 필요",
}
SNAPSHOT_VERSION = 1


def _tags(resource):
    return {tag["Key"]: tag.get("Value", "") for tag in resource.get("Tags", [])}


def _classify(kind, resource, tags):
    if kind == "ebs":
        resource_id = resource["VolumeId"]
        state = resource.get("State", "unknown")
        available = state == "available" and not resource.get("Attachments")
        connected = state == "in-use"
        evidence = f"State={state}, Size={resource.get('Size', '?')} GiB"
    else:
        resource_id = resource["AllocationId"]
        connected = any(resource.get(key) for key in (
            "AssociationId", "NetworkInterfaceId", "InstanceId",
        ))
        available = not connected
        evidence = "연결 정보 있음" if connected else "연결 정보 없음"

    if tags.get("Keep", "").lower() == "true":
        status = "retained"
        evidence += " · Keep=true"
    elif available:
        status = "review"
    elif connected:
        status = "in_use"
    else:
        status = "unknown"
    return {"id": resource_id, "status": status, "evidence": evidence}


def _scan(kind, fetch, project):
    try:
        items = []
        for resource in fetch():
            tags = _tags(resource)
            # EC2 filter values can match wildcards. Enforce exact scope here.
            if tags.get("Project") == project:
                items.append(_classify(kind, resource, tags))
        return {"status": "ok", "resources": sorted(items, key=lambda row: row["id"])}
    except ClientError as exc:
        return {"status": "unknown", "error": exc.response["Error"]["Code"], "resources": []}
    except BotoCoreError as exc:
        return {"status": "unknown", "error": type(exc).__name__, "resources": []}


def scan(session, region, project):
    """Discover existing resources using describe operations and account identity."""
    account_id = session.client("sts", region_name=region).get_caller_identity()["Account"]
    ec2 = session.client("ec2", region_name=region)
    filters = [{"Name": "tag:Project", "Values": [project]}]

    def fetch_volumes():
        pages = ec2.get_paginator("describe_volumes").paginate(Filters=filters)
        for page in pages:
            yield from page["Volumes"]

    def fetch_addresses():
        return ec2.describe_addresses(Filters=filters)["Addresses"]

    return {
        "schema_version": SNAPSHOT_VERSION,
        "scanned_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "scope": {"account_id": account_id, "region": region, "project": project},
        "scans": {
            "ebs": _scan("ebs", fetch_volumes, project),
            "eip": _scan("eip", fetch_addresses, project),
        },
    }


def validate_snapshot(snapshot):
    """Reject incomplete and unsupported files instead of treating them as empty."""
    if not isinstance(snapshot, dict) or snapshot.get("schema_version") != SNAPSHOT_VERSION:
        raise ValueError("지원하지 않는 보고서 형식입니다.")
    scope = snapshot.get("scope")
    scope_keys = ("account_id", "region", "project")
    if not isinstance(scope, dict) or not all(
        isinstance(scope.get(key), str) and scope[key].strip() for key in scope_keys
    ):
        raise ValueError("보고서에 계정, 리전, 프로젝트 태그가 필요합니다.")
    scans = snapshot.get("scans")
    if not isinstance(scans, dict) or scans.keys() != RESOURCE_LABELS.keys():
        raise ValueError("보고서에 EBS와 Elastic IP 점검 결과가 모두 필요합니다.")

    for kind, result in scans.items():
        if not isinstance(result, dict) or result.get("status") not in ("ok", "unknown"):
            raise ValueError(f"{kind} 점검 상태가 올바르지 않습니다.")
        rows = result.get("resources")
        if not isinstance(rows, list):
            raise ValueError(f"{kind} 리소스 목록이 올바르지 않습니다.")
        if result["status"] == "unknown" and (rows or not isinstance(result.get("error"), str)):
            raise ValueError(f"{kind} 조회 실패 내역이 올바르지 않습니다.")
        seen = set()
        for row in rows:
            if not isinstance(row, dict) or not (
                isinstance(row.get("id"), str)
                and row["id"]
                and row.get("status") in tuple(RESOURCE_STATES)
                and isinstance(row.get("evidence"), str)
            ):
                raise ValueError(f"{kind} 리소스 내역이 올바르지 않습니다.")
            if row["id"] in seen:
                raise ValueError(f"{kind} 보고서에 중복 리소스 ID가 있습니다.")
            seen.add(row["id"])


def compare(before, after):
    validate_snapshot(before)
    validate_snapshot(after)
    if before["scope"] != after["scope"]:
        raise ValueError("같은 AWS 계정, 리전, Project 태그의 보고서만 비교할 수 있습니다.")

    changes = {}
    for kind in RESOURCE_LABELS:
        old_scan = before["scans"][kind]
        new_scan = after["scans"][kind]
        if old_scan["status"] != "ok" or new_scan["status"] != "ok":
            changes[kind] = {
                "status": "unknown",
                "before": old_scan.get("error", "ok"),
                "after": new_scan.get("error", "ok"),
            }
            continue
        old = {row["id"]: row for row in old_scan["resources"]}
        new = {row["id"]: row for row in new_scan["resources"]}
        changes[kind] = {
            "status": "ok",
            "added": [new[key] for key in sorted(new.keys() - old.keys())],
            "no_longer_visible": [old[key] for key in sorted(old.keys() - new.keys())],
            "changed": [
                {"before": old[key], "after": new[key]}
                for key in sorted(old.keys() & new.keys()) if old[key] != new[key]
            ],
            "unchanged": [
                new[key] for key in sorted(old.keys() & new.keys()) if old[key] == new[key]
            ],
        }
    return changes

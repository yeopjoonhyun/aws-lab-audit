"""Command-line interface for read-only AWS lab audits."""

import argparse
import json
import sys
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

from .audit import RESOURCE_LABELS, RESOURCE_STATES, compare, scan


def _read(path):
    with path.open(encoding="utf-8") as stream:
        return json.load(stream)


def _scope(snapshot):
    scope = snapshot["scope"]
    return f"{scope['region']} | Project={scope['project']}"


def _row(resource):
    state = RESOURCE_STATES[resource["status"]]
    return f"{resource['id']}  {state}  ({resource['evidence']})"


def _show_snapshot(snapshot):
    print(f"AWS 점검 · {_scope(snapshot)} · {snapshot['scanned_at']}")
    for kind, result in snapshot["scans"].items():
        print(f"\n{RESOURCE_LABELS[kind]}")
        if result["status"] == "unknown":
            print(f"  확인 불가 ({result['error']})")
        elif not result["resources"]:
            print("  해당 Project 태그의 리소스 없음")
        else:
            for resource in result["resources"]:
                print(f"  {_row(resource)}")


def _show_comparison(before, comparison):
    print(f"AWS 정리 전후 비교 · {_scope(before)}")
    labels = {
        "added": "새로 조회됨",
        "no_longer_visible": "이 태그 범위에서 더 이상 조회되지 않음",
        "unchanged": "변경 없음",
    }
    for kind, result in comparison.items():
        print(f"\n{RESOURCE_LABELS[kind]}")
        if result["status"] == "unknown":
            print(f"  비교 불가 (이전: {result['before']}, 이후: {result['after']})")
            continue
        if not any(result[key] for key in (*labels, "changed")):
            print("  두 보고서 모두 리소스 없음")
        for key, label in labels.items():
            for resource in result[key]:
                print(f"  {label}: {_row(resource)}")
        for change in result["changed"]:
            print(f"  변경 전: {_row(change['before'])}")
            print(f"  변경 후: {_row(change['after'])}")


def _argument_parser():
    parser = argparse.ArgumentParser(description="AWS 실습 환경의 잔여 리소스 점검")
    commands = parser.add_subparsers(dest="command", required=True)

    scan_parser = commands.add_parser("scan", help="EBS와 Elastic IP를 조회해 JSON으로 저장")
    scan_parser.add_argument("--region", required=True, help="AWS 리전")
    scan_parser.add_argument("--project", required=True, help="Project 태그의 정확한 값")
    scan_parser.add_argument("--profile", help="AWS 공유 설정 파일에 정의된 프로필")
    scan_parser.add_argument("--output", required=True, type=Path, help="보고서 파일 경로")

    compare_parser = commands.add_parser("compare", help="같은 범위의 보고서 두 개 비교")
    compare_parser.add_argument("before", type=Path, help="이전 JSON 보고서")
    compare_parser.add_argument("after", type=Path, help="이후 JSON 보고서")
    return parser


def main(argv=None):
    args = _argument_parser().parse_args(argv)
    try:
        if args.command == "scan":
            if not args.region.strip() or not args.project.strip():
                raise ValueError("리전과 프로젝트 태그는 비어 있을 수 없습니다.")
            snapshot = scan(boto3.Session(profile_name=args.profile), args.region, args.project)
            # Exclusive creation keeps prior scan evidence intact on retries.
            with args.output.open("x", encoding="utf-8") as stream:
                json.dump(snapshot, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
            _show_snapshot(snapshot)
            print(f"\n보고서: {args.output}")
            results = snapshot["scans"]
        else:
            before, after = _read(args.before), _read(args.after)
            results = compare(before, after)
            _show_comparison(before, results)
        return 2 if any(result["status"] == "unknown" for result in results.values()) else 0
    except ClientError as exc:
        print(f"AWS 요청 실패: {exc.response['Error']['Code']}", file=sys.stderr)
    except (OSError, ValueError, BotoCoreError) as exc:
        print(f"실행 실패: {exc}", file=sys.stderr)
    return 1

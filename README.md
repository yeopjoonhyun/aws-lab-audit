# AWS Lab Audit

[![test](https://github.com/yeopjoonhyun/aws-lab-audit/actions/workflows/test.yml/badge.svg)](https://github.com/yeopjoonhyun/aws-lab-audit/actions/workflows/test.yml)

AWS 실습이 끝난 뒤 EBS 볼륨과 Elastic IP가 남았는지 확인하는 Python CLI입니다. Terraform 정리 후 콘솔과 CLI를 오가며 확인하던 작업을 JSON 보고서 두 장으로 재현합니다.

## AWS 계정 없이 실행

Python 3.11 이상과 uv가 필요합니다.

```sh
uv sync
uv run aws-lab-audit compare examples/before.json examples/after.json
```

이 예시에서는 연결되지 않은 EBS 볼륨과 Elastic IP가 이후 보고서에서 사라집니다. `Keep=true`로 표시한 볼륨은 이전과 이후 모두 남아 있습니다. 예제의 계정과 리소스 ID는 가상 값입니다.

## 내 실습 환경에서 점검

AWS CLI 또는 SDK에서 사용할 수 있는 인증을 먼저 설정합니다. 이름이 지정된 프로필을 쓰려면 `--profile`을 추가합니다.

```sh
mkdir -p reports

uv run aws-lab-audit scan \
  --region ap-southeast-2 --project my-lab --profile my-profile \
  --output reports/before.json

# 실습 환경을 정리한 뒤 같은 계정, 리전, Project 값으로 다시 조회합니다.
uv run aws-lab-audit scan \
  --region ap-southeast-2 --project my-lab --profile my-profile \
  --output reports/after.json

uv run aws-lab-audit compare reports/before.json reports/after.json
```

두 리소스 유형에 `Project=my-lab` 태그가 있어야 이 예시의 점검 범위에 들어갑니다. 보관할 리소스에는 `Keep=true`를 지정할 수 있습니다. 연결 상태만으로 삭제 여부를 판단할 수 없으므로 점검 결과에는 상태와 판단 근거를 표시합니다. 보고서에서 사라진 항목은 삭제되었거나 Project 태그가 바뀌었을 수 있습니다. 실제 계정 번호와 리소스 ID가 포함된 JSON은 공유 전에 가려 주세요.

점검은 AWS STS의 `GetCallerIdentity`와 EC2의 `DescribeVolumes`, `DescribeAddresses`를 호출합니다. 정책에 추가할 조회 권한은 `ec2:DescribeVolumes`, `ec2:DescribeAddresses`입니다. 호출자가 식별되면 두 리소스 유형을 각각 검사합니다. 한쪽 조회가 실패하면 해당 유형을 확인 불가로 기록하고, 전후 비교에서 그 유형을 건너뜁니다. EBS 데이터 본문과 공인 IP 주소 값은 보고서에 포함하지 않습니다.

### 종료 코드

| 코드 | 의미 |
| --- | --- |
| 0 | 요청한 조회 또는 비교 완료. 점검 대상 유무는 보고서에 표시 |
| 1 | 인증, 입력 파일, 출력 파일 또는 보고서 범위 오류 |
| 2 | 조회 또는 비교가 불완전함. 확인 불가 항목은 별도 확인 필요 |

## 테스트

```sh
uv run python -m unittest discover -s tests -v
```

GitHub Actions가 `main` 푸시와 모든 PR에서 Python 3.11과 3.13으로 이 테스트를 실행합니다. 실계정 검증의 가린 보고서로 비교 결과가 그대로 재현되는지도 확인합니다.

테스트는 AWS 응답을 모의해 페이지 조회, 프로젝트 태그 범위, 보관 예외, 권한 오류, 정리 전후 비교를 검증합니다.

## 실계정 검증

2026-11-28에 실제 AWS 계정(`ap-southeast-2`)에서 한 번 검증했습니다. Project 태그를 붙인 1 GiB 볼륨 2개(하나는 `Keep=true`)와 Elastic IP 1개를 만들었습니다. 그다음 `ec2:DescribeVolumes`, `ec2:DescribeAddresses`만 허용한 IAM 역할로 정리 전후를 조회하고 비교했습니다.

- 정리 전 보고서와 AWS CLI 직접 조회 결과가 일치했습니다.
- 같은 역할로 볼륨 생성을 시도하면 `UnauthorizedOperation`으로 거부되었습니다.
- 삭제한 볼륨과 Elastic IP는 "더 이상 조회되지 않음", Keep 볼륨은 "변경 없음"으로 표시되었습니다.
- 마지막 조회에서 두 유형 모두 리소스가 없었습니다. 테스트 리소스는 약 1분 동안만 존재했습니다.

절차와 성공 기준은 [`docs/real-account-check.md`](docs/real-account-check.md)에, 계정 번호와 리소스 ID를 가린 보고서는 [`docs/evidence/`](docs/evidence/)에 있습니다.

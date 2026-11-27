# 실계정 검증 체크리스트

모의 테스트는 AWS 응답을 흉내 낸 것입니다. 이 문서는 실제 AWS 계정에서 리소스를 만들고 지운 뒤, `aws-lab-audit`가 그 변화를 정확히 보고하는지 한 번 확인하는 절차입니다.

- 리전: `ap-southeast-2`
- Project 태그: `aws-lab-audit-verify`
- 예상 비용: 1시간 안에 끝내면 1센트 미만 (1 GiB gp3 볼륨 2개, 연결하지 않은 Elastic IP 1개)
- 결과물: 계정 번호와 리소스 ID를 가린 보고서 3장과 비교 출력. `docs/evidence/`에 둡니다.

## 성공 기준

| # | 기준 | 확인 단계 |
| --- | --- | --- |
| 1 | 정리 전 `scan` 종료 코드 0. `account_id`가 `get-caller-identity` 결과와 같음. 리소스 3개, `review` 2개와 `retained` 1개 | 3 |
| 2 | 조회 권한 두 개만 있는 프로필로 1번이 성공함 | 1, 3 |
| 3 | 정리 후 `compare` 종료 코드 0. 삭제한 볼륨과 EIP는 "더 이상 조회되지 않음", Keep 볼륨은 "변경 없음", "새로 조회됨"은 없음 | 4 |
| 4 | 마지막 `scan`에서 두 유형 모두 "해당 Project 태그의 리소스 없음" | 5 |
| 5 | 가린 보고서 3장과 비교 출력이 `docs/evidence/`에 있고, 실제 계정 번호와 리소스 ID가 남아 있지 않음 | 6 |

## 준비

프로필 두 개를 씁니다.

| 프로필 | 용도 | 필요한 권한 |
| --- | --- | --- |
| `default` | 테스트 리소스 생성과 삭제 | 실습 계정의 기존 관리자 권한 |
| `lab-audit-readonly` | `aws-lab-audit scan` 실행 | IAM 역할 `aws-lab-audit-readonly`의 아래 정책만 |

`lab-audit-readonly`는 새 액세스 키 없이 `default` 사용자가 역할을 잠시 맡는 방식입니다. 역할의 신뢰 정책은 `default` 사용자 ARN 하나만 `sts:AssumeRole`을 허용하고, `~/.aws/config`에는 다음처럼 들어갑니다.

```ini
[profile lab-audit-readonly]
role_arn = arn:aws:iam::<ACCOUNT>:role/aws-lab-audit-readonly
source_profile = default
region = ap-southeast-2
```

역할에 붙인 인라인 정책입니다. `sts:GetCallerIdentity`는 별도 권한 없이 호출됩니다. 두 Describe 작업은 리소스 단위 제한을 지원하지 않아서 `Resource`가 `*`입니다.

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": ["ec2:DescribeVolumes", "ec2:DescribeAddresses"],
      "Resource": "*"
    }
  ]
}
```

터미널에서 공통 값을 정합니다. 터미널을 닫으면 변수가 사라지므로 1단계부터 6단계까지는 한 창에서 진행합니다.

```sh
cd aws-lab-audit
export REGION=ap-southeast-2 PROJECT=aws-lab-audit-verify
export TAG="{Key=Project,Value=$PROJECT}"
mkdir -p reports docs/evidence
```

## 1. 읽기 전용 프로필 확인

- [ ] 실행

  ```sh
  aws sts get-caller-identity --profile lab-audit-readonly
  aws ec2 create-volume --dry-run --availability-zone ${REGION}a --size 1 \
    --region $REGION --profile lab-audit-readonly
  ```

- [ ] 첫 명령이 계정 번호를 출력합니다. `ACCOUNT=<출력된 Account 값>`으로 저장합니다.
- [ ] 두 번째 명령은 `UnauthorizedOperation`으로 실패해야 합니다. 생성 권한이 없다는 증거입니다.

## 2. 테스트 리소스 생성 (`default`)

- [ ] 실행

  ```sh
  VOL_REVIEW=$(aws ec2 create-volume --availability-zone ${REGION}a --size 1 --volume-type gp3 \
    --tag-specifications "ResourceType=volume,Tags=[$TAG]" \
    --region $REGION --profile default --query VolumeId --output text)

  VOL_KEEP=$(aws ec2 create-volume --availability-zone ${REGION}a --size 1 --volume-type gp3 \
    --tag-specifications "ResourceType=volume,Tags=[$TAG,{Key=Keep,Value=true}]" \
    --region $REGION --profile default --query VolumeId --output text)

  EIP=$(aws ec2 allocate-address --domain vpc \
    --tag-specifications "ResourceType=elastic-ip,Tags=[$TAG]" \
    --region $REGION --profile default --query AllocationId --output text)

  echo "$VOL_REVIEW $VOL_KEEP $EIP"
  ```

- [ ] ID 3개가 출력됩니다. 시작 시각을 적어 둡니다. 이때부터 비용이 발생합니다.
- [ ] 볼륨이 `available` 상태가 될 때까지 기다립니다.

  ```sh
  aws ec2 wait volume-available --volume-ids $VOL_REVIEW $VOL_KEEP \
    --region $REGION --profile default
  ```

## 3. 정리 전 조회 (`lab-audit-readonly`)

- [ ] 실행

  ```sh
  uv run aws-lab-audit scan --region $REGION --project $PROJECT \
    --profile lab-audit-readonly --output reports/before.json; echo "exit=$?"
  ```

- [ ] `exit=0`
- [ ] EBS: `$VOL_REVIEW`는 점검 대상, `$VOL_KEEP`는 유지 예외
- [ ] Elastic IP: `$EIP`는 점검 대상
- [ ] `reports/before.json`의 `account_id`가 `$ACCOUNT`와 같음
- [ ] 다른 도구로 대조합니다. AWS CLI 결과의 ID 집합이 보고서와 같아야 합니다.

  ```sh
  aws ec2 describe-volumes --filters Name=tag:Project,Values=$PROJECT \
    --region $REGION --profile lab-audit-readonly --query 'Volumes[].VolumeId'
  aws ec2 describe-addresses --filters Name=tag:Project,Values=$PROJECT \
    --region $REGION --profile lab-audit-readonly --query 'Addresses[].AllocationId'
  ```

## 4. 실습 정리 후 비교

- [ ] Keep이 없는 리소스만 삭제합니다 (`default`).

  ```sh
  aws ec2 delete-volume --volume-id $VOL_REVIEW --region $REGION --profile default
  aws ec2 release-address --allocation-id $EIP --region $REGION --profile default
  aws ec2 wait volume-deleted --volume-ids $VOL_REVIEW --region $REGION --profile default
  ```

- [ ] 다시 조회하고 비교합니다 (`lab-audit-readonly`).

  ```sh
  uv run aws-lab-audit scan --region $REGION --project $PROJECT \
    --profile lab-audit-readonly --output reports/after.json; echo "exit=$?"
  uv run aws-lab-audit compare reports/before.json reports/after.json \
    > reports/compare.txt; echo "exit=$?"; cat reports/compare.txt
  ```

- [ ] 두 명령 모두 `exit=0`
- [ ] "이 태그 범위에서 더 이상 조회되지 않음"에 `$VOL_REVIEW`와 `$EIP`
- [ ] "변경 없음"에 `$VOL_KEEP`
- [ ] "새로 조회됨" 줄이 없음

## 5. 전체 정리와 마지막 조회

- [ ] Keep 볼륨까지 삭제합니다.

  ```sh
  aws ec2 delete-volume --volume-id $VOL_KEEP --region $REGION --profile default
  aws ec2 wait volume-deleted --volume-ids $VOL_KEEP --region $REGION --profile default
  uv run aws-lab-audit scan --region $REGION --project $PROJECT \
    --profile lab-audit-readonly --output reports/final.json; echo "exit=$?"
  ```

- [ ] `exit=0`, EBS와 Elastic IP 모두 "해당 Project 태그의 리소스 없음"
- [ ] 종료 시각을 적습니다. 이 시점 이후로는 비용이 발생하지 않습니다.

## 6. 증거 정리

`reports/`는 Git에서 제외되어 있습니다. 공개용 사본만 가려서 `docs/evidence/`로 복사합니다.

- [ ] 실행

  ```sh
  for f in before.json after.json final.json compare.txt; do
    sed -e "s/$ACCOUNT/123456789012/g" \
        -e "s/$VOL_REVIEW/vol-review-masked/g" \
        -e "s/$VOL_KEEP/vol-keep-masked/g" \
        -e "s/$EIP/eipalloc-review-masked/g" \
        reports/$f > docs/evidence/$f
  done
  grep -rE "$ACCOUNT|$VOL_REVIEW|$VOL_KEEP|$EIP" docs/evidence && echo "가리지 못한 값 있음" || echo "가림 확인"
  ```

- [ ] `가림 확인`이 출력됩니다.
- [ ] `uv run aws-lab-audit compare docs/evidence/before.json docs/evidence/after.json`이 가린 파일로도 같은 결과를 냅니다.
- [ ] 아래 기록을 채웁니다.

## 실행 기록

| 항목 | 값 |
| --- | --- |
| 실행 날짜 | |
| 시작 시각 / 종료 시각 | |
| 성공 기준 1–5 | |
| 예상과 다르게 나온 점 | |

## 중간에 멈췄을 때

남은 리소스가 있는지 확인하고 지웁니다. 이 문서에서 만든 리소스에는 모두 Project 태그가 있습니다.

```sh
uv run aws-lab-audit scan --region $REGION --project $PROJECT \
  --profile lab-audit-readonly --output reports/recovery-$(date +%H%M%S).json
```

보고서에 나온 볼륨은 `aws ec2 delete-volume`, Elastic IP는 `aws ec2 release-address`로 삭제합니다.

# 변경 기록

아직 버전 태그 전입니다. 날짜별로 정리합니다.

## 2026-11-28

### 추가

- 실계정 검증을 실행하고 계정 번호와 리소스 ID를 가린 증거를 [`docs/evidence/`](docs/evidence/)에 저장했습니다. 성공 기준 5개를 모두 충족했고, 테스트 리소스는 약 1분 동안만 존재했습니다. ([#1](https://github.com/yeopjoonhyun/aws-lab-audit/pull/1))
- README에 실계정 검증 요약을 추가했습니다. ([#1](https://github.com/yeopjoonhyun/aws-lab-audit/pull/1))
- GitHub Actions로 `main` 푸시와 PR마다 Python 3.11, 3.13에서 테스트를 실행합니다. 가린 증거로 비교 결과가 재현되는지도 확인합니다. README에 상태 배지를 추가했습니다. ([#2](https://github.com/yeopjoonhyun/aws-lab-audit/pull/2))

## 2026-11-27

### 추가

- `scan`, `compare` 명령으로 EBS 볼륨과 Elastic IP를 읽기 전용으로 조회하고 정리 전후를 비교합니다. 모의 AWS 테스트 7개와 샘플 보고서를 포함합니다.
- 실계정 검증 체크리스트 [`docs/real-account-check.md`](docs/real-account-check.md)를 추가했습니다. 조회용 프로필은 새 액세스 키 없이 Describe 권한 두 개만 가진 IAM 역할을 사용합니다.

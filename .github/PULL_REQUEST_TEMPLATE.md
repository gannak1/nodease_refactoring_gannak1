## 변경 사항
<!-- 이 PR에서 무엇을 변경했나요? -->


## 관련 이슈
<!-- 관련 이슈 번호를 입력해주세요. 예: Closes #123 -->
Closes #

## 변경 유형
- [ ] 버그 수정
- [ ] 새로운 기능
- [ ] 리팩토링
- [ ] 문서 수정
- [ ] 기타

## 테스트
- [ ] 로컬에서 테스트 완료
- [ ] 기존 테스트 통과 확인

## 보호 리소스·외부 실행 경계 (해당 시)
<!--
적용 대상: 보호 리소스/credential reference, user·team 권한, 상태 전이,
preflight와 runtime/background 재검증, secret·PII, 외부 provider/부수효과 변경.
비적용이면 사유만 적습니다. 적용 대상이면
docs/engineering/protected-resource-feature-completion.md와 테스트 매트릭스를 사용합니다.
아래 경계 중 해당 없는 항목은 매트릭스에 사유를 기록하고 체크하지 않습니다.
-->
- 적용 여부: [ ] 적용 [ ] 비적용
- 비적용 사유:
- 완결성 매트릭스 또는 검증 증거:
- [ ] 저장·GraphMutation과 secret 비저장
- [ ] 관리 API/UI와 user/team 권한 부여·회수
- [ ] Deployment preflight와 runtime/background 재검증
- [ ] Lifecycle·TOCTOU·idempotency/capability/lease·외부 adapter 미호출
- [ ] Audit·resource hiding·secret/PII redaction
- 미완료 항목 또는 후속 이슈:

## 스크린샷 (UI 변경 시)
<!-- UI 변경이 있다면 스크린샷을 첨부해주세요 -->

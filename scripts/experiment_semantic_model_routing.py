"""실제 배포 endpoint에서 Workflow-Aware Adaptive Routing을 검증한다.

threshold/min-margin 조정용 calibration 60개와 최종 평가용 holdout 60개를 분리한다.
``semantic-preflight``는 실제 embedding provider만 호출해 Route 분류를 점검하고,
``execute``는 holdout만 실제 배포 workflow와 LLM provider에 보내 예상/실제 cohort와
model을 보고서로 남긴다.
secret, credential 원문, embedding vector, raw trace payload는 출력하지 않는다.
"""

from __future__ import annotations

import argparse
import json
import os
import pathlib
import sys
import time
import uuid
from collections import Counter
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from types import SimpleNamespace
from typing import Any, Iterable


ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiments.model_routing.secret_input import (  # noqa: E402
    DEFAULT_WEBHOOK_SECRET_ENV,
    read_required_secret,
)

WORKFLOW_ID = "91000000-0000-0000-0000-000000000002"
DEPLOYMENT_ID = "91000000-0000-0000-0000-000000000003"
ORGANIZATION_ID = "10200000-0000-0000-0000-000000000100"
EXECUTION_USER_ID = "10200000-0000-0000-0000-000000000003"
NODE_ID = "llm-triage"
APP_SLUG = "demo-model-router-ticket-ops"

EVIDENCE_MODELS = {
    "routine_support": "gpt-4o-mini",
    "account_billing": "gpt-4.1-mini",
}


@dataclass(frozen=True)
class RoutingCase:
    case_id: str
    expected_cohort_id: str
    customer_tier: str
    message: str


@dataclass(frozen=True)
class RoutingObservation:
    case: RoutingCase
    run_id: str | None
    run_status: str
    expected_model_id: str
    actual_model_id: str | None
    actual_cohort_id: str | None
    match_status: str | None
    reason_code: str | None
    similarity: float | None
    threshold: float | None
    margin: float | None
    policy_version: str | None
    route_catalog_version: str | None
    candidate_cohort_id: str | None
    candidate_label: str | None
    semantic_decision_source: str | None = None
    lexical_score: float | None = None
    lexical_signal_count: int | None = None
    safety_override: bool = False


@dataclass(frozen=True)
class ReplayEvidenceObservation:
    case_id: str
    expected_cohort_id: str
    actual_cohort_id: str
    baseline_node_run_id: str
    baseline_model_id: str
    candidate_model_id: str
    candidate_id: str
    candidate_status: str
    schema_status: str | None
    downstream_state: str | None
    quality_status: str | None
    baseline_quality_score: float | None
    candidate_quality_score: float | None
    quality_confidence: str | None
    candidate_cost: float | None
    judge_cost: float | None


def _cases(
    dataset_prefix: str,
    cohort_id: str,
    customer_tier: str,
    messages: Iterable[str],
) -> list[RoutingCase]:
    prefix = {
        "routine_support": "R",
        "account_billing": "B",
        "high_risk": "H",
    }[cohort_id]
    return [
        RoutingCase(
            case_id=f"{dataset_prefix}-{prefix}{index:02d}",
            expected_cohort_id=cohort_id,
            customer_tier=customer_tier,
            message=message,
        )
        for index, message in enumerate(messages, start=1)
    ]


CALIBRATION_CASES = tuple(
    _cases(
        "C",
        "routine_support",
        "startup",
        [
            "알림 이메일을 다시 받으려면 어느 메뉴에서 설정해야 하나요?",
            "화면 언어를 한국어에서 영어로 바꾸는 위치를 알려 주세요.",
            "내보내기가 끝난 파일을 다운로드하는 화면을 찾고 있습니다.",
            "프로필 사진과 표시 이름을 수정하는 방법이 궁금합니다.",
            "비밀번호 초기화 메일이 만료됐는데 새 링크를 받을 수 있나요?",
            "날짜 표시 방식을 연도-월-일 순서로 바꾸고 싶습니다.",
            "워크스페이스 기본 시간대를 서울로 지정하는 절차를 알려 주세요.",
            "지난주에 만든 분석 보고서를 다시 내려받고 싶습니다.",
            "팀 초대 안내 메일을 동일한 사람에게 다시 보내는 메뉴가 어디인가요?",
            "대시보드 위젯 순서를 사용자가 원하는 대로 옮길 수 있나요?",
            "휴대전화 푸시 알림만 끄고 이메일 알림은 유지하고 싶습니다.",
            "CSV를 저장할 때 쉼표 대신 탭 구분자를 선택할 수 있나요?",
            "기존 워크플로우를 복제해서 새 이름으로 저장하는 방법을 알려 주세요.",
            "보관 처리한 모듈을 다시 찾을 수 있는 화면이 어디인가요?",
            "예약 실행 시간이 해외 시간으로 보여서 표시 기준을 바꾸고 싶습니다.",
            "API 사용 예제와 요청 형식이 정리된 문서 위치를 알려 주세요.",
            "자주 쓰는 응답 템플릿의 이름을 변경하려면 어떻게 하나요?",
            "프로젝트를 다른 폴더로 이동시키는 순서를 안내해 주세요.",
            "어두운 화면 모드를 켜는 설정이 있는지 궁금합니다.",
            "매주 발송되는 사용 현황 보고서를 구독하는 방법을 알려 주세요.",
        ],
    )
    + _cases(
        "C",
        "account_billing",
        "business",
        [
            "지난달 카드 결제액과 발행된 청구서 금액이 서로 다릅니다.",
            "같은 구독료가 이틀 연속 결제됐는데 중복 청구인지 확인해 주세요.",
            "상위 요금제로 변경했지만 계정의 사용 한도가 그대로입니다.",
            "결제 카드를 새 법인 카드로 교체하려는데 저장 단계에서 실패합니다.",
            "세금계산서에 등록된 사업자 번호를 수정해서 다시 발급받고 싶습니다.",
            "좌석을 줄였는데 다음 달 예상 청구액에 이전 인원이 반영돼 있습니다.",
            "무료 체험을 해지했는데 정식 구독 비용이 결제됐습니다.",
            "환불 승인 안내를 받았지만 아직 카드 취소 내역이 보이지 않습니다.",
            "연간 기업 계약의 갱신일과 다음 결제 예정 금액을 확인해 주세요.",
            "구매한 추가 크레딧이 소진 한도에 반영되지 않았습니다.",
            "해외 법인 청구서에 부가세가 포함된 이유를 확인하고 싶습니다.",
            "월별 청구서를 회계 담당자 이메일로도 보내도록 변경해 주세요.",
            "자동 결제가 실패한 뒤 유료 기능이 잠겼는데 복구 방법이 필요합니다.",
            "프로모션 코드를 입력했지만 할인 금액이 결제 화면에 적용되지 않습니다.",
            "구독 취소를 예약하면 실제 서비스 종료일이 언제인지 알려 주세요.",
            "월 중간에 요금제를 올렸을 때 일할 계산된 금액이 맞는지 궁금합니다.",
            "퇴사한 결제 관리자 대신 새 담당자에게 청구 권한을 이전하고 싶습니다.",
            "결제는 정상인데 조직의 유료 워크스페이스 접근 권한이 열리지 않았습니다.",
            "원화로 결제했는데 카드 명세서에는 달러 금액으로 표시됩니다.",
            "이번 달 초과 사용량에 따른 추가 과금 계산 기준을 설명해 주세요.",
        ],
    )
    + _cases(
        "C",
        "high_risk",
        "enterprise",
        [
            "핵심 결제 서비스가 장시간 중단되어 SLA 위반과 고객 보상 검토가 필요합니다.",
            "운영 API 키가 외부 저장소에 노출된 정황이 있어 즉시 폐기해야 합니다.",
            "고객 개인정보가 권한 없는 직원 화면에 표시됐다는 신고가 접수됐습니다.",
            "관리자 계정이 탈취된 것 같고 여러 사용자의 권한이 변경돼 있습니다.",
            "전 지역 사용자가 접속하지 못하는 전체 장애가 발생해 긴급 대응이 필요합니다.",
            "결제 API 오류로 다수 고객에게 금액이 두 번 청구됐습니다.",
            "법적 보존 의무가 있는 고객 데이터의 긴급 삭제 요청이 들어왔습니다.",
            "운영 서버에서 랜섬웨어 의심 파일이 발견되어 서비스 격리를 검토 중입니다.",
            "일반 사용자 계정이 관리자 전용 정보에 접근한 기록을 발견했습니다.",
            "감사 로그 일부가 삭제되거나 변경된 정황이 있어 보안 조사가 필요합니다.",
            "유럽 고객 데이터가 승인 없이 다른 지역으로 전송됐을 가능성이 있습니다.",
            "SSO 인증을 우회해 퇴사자 계정으로 로그인한 흔적이 발견됐습니다.",
            "외부에서 위조한 웹훅이 운영 주문을 대량으로 변경한 것으로 보입니다.",
            "배포 직후 운영 데이터가 손상되어 복구와 고객 공지가 필요한 상황입니다.",
            "인증 장애로 기업 고객 직원 수천 명이 동시에 계정 잠금 상태가 됐습니다.",
            "백업 복원 작업이 실패해 재해 복구 목표 시간을 넘길 가능성이 큽니다.",
            "보안 사고 이후에도 유출된 자격 증명이 계속 사용되는 정황이 있습니다.",
            "규제 기관에 사고를 보고해야 하는 기한이 임박했는데 영향 범위가 불명확합니다.",
            "기업 계약의 응답 시간 약속을 반복 위반해 크레딧 보상 승인이 필요합니다.",
            "고객 문서가 공개 링크로 노출되어 누구나 내려받을 수 있는 상태입니다.",
        ],
    )
)


HOLDOUT_CASES = tuple(
    _cases(
        "H",
        "routine_support",
        "startup",
        [
            "왼쪽 메뉴를 접은 뒤 다시 펼치는 방법을 찾고 있어요.",
            "워크플로우 이름 옆에 별표를 붙여 즐겨찾기로 관리할 수 있나요?",
            "작성 중인 모듈을 사본으로 하나 더 만드는 절차를 안내해 주세요.",
            "브라우저 알림만 잠시 멈추고 나중에 다시 켜고 싶습니다.",
            "완료된 실행 기록을 PDF로 저장하는 버튼이 어느 화면에 있나요?",
            "자주 보는 프로젝트가 목록 맨 위에 오도록 정렬하고 싶어요.",
            "새 구성원이 참고할 수 있는 시작 안내서를 어디에서 볼 수 있나요?",
            "계정 화면에 보이는 닉네임을 회사에서 쓰는 이름으로 바꾸고 싶습니다.",
            "아침마다 오는 요약 메일의 발송 시간을 오후로 옮길 수 있나요?",
            "작업 화면의 글자 크기를 키울 수 있는 설정 위치를 알려 주세요.",
            "삭제하지 않고 숨겨 둔 워크플로우를 다시 목록에 표시하고 싶어요.",
            "여러 대시보드 중 하나를 첫 화면으로 지정하는 방법이 궁금합니다.",
            "완료 알림 소리는 끄고 화면 알림만 남길 수 있나요?",
            "내 활동 기록을 파일로 내려받는 순서를 알려 주세요.",
            "새 폴더를 만든 뒤 기존 모듈을 그 안으로 옮기고 싶습니다.",
            "저장된 필터 조건을 다른 팀원과 공유하는 방법이 있나요?",
            "반복 실행 일정을 매주 월요일 오전으로 수정하고 싶어요.",
            "목록에서 보이는 설명 열을 숨기는 화면 설정을 찾고 있습니다.",
            "웹훅 예제 payload를 확인할 수 있는 개발자 안내 페이지가 어디인가요?",
            "최근 열어본 항목 기록을 지우는 메뉴를 알려 주세요.",
        ],
    )
    + _cases(
        "H",
        "account_billing",
        "business",
        [
            "청구서 결제 예정일이 계약서에 적힌 날짜와 다르게 표시됩니다.",
            "회사 카드가 만료되어 다음 정기 결제 전에 새 카드로 바꾸고 싶습니다.",
            "사용하지 않은 좌석까지 요금에 포함된 것 같아 산정 내역을 확인해 주세요.",
            "요금제를 낮췄는데 다음 결제 예상액이 줄어들지 않았습니다.",
            "결제 영수증의 회사명이 이전 법인명으로 발급됐습니다.",
            "잔여 크레딧이 있는데도 추가 사용료가 청구된 이유가 궁금합니다.",
            "카드 승인은 취소됐는데 서비스 화면에는 결제 실패로 계속 표시됩니다.",
            "계약 갱신 전에 월간 결제에서 연간 결제로 전환하고 싶어요.",
            "세금 서류를 받을 담당 메일 주소를 두 개 등록할 수 있나요?",
            "체험 기간 중 취소했는데 소액 승인 금액이 카드에서 빠져나갔습니다.",
            "결제 통화를 달러에서 원화로 변경했을 때 적용 시점을 알고 싶습니다.",
            "부서별 사용 금액을 나눈 상세 명세서를 발급받을 수 있나요?",
            "계정에 표시된 다음 갱신 가격이 영업 담당자가 안내한 금액과 다릅니다.",
            "새로 추가한 사용자 한 명의 좌석 비용이 두 명분으로 계산됐습니다.",
            "구독을 일시 중지하는 동안에도 기본 요금이 발생하는지 확인해 주세요.",
            "환불 처리 번호는 받았지만 환급 예정일을 확인할 수 없습니다.",
            "법인 주소가 바뀌어서 이번 분기 청구 문서를 모두 정정해야 합니다.",
            "결제 권한을 가진 관리자가 퇴사해 새 책임자를 지정하려고 합니다.",
            "예산 한도를 넘지 않았는데 결제 제한 안내가 나타납니다.",
            "할인 계약이 갱신 청구서에 반영되지 않아 금액 검토가 필요합니다.",
        ],
    )
    + _cases(
        "H",
        "high_risk",
        "enterprise",
        [
            "다른 회사의 고객 목록이 우리 조직 화면에 노출되어 즉시 차단이 필요합니다.",
            "운영 데이터베이스 계정이 유출된 정황이 있어 모든 접근을 긴급 회수해야 합니다.",
            "대규모 장애가 복구 목표 시간을 넘겨 계약상 보상 절차를 시작해야 합니다.",
            "알 수 없는 관리자가 새 최고 권한 계정을 여러 개 생성했습니다.",
            "악성 코드가 운영 서버에서 외부로 고객 파일을 전송한 흔적이 있습니다.",
            "공격자가 인증 절차를 건너뛰고 관리자 API를 호출한 기록을 발견했습니다.",
            "전체 고객의 결제가 반복 처리되어 금전 피해와 긴급 공지가 예상됩니다.",
            "개인정보 삭제 요청이 법적 보존 명령과 충돌해 법무 판단이 필요합니다.",
            "보안 감사 증적의 시간과 작성자가 조작된 것으로 보여 무결성 검사가 필요합니다.",
            "해외 리전에 민감 정보가 무단 복제되어 규제 신고 여부를 판단해야 합니다.",
            "SSO 인증서가 탈취된 가능성이 있어 전사 로그인을 즉시 중단해야 합니다.",
            "백업 암호화 키를 잃어 재해 복구가 불가능할 수 있는 긴급 상황입니다.",
            "고객 전용 문서 저장소가 인터넷 검색 결과에 노출됐다는 제보가 들어왔습니다.",
            "수천 개 계정을 대상으로 비밀번호 대입 공격이 진행 중입니다.",
            "운영 주문 금액이 일괄 변조되어 거래를 중지하고 사고 조사를 해야 합니다.",
            "핵심 API가 장시간 응답하지 않아 여러 기업의 SLA 위반이 확정될 상황입니다.",
            "퇴사자의 장기 토큰으로 생산 환경 설정이 변경된 기록이 남아 있습니다.",
            "고객 암호화 키가 공개 채널에 게시되어 데이터 노출 가능성을 조사해야 합니다.",
            "배포 패키지에서 공급망 공격이 의심되는 실행 파일을 발견했습니다.",
            "사고 통지 법정 기한이 오늘인데 피해 고객 범위가 아직 확인되지 않았습니다.",
        ],
    )
)

# threshold 보정, 1차 holdout 점검, Replay evidence에 한 번도 쓰지 않은
# 최종 배포 평가 입력이다. 최종 성능을 본 뒤 이 문장으로 Route를 다시 조정하지 않는다.
FINAL_HOLDOUT_V1_CASES = tuple(
    _cases(
        "F",
        "routine_support",
        "startup",
        [
            "편집 화면에서 미니맵을 감추는 설정이 어디에 있는지 알려 주세요.",
            "실행 결과 목록을 생성일이 오래된 순서로 정렬하고 싶어요.",
            "매일 받는 활동 요약을 주말에는 보내지 않도록 설정할 수 있나요?",
            "복사한 워크플로우의 설명만 수정하려면 어느 메뉴로 들어가야 하나요?",
            "저장해 둔 검색 조건을 삭제하는 방법을 찾고 있습니다.",
            "프로젝트 목록에서 썸네일 대신 간단한 목록 보기로 바꾸고 싶습니다.",
            "내 계정의 기본 표시 언어를 일본어로 선택할 수 있나요?",
            "실행 완료 알림을 특정 워크플로우에서만 끄는 방법을 알려 주세요.",
            "예전에 닫아 둔 대시보드 탭을 다시 열 수 있는 위치가 궁금합니다.",
            "팀원이 만든 모듈을 내 즐겨찾기에 추가하는 절차를 안내해 주세요.",
            "개발자 문서에서 webhook 응답 예제를 어디서 찾을 수 있나요?",
            "보고서 파일 이름에 실행 날짜가 자동으로 붙도록 설정할 수 있나요?",
            "워크스페이스 첫 화면에 표시되는 안내 문구를 닫고 싶습니다.",
            "프로필의 연락처 번호를 새 번호로 변경하는 순서를 알려 주세요.",
            "임시 보관한 초안을 원래 프로젝트로 복원하려면 어떻게 해야 하나요?",
            "같은 조건의 예약 작업을 다음 달에도 반복하도록 수정하고 싶어요.",
            "표에서 한 페이지에 보이는 항목 수를 늘리는 설정이 있나요?",
            "새 멤버에게 제품 사용 가이드를 다시 보내는 버튼을 찾고 있습니다.",
            "작성 화면에서 접어 둔 속성 패널을 다시 표시하는 방법이 궁금합니다.",
            "개인 설정을 초기값으로 되돌리되 저장된 모듈은 유지하고 싶습니다.",
        ],
    )
    + _cases(
        "F",
        "account_billing",
        "business",
        [
            "이번 청구서에 계약하지 않은 부가 기능 요금이 포함되어 있습니다.",
            "결제 담당자를 바꿨는데 승인 요청이 이전 담당자에게 전송됩니다.",
            "선불로 구매한 사용량이 월별 한도에서 차감되지 않은 것 같습니다.",
            "분기 결제로 합의했는데 결제 화면에는 매월 청구로 표시됩니다.",
            "해지한 추가 워크스페이스의 요금이 다음 달 견적에 남아 있습니다.",
            "카드 결제 실패 후 계좌 이체로 납부할 수 있는지 확인해 주세요.",
            "영수증에 표시된 결제일과 실제 카드 승인일이 하루 차이 납니다.",
            "회사 합병으로 사업자 정보가 바뀌어 청구 계정을 이전해야 합니다.",
            "구독 갱신 직전에 인원을 줄이면 어느 달부터 금액이 조정되나요?",
            "교육 기관 할인 승인을 받았지만 정가로 결제될 예정이라고 나옵니다.",
            "미납 금액을 납부했는데도 유료 기능 제한이 해제되지 않았습니다.",
            "추가 저장 공간을 취소했을 때 남은 기간의 금액을 돌려받을 수 있나요?",
            "두 조직의 결제 내역을 하나의 통합 청구서로 받을 수 있는지 궁금합니다.",
            "결제 페이지에 표시된 세율이 우리 회사 소재지 기준과 맞지 않습니다.",
            "자동 갱신을 껐지만 다음 결제 예약이 여전히 활성 상태로 보입니다.",
            "구매 주문서 번호를 이번 달 청구서에 추가해 다시 발급해 주세요.",
            "예치금 잔액보다 적게 사용했는데 카드에 별도 금액이 승인됐습니다.",
            "환불 금액에서 수수료가 제외된 산정 근거를 확인하고 싶습니다.",
            "부서 하나를 분리하면서 해당 좌석과 결제 내역도 새 조직으로 옮기려 합니다.",
            "연간 선납 계약을 중도 변경할 때 남은 금액이 어떻게 계산되는지 알려 주세요.",
        ],
    )
    + _cases(
        "F",
        "high_risk",
        "enterprise",
        [
            "외부인이 고객 관리자 권한으로 접속한 흔적이 있어 계정을 즉시 봉쇄해야 합니다.",
            "생산 환경의 비밀 키가 공개 이슈에 첨부되어 전면 교체가 필요합니다.",
            "결제 원장이 손상되어 고객 잔액이 잘못 표시되는 중대한 사고가 발생했습니다.",
            "고객 파일 일부가 경쟁사 조직에서 조회된다는 신고를 받았습니다.",
            "서비스 중단이 계약 보장 시간을 초과해 손해배상 검토가 시작됐습니다.",
            "감염된 관리자 PC에서 운영 자격 증명이 사용된 기록이 확인됐습니다.",
            "삭제돼야 할 개인정보가 백업에서 복원되어 규제 위반 가능성이 있습니다.",
            "서명되지 않은 배포 파일이 운영 서버 여러 대에 설치된 상태입니다.",
            "권한 변경 감사 기록과 실제 데이터가 달라 내부자 조사가 필요합니다.",
            "고객 암호화 자료를 해독할 수 있는 키가 분실되어 긴급 대응 중입니다.",
            "접속 장애가 전 세계 리전에 확산되어 복구 예상 시간을 제시할 수 없습니다.",
            "인증 우회 취약점이 실제 공격에 사용되어 관리자 기능이 노출됐습니다.",
            "법원 보존 명령 대상 자료가 자동 정리 작업으로 삭제된 정황이 있습니다.",
            "퇴사자 계정이 대량의 고객 정보를 내려받은 기록을 발견했습니다.",
            "공격자가 결제 환불 계좌를 바꿔 금전 피해가 발생했을 가능성이 큽니다.",
            "재해 복구 센터까지 동시에 장애가 나 서비스 복원 계획이 실패했습니다.",
            "공개 저장소에 올라간 데이터베이스 백업을 누구나 내려받을 수 있습니다.",
            "규제 신고 마감 전까지 유출 대상자를 확정하지 못할 위험이 있습니다.",
            "관리자 승인 없이 보안 정책이 완화되어 모든 세션을 폐기해야 합니다.",
            "기업 고객의 핵심 업무가 멈춰 긴급 크레딧 보상과 공식 공지가 필요합니다.",
        ],
    )
)

# v1 결과로 안전 margin을 보정한 뒤 사용한 두 번째 평가셋이다. Hybrid safety
# override 설계의 진단 자료로만 남기고 최종 성능 보고에는 사용하지 않는다.
FINAL_HOLDOUT_V2_CASES = tuple(
    _cases(
        "G",
        "routine_support",
        "startup",
        [
            "캔버스 격자선을 잠시 숨기려면 어떤 보기 옵션을 눌러야 하나요?",
            "최근 실행한 자동화만 모아서 보는 필터를 저장하고 싶습니다.",
            "업로드한 파일의 이름을 바꾸는 기능이 어느 화면에 있나요?",
            "초대받은 프로젝트를 내 홈 화면에 고정하는 방법을 알려 주세요.",
            "완료된 작업의 상세 패널을 기본으로 접힌 상태로 둘 수 있나요?",
            "계정에서 사용하는 날짜와 숫자 표기 형식을 변경하고 싶어요.",
            "매달 생성되는 보고서의 저장 폴더를 다른 곳으로 지정하려 합니다.",
            "알림 센터에서 읽은 항목을 한꺼번에 지우는 버튼을 찾고 있습니다.",
            "워크플로우 설명에 링크를 추가하는 작성 방법이 궁금합니다.",
            "내가 만든 템플릿만 보이도록 목록을 거르는 기능이 있나요?",
            "실수로 닫은 실행 결과 창을 다시 여는 순서를 안내해 주세요.",
            "사이드바 항목의 표시 순서를 직접 바꿀 수 있는지 알려 주세요.",
            "팀 공용 폴더 안에서 새 하위 폴더를 만드는 방법이 필요합니다.",
            "로그인 알림 메일의 수신 여부를 개인 설정에서 바꾸고 싶습니다.",
            "저장 버튼을 누르기 전 변경 내용을 취소하는 기능은 어디에 있나요?",
            "목록을 카드 보기에서 표 보기로 전환하는 메뉴를 알려 주세요.",
            "모듈 실행 예제를 따라 할 수 있는 튜토리얼 페이지를 찾고 있어요.",
            "예약된 실행의 이름과 메모를 수정하려면 어떻게 해야 하나요?",
            "사용하지 않는 태그를 삭제하되 연결된 모듈은 남기고 싶습니다.",
            "브라우저를 바꿔도 개인 화면 설정을 그대로 유지할 수 있나요?",
        ],
    )
    + _cases(
        "G",
        "account_billing",
        "business",
        [
            "새 법인 카드 등록은 됐지만 기본 결제 수단으로 선택되지 않습니다.",
            "청구서에 추가된 좌석 수가 실제 활성 사용자 수보다 많습니다.",
            "월간 구독을 연간으로 바꿀 때 기존 결제액이 어떻게 정산되나요?",
            "세금계산서의 공급받는 자 주소를 수정해 재발행하고 싶습니다.",
            "프로모션 종료일 전에 갱신됐는데 할인 가격이 적용되지 않았습니다.",
            "결제 승인은 났지만 인보이스 상태가 계속 미납으로 남아 있습니다.",
            "사용 크레딧의 충전 내역과 차감 내역을 월별로 확인하고 싶어요.",
            "조직을 하나 삭제했는데 해당 조직의 구독이 계속 유지되고 있습니다.",
            "다음 갱신부터 결제 주기를 분기 단위로 변경할 수 있나요?",
            "회계팀이 받을 영수증 이메일 주소를 새 주소로 교체해 주세요.",
            "해외 카드 수수료가 청구 금액에 포함됐는지 구분해서 보고 싶습니다.",
            "좌석 추가 비용이 계약서의 단가와 다르게 계산된 이유를 알려 주세요.",
            "구독 해지 후 남은 크레딧을 다른 조직으로 이전할 수 있나요?",
            "환불 접수는 완료됐는데 처리 상태를 확인할 번호가 보이지 않습니다.",
            "결제 한도를 높였지만 추가 사용 승인 요청이 계속 차단됩니다.",
            "지난 분기 청구 문서를 비용 센터별로 나누어 다시 받을 수 있나요?",
            "은행 이체로 납부한 금액이 계정 잔액에 아직 반영되지 않았습니다.",
            "자동 갱신 날짜를 회사 회계 마감일 뒤로 변경하고 싶습니다.",
            "구매 담당자만 요금제 변경을 승인하도록 권한을 설정할 수 있나요?",
            "계약 기간 중 자회사를 추가하면 청구 금액이 어떻게 합산되는지 궁금합니다.",
        ],
    )
    + _cases(
        "G",
        "high_risk",
        "enterprise",
        [
            "정상 직원이 아닌 계정이 운영 시스템의 최고 관리자 권한을 획득했습니다.",
            "고객 데이터가 담긴 저장소의 접근 토큰이 외부 게시판에 공개됐습니다.",
            "결제 내역이 대량으로 변조되어 실제 청구액과 원장이 일치하지 않습니다.",
            "전체 리전 장애로 계약상 가동률을 지키지 못할 가능성이 확정적입니다.",
            "악성 프로그램이 고객 문서를 외부 서버로 전송한 증거를 발견했습니다.",
            "공격자가 환불 승인 권한을 탈취해 여러 건의 금액을 빼돌렸습니다.",
            "보존 의무가 있는 감사 자료가 삭제되어 규제 대응이 어려운 상황입니다.",
            "암호화 키가 노출되어 저장된 개인정보를 다시 암호화해야 합니다.",
            "인증 시스템 장애로 모든 기업 사용자가 업무를 시작하지 못하고 있습니다.",
            "고객별로 분리돼야 할 문서가 다른 조직 검색 결과에 나타납니다.",
            "운영 배포에 포함된 라이브러리에서 공급망 침해 흔적이 확인됐습니다.",
            "퇴사자가 남긴 토큰으로 보안 설정을 해제한 기록이 있습니다.",
            "법정 사고 통지 시간이 얼마 남지 않았지만 유출 범위를 모릅니다.",
            "백업과 주 서버가 동시에 손상되어 복구 목표를 달성하기 어렵습니다.",
            "결제 장애가 장시간 계속돼 다수 기업에 서비스 크레딧을 제공해야 합니다.",
            "공개 URL을 통해 인증 없이 고객 계약서를 다운로드할 수 있습니다.",
            "관리자 API의 권한 검사가 우회되어 민감 설정이 변경됐습니다.",
            "보안 로그의 시간 정보가 조작돼 사고 경로를 신뢰할 수 없습니다.",
            "랜섬웨어 공격으로 생산 데이터가 잠겨 즉시 시스템 격리가 필요합니다.",
            "해외 지역으로 민감 정보가 무단 이전되어 법무와 규제 검토가 필요합니다.",
        ],
    )
)

# Dense-only v1/v2 결과를 본 뒤 hybrid safety override를 고정하고 작성한 세 번째
# 미사용 평가셋이다. 아래 입력을 실행한 뒤 signal이나 threshold를 다시 맞추면 새
# 버전과 새 평가셋으로 분리해야 한다.
FINAL_HOLDOUT_CASES = tuple(
    _cases(
        "H",
        "routine_support",
        "startup",
        [
            "캔버스 확대 비율을 키보드로 초기화하는 방법을 알려 주세요.",
            "실행 기록에서 성공한 항목만 보이도록 저장 필터를 만들고 싶습니다.",
            "복제한 모듈의 아이콘과 표시 이름을 바꾸는 위치가 궁금합니다.",
            "주간 요약 메일을 월요일 아침 대신 화요일 오후에 받으려 합니다.",
            "워크플로우 목록을 마지막으로 연 순서대로 정렬할 수 있나요?",
            "사용하지 않는 개인 템플릿을 보관함으로 옮기는 절차를 안내해 주세요.",
            "편집 화면에서 노드 설명을 항상 펼쳐 두는 보기 옵션이 있나요?",
            "내 프로필에 표시되는 부서명과 직책을 수정하고 싶습니다.",
            "CSV로 내보낼 때 화면에 보이는 열만 포함하는 방법이 궁금합니다.",
            "예약 실행의 시간대를 서울 기준으로 변경하려면 어디를 눌러야 하나요?",
            "최근 사용한 지식 베이스 목록을 홈에서 숨길 수 있나요?",
            "실행 결과의 긴 텍스트를 줄바꿈해서 보는 설정을 찾고 있습니다.",
            "다른 팀이 공유한 워크플로우를 내 작업 목록에 바로가기만 추가하고 싶습니다.",
            "완료된 알림을 모두 읽음으로 표시하는 기능은 어느 메뉴에 있나요?",
            "워크플로우 편집 중 마지막 저장 시각을 확인하는 위치를 알려 주세요.",
            "노드 검색창에서 유형별로 결과를 좁히는 방법이 궁금합니다.",
            "보고서 다운로드 파일 형식을 PDF에서 CSV로 바꾸고 싶습니다.",
            "대시보드에서 사용하지 않는 위젯만 제거하는 순서를 안내해 주세요.",
            "브라우저 알림은 끄고 이메일 알림만 유지할 수 있나요?",
            "공유받은 실행 결과에 개인 메모를 남기는 기능이 있는지 알려 주세요.",
        ],
    )
    + _cases(
        "H",
        "account_billing",
        "business",
        [
            "이번 달 인보이스에 반영된 사용자 수의 계산 기준을 확인해 주세요.",
            "연간 요금제로 전환했는데 월간 결제 예약이 아직 남아 있습니다.",
            "법인 카드 만료일을 갱신했지만 다음 납부 수단에 반영되지 않았습니다.",
            "추가한 좌석 세 개의 일할 계산 금액이 예상보다 높게 나왔습니다.",
            "세금계산서 발행일을 회사 결산 일정에 맞춰 조정할 수 있나요?",
            "환불 신청 건의 예상 입금일과 처리 단계를 확인하고 싶습니다.",
            "선불 크레딧을 구매했는데 사용 가능 잔액이 그대로입니다.",
            "계약 갱신 견적서에 협의한 기업 할인율이 빠져 있습니다.",
            "결제 담당자 이메일을 바꾼 뒤 청구 알림이 오지 않습니다.",
            "두 부서의 사용료를 서로 다른 비용 센터로 나누어 청구하고 싶습니다.",
            "구독 종료일 이후에도 다음 달 요금이 예상 금액에 잡혀 있습니다.",
            "은행 송금 영수증을 제출했는데 계정 상태가 미납으로 표시됩니다.",
            "구매 주문서 번호가 누락된 청구 문서를 다시 발급해 주세요.",
            "좌석을 줄인 날짜와 실제 요금 조정 시작일이 다른 이유가 궁금합니다.",
            "해외 지사의 청구 통화를 원화에서 달러로 변경할 수 있나요?",
            "교육용 할인 기간이 끝난 뒤 적용될 단가를 미리 확인하고 싶습니다.",
            "결제 수단을 계좌 이체로 바꾸면 자동 납부일도 유지되나요?",
            "지난달 초과 사용량이 어느 워크스페이스에서 발생했는지 알려 주세요.",
            "분리된 자회사의 기존 크레딧을 새 청구 계정으로 옮기고 싶습니다.",
            "영수증 수신자를 추가했지만 기존 담당자만 메일을 받고 있습니다.",
        ],
    )
    + _cases(
        "H",
        "high_risk",
        "enterprise",
        [
            "운영 콘솔에서 무단 접근 기록이 발견되어 모든 관리자 세션을 종료해야 합니다.",
            "API 키 유출 정황으로 고객 연동 자격 증명을 즉시 교체해야 합니다.",
            "결제 원장 손상 때문에 고객 잔액이 실제 거래와 다르게 계산되고 있습니다.",
            "전 지역 서비스 중단으로 기업 고객의 핵심 업무가 멈춘 상태입니다.",
            "청구 승인 기록이 변조되어 정상 거래와 비정상 거래를 구분할 수 없습니다.",
            "공격자가 계정 탈취 후 환불 계좌를 변경한 흔적이 확인됐습니다.",
            "민감 정보가 허용되지 않은 국가로 이동해 규제 위반 검토가 필요합니다.",
            "인증 우회 취약점으로 일반 사용자가 관리자 설정을 열 수 있습니다.",
            "고객 계약서가 외부 공개 링크에서 검색되는 상황을 즉시 차단해 주세요.",
            "랜섬웨어 감염으로 생산 파일이 잠겨 서버 격리와 복구가 필요합니다.",
            "공격자가 운영 배포 파일을 위조해 여러 서버에 설치했습니다.",
            "개인정보 유출 신고가 접수되어 영향 고객과 노출 범위를 확인해야 합니다.",
            "장시간 장애로 SLA 위반이 확정되어 공식 보상 절차를 시작해야 합니다.",
            "감사 로그 삭제 흔적 때문에 사고 발생 시점과 행위자를 확인할 수 없습니다.",
            "비밀 키 노출로 암호화된 고객 자료의 안전성을 더 이상 보장할 수 없습니다.",
            "권한 상승 공격이 성공해 제한된 계정이 최고 관리자 기능을 실행했습니다.",
            "위조된 웹훅 요청이 고객 주문 상태를 대량으로 변경했습니다.",
            "데이터베이스 백업이 공개 저장소에 올라가 누구나 내려받을 수 있습니다.",
            "환불 시스템 침해로 실제 금전 피해가 발생했을 가능성이 큽니다.",
            "승인되지 않은 관리자가 여러 조직의 고객 파일을 열람한 정황이 있습니다.",
        ],
    )
)

# 후보 품질 증거를 만드는 입력은 threshold 보정 및 최종 평가 입력과 분리한다.
EVIDENCE_CASES = tuple(
    _cases(
        "E",
        "routine_support",
        "startup",
        [
            "완료한 자동화의 이름을 바꾸는 메뉴 위치를 알려 주세요.",
            "주간 실행 요약 메일을 금요일 오후에 받도록 설정하고 싶습니다.",
            "목록에서 최근 수정한 모듈이 먼저 보이도록 정렬하는 방법이 궁금합니다.",
            "화면 테마를 밝은 모드로 변경하는 메뉴를 알려 주세요.",
            "보관한 프로젝트를 다시 활성 목록으로 돌리는 절차를 안내해 주세요.",
        ],
    )
    + _cases(
        "E",
        "account_billing",
        "business",
        [
            "다음 달 청구서에 해지한 좌석 비용이 포함되어 있어 확인이 필요합니다.",
            "법인 카드 변경은 완료됐지만 결제 수단 화면에는 이전 카드가 보입니다.",
            "환불 완료 메일을 받았는데 계정 크레딧 잔액이 복원되지 않았습니다.",
            "연간 계약 할인율이 이번 갱신 견적에 적용되지 않은 것 같습니다.",
            "세금계산서 수신 담당자를 변경했지만 이전 담당자에게 계속 발송됩니다.",
        ],
    )
)

# 기존 호출부 호환용 별칭이다. 새 실험 코드는 dataset을 명시해서 사용한다.
ROUTING_CASES = HOLDOUT_CASES


def _expected_model_for_cohort(
    active_policy: dict[str, Any],
    cohort_id: str,
) -> str:
    """기대 cohort가 정확히 매칭됐을 때 frozen policy가 고를 모델을 계산한다."""
    for rule in active_policy.get("rules") or []:
        if not isinstance(rule, dict):
            continue
        when = rule.get("when")
        if not isinstance(when, dict):
            continue
        if set(when) != {"semantic_cohort_id"}:
            continue
        if str(when.get("semantic_cohort_id") or "") != cohort_id:
            continue
        selected_model_id = str(rule.get("selected_model_id") or "").strip()
        if selected_model_id:
            return selected_model_id
    default_model_id = str(active_policy.get("default_model_id") or "").strip()
    if not default_model_id:
        raise RuntimeError("활성 policy에 default_model_id가 없습니다.")
    return default_model_id


def build_runtime_inputs(case: RoutingCase) -> dict[str, Any]:
    """실제 webhook trigger가 LLM node에 전달하는 upstream object를 재현한다."""
    return {
        "webhook-ticket": {
            "message": case.message,
            "customerTier": case.customer_tier,
        }
    }


def _candidate_request_from_node(
    node_data: dict[str, Any],
    *,
    candidate_model_id: str,
    label: str,
) -> dict[str, Any]:
    """배포 node 계약은 보존하고 자동 라우팅 없이 exact 후보 모델만 실행한다."""
    knowledge_base_ids = [
        str(item.get("id")).strip()
        for item in node_data.get("knowledgeBases") or []
        if isinstance(item, dict) and str(item.get("id") or "").strip()
    ]
    knowledge: dict[str, Any] = {"knowledge_base_ids": knowledge_base_ids}
    knowledge_fields = {
        "topK": "top_k",
        "scoreThreshold": "score_threshold",
        "dedupeRetrievedContext": "dedupe_retrieved_context",
        "retrievedContextMaxChars": "retrieved_context_max_chars",
        "retrievedContextCompression": "retrieved_context_compression",
        "answerGroundingCheck": "answer_grounding_check",
    }
    for node_key, request_key in knowledge_fields.items():
        if node_key in node_data:
            knowledge[request_key] = node_data[node_key]

    output_format = node_data.get("output_format")
    if isinstance(output_format, str):
        output_format = {"type": output_format}
    elif not isinstance(output_format, dict):
        output_format = {"type": "text"}

    return {
        "label": label,
        "model_id": candidate_model_id,
        "fallback_model_id": None,
        "auto_model_routing": False,
        "model_routing_policy": None,
        "task_type": node_data.get("task_type") or "generate",
        "system_prompt": node_data.get("system_prompt") or None,
        "user_prompt": node_data.get("user_prompt") or None,
        "assistant_prompt": node_data.get("assistant_prompt") or None,
        "referenced_variables": node_data.get("referenced_variables") or [],
        "parameters": dict(node_data.get("parameters") or {}),
        "output_format": dict(output_format),
        "knowledge": knowledge,
    }


def _human_reason(observation: RoutingObservation) -> str:
    if observation.semantic_decision_source == "safety_override":
        count = observation.lexical_signal_count or 0
        count_text = f" {count}개" if count > 0 else ""
        return (
            f"정책의 안전 조건{count_text}와 일치해 비용 절감보다 사고 대응 품질을 "
            "우선하고 기본 고성능 모델을 사용함"
        )
    if observation.reason_code == "validated_quality_floor_cost_reduction":
        return "이 입력군에서 품질 기준을 통과했고 비용 절감이 검증된 모델 규칙이 일치함"
    if observation.reason_code == "semantic_matched_no_rule_default":
        return "입력군은 구분했지만 검증된 모델 규칙이 아직 없어 기본 모델을 유지함"
    if observation.reason_code == "semantic_no_match_default":
        if (
            observation.candidate_label
            and observation.similarity is not None
            and observation.threshold is not None
        ):
            return (
                f"가장 가까운 유형은 {observation.candidate_label}였지만 "
                f"유사도 {_format_similarity(observation.similarity)}가 선택 기준 "
                f"{_format_similarity(observation.threshold)}에 미달해 기본 모델을 사용함"
            )
        return "어느 입력군에도 충분히 가깝지 않아 안전하게 기본 모델을 사용함"
    if observation.reason_code == "semantic_ambiguous_default":
        if observation.candidate_label:
            return (
                f"가장 가까운 유형은 {observation.candidate_label}였지만 "
                "2위와 점수 차이가 작아 기본 모델을 사용함"
            )
        return "두 입력군의 점수가 비슷해 안전하게 기본 모델을 사용함"
    if observation.reason_code == "semantic_unavailable_default":
        return "의미 분류를 사용할 수 없어 기본 모델을 사용함"
    return observation.reason_code or "선정 근거 없음"


def _pct(numerator: int, denominator: int) -> float:
    return round((numerator / denominator) * 100, 1) if denominator else 0.0


def _format_similarity(value: float) -> str:
    return f"{round(value * 100, 1):g}%"


def build_markdown_report(observations: Iterable[RoutingObservation]) -> str:
    rows = list(observations)
    cohort_hits = sum(
        row.actual_cohort_id == row.case.expected_cohort_id for row in rows
    )
    model_hits = sum(row.actual_model_id == row.expected_model_id for row in rows)
    high_risk = [row for row in rows if row.case.expected_cohort_id == "high_risk"]
    high_risk_hits = sum(row.actual_cohort_id == "high_risk" for row in high_risk)
    trace_complete = sum(
        bool(
            row.reason_code
            and row.policy_version
            and row.route_catalog_version
            and row.match_status
        )
        for row in rows
    )

    lines = [
        "# Workflow-Aware 모델 라우팅 60개 실배포 검증",
        "",
        f"- 실행 시각: {datetime.now(timezone.utc).isoformat()}",
        f"- 전체 입력: {len(rows)}개",
        f"- 입력군 정확도: {_pct(cohort_hits, len(rows))}% ({cohort_hits}/{len(rows)})",
        f"- 모델 선택 정확도: {_pct(model_hits, len(rows))}% ({model_hits}/{len(rows)})",
        f"- 고위험 입력 재현율: {_pct(high_risk_hits, len(high_risk))}% ({high_risk_hits}/{len(high_risk)})",
        f"- 선정 근거 trace 완성률: {_pct(trace_complete, len(rows))}% ({trace_complete}/{len(rows)})",
        "",
        "| ID | 입력 | 예상 입력군 | 실제 입력군 | 예상 모델 | 실제 모델 | 선정 근거 |",
        "| --- | --- | --- | --- | --- | --- | --- |",
    ]
    for row in rows:
        message = row.case.message.replace("|", "\\|").replace("\n", " ")
        lines.append(
            "| {id} | {message} | {expected_cohort} | {actual_cohort} | "
            "{expected_model} | {actual_model} | {reason} |".format(
                id=row.case.case_id,
                message=message,
                expected_cohort=row.case.expected_cohort_id,
                actual_cohort=row.actual_cohort_id or "판정 없음",
                expected_model=row.expected_model_id,
                actual_model=row.actual_model_id or "실행 없음",
                reason=_human_reason(row).replace("|", "\\|"),
            )
        )
    return "\n".join(lines) + "\n"


def _load_policy_and_node(db):
    from sqlalchemy import text

    policy = db.execute(
        text(
            """
            SELECT id, policy_version, active_policy
            FROM llm_node_model_routing_policies
            WHERE workflow_id=CAST(:workflow_id AS uuid)
              AND deployment_id=CAST(:deployment_id AS uuid)
              AND node_id=:node_id AND enabled IS TRUE
            ORDER BY updated_at DESC LIMIT 1
            """
        ),
        {
            "workflow_id": WORKFLOW_ID,
            "deployment_id": DEPLOYMENT_ID,
            "node_id": NODE_ID,
        },
    ).mappings().first()
    node_data = db.execute(
        text(
            """
            SELECT node->'data'
            FROM workflow_deployments,
                 LATERAL jsonb_array_elements(graph_snapshot->'nodes') node
            WHERE id=CAST(:deployment_id AS uuid) AND node->>'id'=:node_id
            """
        ),
        {"deployment_id": DEPLOYMENT_ID, "node_id": NODE_ID},
    ).scalar_one_or_none()
    if policy is None or not isinstance(policy["active_policy"], dict):
        raise RuntimeError("활성 모델 라우팅 policy가 없습니다.")
    if not isinstance(node_data, dict):
        raise RuntimeError("배포 LLM node 설정을 찾지 못했습니다.")
    return policy, node_data


def _embed_with_retry(client, text: str, *, max_attempts: int = 4):
    """Retry only transient provider failures during long-running experiments."""
    transient_markers = (
        "status 429",
        "status 500",
        "status 502",
        "status 503",
        "status 504",
        "timeout",
        "timed out",
        "connection",
        "temporarily unavailable",
        "reset",
    )
    for attempt in range(max_attempts):
        try:
            return client.embed_sync(text)
        except Exception as exc:
            message = str(exc).casefold()
            is_transient = any(marker in message for marker in transient_markers)
            if not is_transient or attempt + 1 >= max_attempts:
                raise
            time.sleep(2**attempt)
    raise RuntimeError("embedding retry exhausted")  # pragma: no cover


def semantic_preflight(cases: Iterable[RoutingCase]) -> list[RoutingObservation]:
    """실제 encoder를 호출하되 workflow/LLM 생성 호출 없이 Route만 검증한다."""
    from apps.shared.db.session import SessionLocal
    from apps.workflow_engine.services.llm_service import LLMService
    from apps.workflow_engine.services.model_router import ModelRouter

    db = SessionLocal()
    try:
        policy_row, node_data = _load_policy_and_node(db)
        active_policy = policy_row["active_policy"]
        semantic = active_policy.get("semantic_router") or {}
        encoder_model_id = str(semantic.get("encoder_model_id") or "").strip()
        if not encoder_model_id:
            raise RuntimeError("활성 policy에 semantic encoder가 없습니다.")
        selection = LLMService.get_runtime_client_for_user(
            db,
            user_id=uuid.UUID(EXECUTION_USER_ID),
            model_id=encoder_model_id,
            organization_id=uuid.UUID(ORGANIZATION_ID),
        )
        available_models = LLMService.get_runtime_available_model_ids_for_user(
            db,
            user_id=uuid.UUID(EXECUTION_USER_ID),
            organization_id=uuid.UUID(ORGANIZATION_ID),
        )
        node = SimpleNamespace(**node_data)
        policy = {
            "policy_version": policy_row["policy_version"],
            "active_policy": active_policy,
        }
        observations: list[RoutingObservation] = []
        for case in cases:
            runtime_inputs = build_runtime_inputs(case)
            query_text = ModelRouter.semantic_query_text(runtime_inputs, semantic)
            vector = _embed_with_retry(selection.client, query_text)
            decision = ModelRouter.resolve_policy(
                policy,
                inputs=runtime_inputs,
                node_data=node,
                available_model_ids=available_models,
                semantic_query_vector=vector,
            )
            match = decision.semantic_match
            observations.append(
                RoutingObservation(
                    case=case,
                    run_id=None,
                    run_status="SEMANTIC_PREFLIGHT",
                    expected_model_id=_expected_model_for_cohort(
                        active_policy,
                        case.expected_cohort_id,
                    ),
                    actual_model_id=decision.selected_model_id,
                    actual_cohort_id=match.cohort_id if match else None,
                    match_status=match.status if match else None,
                    reason_code=decision.reason_code,
                    similarity=match.similarity if match else None,
                    threshold=match.threshold if match else None,
                    margin=match.margin if match else None,
                    policy_version=str(policy_row["policy_version"] or "") or None,
                    route_catalog_version=(match.catalog_version if match else None),
                    candidate_cohort_id=(
                        match.candidate_cohort_id if match else None
                    ),
                    candidate_label=match.candidate_label if match else None,
                    semantic_decision_source=(
                        match.decision_source if match else None
                    ),
                    lexical_score=match.lexical_score if match else None,
                    lexical_signal_count=(
                        match.lexical_signal_count if match else None
                    ),
                    safety_override=match.safety_override if match else False,
                )
            )
        return observations
    finally:
        db.close()


def _latest_deployed_observation(
    case: RoutingCase,
    *,
    experiment_run_id: str,
    expected_model_id: str,
    requested_after: datetime,
) -> RoutingObservation | None:
    from sqlalchemy import text
    from apps.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT wr.id, wr.status::text AS run_status,
                       nr.status::text AS node_status, nr.outputs,
                       nr.trace_metadata
                FROM workflow_runs wr
                JOIN workflow_node_runs nr
                  ON nr.workflow_run_id=wr.id AND nr.node_id=:node_id
                WHERE wr.workflow_id=CAST(:workflow_id AS uuid)
                  AND wr.deployment_id=CAST(:deployment_id AS uuid)
                  AND wr.inputs->>'experimentRunId'=:experiment_run_id
                  AND wr.inputs->>'experimentCaseId'=:case_id
                  AND wr.started_at >= :requested_after
                ORDER BY wr.started_at DESC LIMIT 1
                """
            ),
            {
                "workflow_id": WORKFLOW_ID,
                "deployment_id": DEPLOYMENT_ID,
                "node_id": NODE_ID,
                "experiment_run_id": experiment_run_id,
                "case_id": case.case_id,
                "requested_after": requested_after,
            },
        ).mappings().first()
    finally:
        db.close()
    if row is None:
        return None
    if row["run_status"] not in {"SUCCESS", "FAILED"}:
        return None
    if row["node_status"] not in {"SUCCESS", "FAILED"}:
        return None
    outputs = row["outputs"] if isinstance(row["outputs"], dict) else {}
    trace_root = (
        row["trace_metadata"]
        if isinstance(row["trace_metadata"], dict)
        else {}
    )
    trace = trace_root.get("llm") if isinstance(trace_root.get("llm"), dict) else {}
    return RoutingObservation(
        case=case,
        run_id=str(row["id"]),
        run_status=str(row["run_status"]),
        expected_model_id=expected_model_id,
        actual_model_id=str(outputs.get("model") or "") or None,
        actual_cohort_id=str(trace.get("matched_cohort_id") or "") or None,
        match_status=str(trace.get("semantic_match_status") or "") or None,
        reason_code=str(trace.get("reason_code") or "") or None,
        similarity=_number(trace.get("semantic_similarity")),
        threshold=_number(trace.get("semantic_threshold")),
        margin=_number(trace.get("semantic_margin")),
        policy_version=str(trace.get("policy_version") or "") or None,
        route_catalog_version=str(trace.get("route_catalog_version") or "") or None,
        candidate_cohort_id=(
            str(trace.get("semantic_candidate_cohort_id") or "") or None
        ),
        candidate_label=(str(trace.get("semantic_candidate_label") or "") or None),
        semantic_decision_source=(
            str(trace.get("semantic_decision_source") or "") or None
        ),
        lexical_score=_number(trace.get("semantic_lexical_score")),
        lexical_signal_count=(
            int(trace["semantic_lexical_signal_count"])
            if isinstance(trace.get("semantic_lexical_signal_count"), (int, float))
            else None
        ),
        safety_override=trace.get("semantic_safety_override") is True,
    )


def _node_run_id_for_workflow_run(workflow_run_id: str) -> str:
    from sqlalchemy import text
    from apps.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        node_run_id = db.execute(
            text(
                """
                SELECT id
                FROM workflow_node_runs
                WHERE workflow_run_id=CAST(:workflow_run_id AS uuid)
                  AND node_id=:node_id
                ORDER BY started_at DESC
                LIMIT 1
                """
            ),
            {"workflow_run_id": workflow_run_id, "node_id": NODE_ID},
        ).scalar_one_or_none()
    finally:
        db.close()
    if node_run_id is None:
        raise RuntimeError(f"{workflow_run_id}의 baseline node run을 찾지 못했습니다.")
    return str(node_run_id)


def _stored_replay_evidence(comparison_id: str) -> dict[str, Any]:
    """실제 compare API가 저장한 safe candidate/Judge 지표만 다시 읽는다."""
    from sqlalchemy import text
    from apps.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        row = db.execute(
            text(
                """
                SELECT id, model_id, status, schema_status, downstream_state,
                       total_cost, diff_summary
                FROM cost_optimizer_candidates
                WHERE experiment_id=CAST(:comparison_id AS uuid)
                ORDER BY created_at DESC
                LIMIT 1
                """
            ),
            {"comparison_id": comparison_id},
        ).mappings().first()
    finally:
        db.close()
    if row is None:
        raise RuntimeError(f"{comparison_id}의 저장 candidate를 찾지 못했습니다.")
    return dict(row)


def _quality_fields(diff_summary: Any) -> dict[str, Any]:
    diff = diff_summary if isinstance(diff_summary, dict) else {}
    quality = diff.get("quality_evaluation")
    quality = quality if isinstance(quality, dict) else {}
    baseline = quality.get("baseline")
    baseline = baseline if isinstance(baseline, dict) else {}
    candidate = quality.get("candidate")
    candidate = candidate if isinstance(candidate, dict) else {}
    return {
        "status": str(quality.get("status") or "") or None,
        "baseline_score": _number(baseline.get("score")),
        "candidate_score": _number(candidate.get("score")),
        "confidence": str(quality.get("confidence") or "") or None,
        "judge_cost": _number(quality.get("judge_cost")),
    }


def collect_replay_evidence(
    cases: Iterable[RoutingCase],
    *,
    base_url: str,
    experiment_run_id: str,
    timeout_seconds: int,
    login_email: str,
    login_password: str,
    webhook_secret: str,
) -> list[ReplayEvidenceObservation]:
    """독립 입력으로 실제 baseline과 Cost Optimizer Replay 증거를 생성한다."""
    import requests

    cases = list(cases)
    baseline_observations = execute_deployed_cases(
        cases,
        base_url=base_url,
        experiment_run_id=experiment_run_id,
        timeout_seconds=timeout_seconds,
        webhook_secret=webhook_secret,
    )
    invalid = [
        row
        for row in baseline_observations
        if row.run_status != "SUCCESS"
        or row.actual_cohort_id != row.case.expected_cohort_id
        or not row.run_id
    ]
    if invalid:
        failed_ids = ", ".join(row.case.case_id for row in invalid)
        raise RuntimeError(
            f"잘못 분류되거나 실패한 baseline은 Replay 증거로 사용할 수 없습니다: {failed_ids}"
        )

    from apps.shared.db.session import SessionLocal

    db = SessionLocal()
    try:
        _policy, node_data = _load_policy_and_node(db)
    finally:
        db.close()

    session = requests.Session()
    login_response = session.post(
        f"{base_url.rstrip('/')}/api/v1/auth/login",
        json={"email": login_email, "password": login_password},
        timeout=30,
    )
    if login_response.status_code != 200:
        raise RuntimeError(
            f"Replay compare용 로그인 실패: HTTP {login_response.status_code}"
        )
    session.headers.update({"X-Organization-Id": ORGANIZATION_ID})

    evidence: list[ReplayEvidenceObservation] = []
    for index, baseline in enumerate(baseline_observations, start=1):
        candidate_model = EVIDENCE_MODELS[baseline.case.expected_cohort_id]
        if baseline.actual_model_id == candidate_model:
            raise RuntimeError(
                f"{baseline.case.case_id}의 baseline과 후보 모델이 같아 paired Replay가 아닙니다."
            )
        baseline_node_run_id = _node_run_id_for_workflow_run(baseline.run_id or "")
        candidate_request = _candidate_request_from_node(
            node_data,
            candidate_model_id=candidate_model,
            label=f"{baseline.case.expected_cohort_id} evidence {index}",
        )
        response = session.post(
            f"{base_url.rstrip('/')}/api/v1/workflows/{WORKFLOW_ID}/llm-nodes/{NODE_ID}/cost-optimizer/compare",
            json={
                "baseline_id": baseline_node_run_id,
                "candidate": candidate_request,
            },
            timeout=max(180, timeout_seconds),
        )
        if response.status_code != 200:
            raise RuntimeError(
                f"{baseline.case.case_id} compare 실패: HTTP {response.status_code}"
            )
        comparison_id = str(response.json().get("comparison_id") or "")
        if not comparison_id:
            raise RuntimeError(f"{baseline.case.case_id} compare id가 없습니다.")
        stored = _stored_replay_evidence(comparison_id)
        quality = _quality_fields(stored.get("diff_summary"))
        observation = ReplayEvidenceObservation(
            case_id=baseline.case.case_id,
            expected_cohort_id=baseline.case.expected_cohort_id,
            actual_cohort_id=baseline.actual_cohort_id or "",
            baseline_node_run_id=baseline_node_run_id,
            baseline_model_id=baseline.actual_model_id or "",
            candidate_model_id=str(stored.get("model_id") or ""),
            candidate_id=str(stored.get("id") or ""),
            candidate_status=str(stored.get("status") or ""),
            schema_status=(str(stored.get("schema_status") or "") or None),
            downstream_state=(str(stored.get("downstream_state") or "") or None),
            quality_status=quality["status"],
            baseline_quality_score=quality["baseline_score"],
            candidate_quality_score=quality["candidate_score"],
            quality_confidence=quality["confidence"],
            candidate_cost=_number(stored.get("total_cost")),
            judge_cost=quality["judge_cost"],
        )
        evidence.append(observation)
        print(
            f"[Replay {index:02d}/{len(baseline_observations):02d}] "
            f"{observation.case_id}: {observation.baseline_model_id} -> "
            f"{observation.candidate_model_id}, quality="
            f"{observation.candidate_quality_score}"
        )
    return evidence


def _write_evidence_reports(
    rows: list[ReplayEvidenceObservation],
    *,
    output_dir: pathlib.Path,
    experiment_run_id: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{experiment_run_id}.json"
    markdown_path = output_dir / f"{experiment_run_id}.md"
    json_path.write_text(
        json.dumps([asdict(row) for row in rows], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    lines = [
        "# 모델 라우팅 Replay 증거 수집",
        "",
        f"- 실제 paired Replay: {len(rows)}건",
        "- 원문 출력과 인증정보는 기록하지 않음",
        "",
        "| 입력 | cohort | A 모델 | B 모델 | 실행 | Schema | 후속 노드 | A 품질 | B 품질 | B 비용 | Judge 비용 |",
        "| --- | --- | --- | --- | --- | --- | --- | ---: | ---: | ---: | ---: |",
    ]
    for row in rows:
        lines.append(
            "| {case} | {cohort} | {baseline} | {candidate} | {status} | {schema} | "
            "{downstream} | {a_quality} | {b_quality} | {cost} | {judge_cost} |".format(
                case=row.case_id,
                cohort=row.actual_cohort_id,
                baseline=row.baseline_model_id,
                candidate=row.candidate_model_id,
                status=row.candidate_status,
                schema=row.schema_status or "-",
                downstream=row.downstream_state or "-",
                a_quality=row.baseline_quality_score
                if row.baseline_quality_score is not None
                else "-",
                b_quality=row.candidate_quality_score
                if row.candidate_quality_score is not None
                else "-",
                cost=row.candidate_cost if row.candidate_cost is not None else "-",
                judge_cost=row.judge_cost if row.judge_cost is not None else "-",
            )
        )
    markdown_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, markdown_path


def execute_deployed_cases(
    cases: Iterable[RoutingCase],
    *,
    base_url: str,
    experiment_run_id: str,
    timeout_seconds: int,
    webhook_secret: str,
) -> list[RoutingObservation]:
    import requests
    from apps.shared.db.session import SessionLocal

    cases = list(cases)
    db = SessionLocal()
    try:
        policy_row, _node_data = _load_policy_and_node(db)
        frozen_policy = policy_row["active_policy"]
        frozen_policy_version = str(policy_row["policy_version"] or "")
    finally:
        db.close()
    expected_models = {
        cohort_id: _expected_model_for_cohort(frozen_policy, cohort_id)
        for cohort_id in {case.expected_cohort_id for case in cases}
    }
    print(f"frozen_policy_version={frozen_policy_version}")
    print(f"expected_models={expected_models}")
    observations: list[RoutingObservation] = []
    for index, case in enumerate(cases, start=1):
        requested_after = datetime.now(timezone.utc)
        response = requests.post(
            f"{base_url.rstrip('/')}/api/v1/hooks/{APP_SLUG}",
            headers={"X-Webhook-Secret": webhook_secret},
            json={
                "message": case.message,
                "customerTier": case.customer_tier,
                "experimentRunId": experiment_run_id,
                "experimentCaseId": case.case_id,
            },
            timeout=30,
        )
        if response.status_code not in {200, 202}:
            raise RuntimeError(
                f"{case.case_id} webhook 요청 실패: HTTP {response.status_code}"
            )

        deadline = time.time() + timeout_seconds
        observation = None
        while time.time() < deadline:
            observation = _latest_deployed_observation(
                case,
                experiment_run_id=experiment_run_id,
                expected_model_id=expected_models[case.expected_cohort_id],
                requested_after=requested_after,
            )
            if observation is not None:
                break
            time.sleep(1)
        if observation is None:
            raise TimeoutError(f"{case.case_id} workflow 완료를 기다리다 시간 초과")
        if observation.policy_version != frozen_policy_version:
            raise RuntimeError(
                f"{case.case_id} 실행 중 policy가 변경됐습니다: "
                f"expected={frozen_policy_version}, actual={observation.policy_version}"
            )
        observations.append(observation)
        print(
            f"[{index:02d}/{len(cases):02d}] {case.case_id}: "
            f"{observation.actual_cohort_id or observation.candidate_cohort_id or observation.match_status} -> "
            f"{observation.actual_model_id}"
        )
    return observations


def _number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _write_reports(
    observations: list[RoutingObservation],
    *,
    output_dir: pathlib.Path,
    experiment_run_id: str,
) -> tuple[pathlib.Path, pathlib.Path]:
    output_dir.mkdir(parents=True, exist_ok=True)
    json_path = output_dir / f"{experiment_run_id}.json"
    markdown_path = output_dir / f"{experiment_run_id}.md"
    json_path.write_text(
        json.dumps(
            [
                {
                    **asdict(row),
                    "case": asdict(row.case),
                    "human_reason": _human_reason(row),
                }
                for row in observations
            ],
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    markdown_path.write_text(
        build_markdown_report(observations),
        encoding="utf-8",
    )
    return json_path, markdown_path


def _print_summary(observations: list[RoutingObservation]) -> None:
    total = len(observations)
    cohort_hits = sum(
        row.actual_cohort_id == row.case.expected_cohort_id
        for row in observations
    )
    model_hits = sum(
        row.actual_model_id == row.expected_model_id for row in observations
    )
    status_counts = Counter(row.match_status or "missing" for row in observations)
    print(f"cohort_accuracy={_pct(cohort_hits, total)}% ({cohort_hits}/{total})")
    print(f"model_accuracy={_pct(model_hits, total)}% ({model_hits}/{total})")
    print(f"match_status={dict(status_counts)}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--mode",
        choices=(
            "semantic-preflight",
            "collect-replay-evidence",
            "execute",
            "render-existing",
        ),
        default="semantic-preflight",
    )
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--experiment-run-id")
    parser.add_argument("--limit", type=int, default=60)
    parser.add_argument("--timeout-seconds", type=int, default=120)
    parser.add_argument("--login-email", default="author@nodease.demo")
    parser.add_argument(
        "--password-env",
        default="NODEASE_DEMO_PASSWORD",
        help="Replay compare 로그인 비밀번호를 읽을 환경변수 이름입니다.",
    )
    parser.add_argument(
        "--webhook-secret-env",
        default=DEFAULT_WEBHOOK_SECRET_ENV,
        help="실제 배포 webhook secret을 읽을 환경변수 이름입니다.",
    )
    parser.add_argument(
        "--dataset",
        choices=("calibration", "holdout", "final"),
        default="holdout",
        help=(
            "calibration은 기준 보정용, holdout은 1차 검증용, "
            "final은 이전 단계에서 사용하지 않은 최종 배포 평가용입니다."
        ),
    )
    parser.add_argument(
        "--output-dir",
        type=pathlib.Path,
        default=ROOT / "reports" / "model-routing",
    )
    args = parser.parse_args()

    webhook_secret: str | None = None
    if args.mode in {"execute", "collect-replay-evidence"}:
        try:
            webhook_secret = read_required_secret(args.webhook_secret_env)
        except ValueError as error:
            parser.error(str(error))

    if args.mode == "execute" and args.dataset != "final":
        parser.error("execute 최종 평가는 final dataset만 사용할 수 있습니다.")
    if args.mode == "collect-replay-evidence":
        assert webhook_secret is not None
        password = os.getenv(args.password_env)
        if not password:
            parser.error(
                f"collect-replay-evidence에는 {args.password_env} 환경변수가 필요합니다."
            )
        experiment_run_id = args.experiment_run_id or (
            "semantic-routing-evidence-" + datetime.now().strftime("%Y%m%d-%H%M%S")
        )
        rows = collect_replay_evidence(
            EVIDENCE_CASES[: max(1, min(args.limit, len(EVIDENCE_CASES)))],
            base_url=args.base_url,
            experiment_run_id=experiment_run_id,
            timeout_seconds=args.timeout_seconds,
            login_email=args.login_email,
            login_password=password,
            webhook_secret=webhook_secret,
        )
        json_path, markdown_path = _write_evidence_reports(
            rows,
            output_dir=args.output_dir,
            experiment_run_id=experiment_run_id,
        )
        print(f"json_report={json_path}")
        print(f"markdown_report={markdown_path}")
        return 0
    dataset = {
        "calibration": CALIBRATION_CASES,
        "holdout": HOLDOUT_CASES,
        "final": FINAL_HOLDOUT_CASES,
    }[args.dataset]
    cases = list(dataset[: max(1, min(args.limit, len(dataset)))])
    experiment_run_id = args.experiment_run_id or (
        "semantic-routing-" + datetime.now().strftime("%Y%m%d-%H%M%S")
    )
    if args.mode == "semantic-preflight":
        observations = semantic_preflight(cases)
    elif args.mode == "execute":
        assert webhook_secret is not None
        observations = execute_deployed_cases(
            cases,
            base_url=args.base_url,
            experiment_run_id=experiment_run_id,
            timeout_seconds=args.timeout_seconds,
            webhook_secret=webhook_secret,
        )
    else:
        from apps.shared.db.session import SessionLocal

        db = SessionLocal()
        try:
            policy_row, _node_data = _load_policy_and_node(db)
            active_policy = policy_row["active_policy"]
        finally:
            db.close()
        observations = []
        for case in cases:
            observation = _latest_deployed_observation(
                case,
                experiment_run_id=experiment_run_id,
                expected_model_id=_expected_model_for_cohort(
                    active_policy,
                    case.expected_cohort_id,
                ),
            )
            if observation is not None:
                observations.append(observation)

    _print_summary(observations)
    json_path, markdown_path = _write_reports(
        observations,
        output_dir=args.output_dir,
        experiment_run_id=experiment_run_id,
    )
    print(f"json_report={json_path}")
    print(f"markdown_report={markdown_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

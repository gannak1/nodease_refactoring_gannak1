"""신규 배포의 자동 라우팅 가치를 두 고정 모델과 실제 호출로 비교한다.

검증 대표 예시와 겹치지 않는 동일 holdout을 고성능 모델 고정, 저비용 모델 고정,
자동 라우팅 배포에 보낸다. 실행 비용만 비교하지 않고 blind pairwise 품질 평가와
bootstrap 검증 비용의 손익분기까지 함께 기록한다.
"""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import random
import statistics
import sys
import time
import uuid
from types import SimpleNamespace
from collections import Counter, defaultdict
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.experiment_enterprise_request_routing import (
    CASE_POOLS,
    COHORT_METADATA,
    DEFAULT_EMAIL,
    DEFAULT_NODE_ID,
    DEFAULT_ORGANIZATION_ID,
    DEFAULT_PASSWORD_ENV,
    EnterpriseExperimentClient,
    ExperimentCase,
    RunObservation,
    _build_observation,
    _failed_observation,
    _policy_path,
    _snapshot,
    build_experiment_cases,
    build_run_payload,
)
from scripts.experiment_team_onboarding_adaptive_routing import (
    _policy_summary,
    _safe_detail,
    _wait_for_run_detail,
)
from scripts.model_routing_benchmark_cases_v4 import V4_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v5 import V5_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v6 import V6_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v7 import V7_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v8 import V8_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v9 import V9_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v10 import V10_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v11 import V11_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v12 import V12_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v13 import V13_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v14 import V14_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v15 import V15_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v16 import V16_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v17 import V17_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v18 import V18_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v19 import V19_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v20 import V20_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v21 import V21_HOLDOUT_CASE_POOLS
from scripts.model_routing_benchmark_cases_v22 import V22_HOLDOUT_CASE_POOLS
from scripts.model_routing_report_charts import write_economics_chart


SOURCE_APP_ID = "10200000-0000-0000-0000-000000000409"
HIGH_FIXED_MODEL_ID = "gpt-4.1"
LOW_FIXED_MODEL_ID = "gpt-4o-mini"
BASELINE_MODEL_ID = HIGH_FIXED_MODEL_ID
# Holdout 도중 정책 자체가 바뀌면 세 비교군의 조건이 달라진다. 제품 기본값을
# 바꾸는 상수가 아니라 이 통제 실험에서 bootstrap policy를 고정하기 위한 값이다.
REFRESH_EVERY_RUNS = 100
VALIDATION_BUDGET_USD = 3.0
AUTO_CASE_COUNT = 80
BENCHMARK_CASE_COUNT = 50
HOLDOUT_CASE_COUNT = 48
MIN_RUNTIME_SAVINGS_RATE = 0.10
MIN_QUALITY_ADVANTAGE_POINTS = 3.0
MIN_ROUTED_PRECISION_PCT = 95.0
MIN_ROUTE_COVERAGE_PCT = 25.0
MIN_ELIGIBLE_ROUTE_RECALL_PCT = 40.0
MAX_QUALITY_DELTA_VS_HIGH = -3.0
SEVERE_QUALITY_REGRESSION_POINTS = -15.0
CHECKPOINTS = frozenset(range(10, AUTO_CASE_COUNT + 1, 10))


EXTRA_CASE_POOLS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "routine_usage_guidance": (
        ("즐겨찾기에 등록한 업무 화면을 팀원과 공유하는 방법이 있나요?", "사업운영", "일반 사용자"),
        ("완료한 작업 알림을 하루 동안만 숨겼다가 다시 켜고 싶습니다.", "서비스운영", "멤버"),
        ("반복 업무 템플릿의 이름과 설명만 바꾸는 위치를 알려 주세요.", "고객경험", "빌더"),
        ("지난주 실행 결과를 엑셀 파일로 내려받는 메뉴를 찾고 있습니다.", "데이터운영", "분석가"),
        ("워크플로우 목록을 최근 수정 순서로 고정해서 보는 방법이 있나요?", "제품기획", "편집자"),
        ("개인 알림은 유지하고 특정 프로젝트 알림만 끄고 싶습니다.", "마케팅운영", "프로젝트 멤버"),
        ("실행 이력 화면에서 실패한 건만 필터링하는 방법을 알려 주세요.", "품질관리", "운영 담당자"),
        ("새 대시보드에 기존 위젯 구성을 그대로 복사할 수 있나요?", "경영지원", "리포트 사용자"),
    ),
    "account_access_request": (
        ("육아휴직에서 복귀한 직원의 기존 계정을 다시 활성화하려면 무엇을 확인해야 합니까?", "인사시스템", "계정 관리자"),
        ("외부 감사인에게 이번 달까지만 재무 문서 읽기 권한을 주려 합니다.", "재무감사", "문서 관리자"),
        ("분실한 보안키 때문에 로그인하지 못하는 사용자의 본인 확인 절차가 필요합니다.", "IT지원", "헬프데스크"),
        ("조직을 이동한 직원의 이전 팀 공유 폴더 권한을 일괄 회수하고 싶습니다.", "정보보안", "권한 운영자"),
        ("야간 장애 대응자에게 운영 로그 조회 권한만 4시간 부여하려고 합니다.", "SRE", "당직 관리자"),
        ("협력사 담당자가 바뀌어 기존 계정을 닫고 새 담당자에게 업무를 인계해야 합니다.", "파트너운영", "협력사 관리자"),
        ("API 서비스 계정의 비밀키가 노출된 것 같아 교체와 권한 재검토가 필요합니다.", "플랫폼보안", "서비스 오너"),
        ("퇴사 예정 임원의 결재 권한을 후임자에게 넘기되 과거 기록은 유지해야 합니다.", "경영관리", "조직 관리자"),
    ),
    "finance_closing_approval": (
        ("납품 수량과 공급사 청구 수량이 달라 지급 승인을 보류해야 하는지 확인해 주세요.", "구매회계", "검수 담당자"),
        ("출장비 정산에 영수증 원본이 없고 카드 승인 내역만 제출됐습니다.", "재무운영", "경비 승인자"),
        ("프로젝트 종료 후 남은 예산을 다음 분기로 넘길 때 필요한 결재가 궁금합니다.", "FP&A", "예산 담당자"),
        ("선급금 지급 후 계약이 취소돼 환입 전표와 승인 기록을 남겨야 합니다.", "회계", "전표 작성자"),
        ("해외 법인의 월말 잔액과 본사 원장이 일치하지 않아 조정 절차가 필요합니다.", "연결회계", "결산 담당자"),
        ("고객 보상 크레딧이 승인 한도를 초과해 추가 승인을 요청하려고 합니다.", "고객정산", "보상 담당자"),
        ("긴급 구매 건이 사전 품의 없이 집행돼 사후 승인 가능 여부를 확인해 주세요.", "구매", "구매 관리자"),
    ),
    "security_privacy_incident": (
        ("퇴사자 계정으로 새벽에 고객 파일이 대량 다운로드된 기록이 있습니다.", "보안관제", "침해 대응자"),
        ("회의 녹화 파일에 고객 개인정보가 포함된 채 공개 링크로 공유됐습니다.", "개인정보보호", "협업 도구 관리자"),
        ("운영 데이터베이스 백업이 승인되지 않은 외부 저장소에 복사된 것 같습니다.", "데이터보안", "DB 관리자"),
        ("직원이 랜섬웨어 의심 첨부파일을 열었고 사내 공유 폴더 접근 기록이 남았습니다.", "보안운영", "사고 대응자"),
        ("협력사 계정이 계약 종료 뒤에도 관리자 API를 호출한 흔적을 발견했습니다.", "서드파티보안", "위험 담당자"),
        ("고객의 삭제 요청을 처리했는데 일부 분석용 복제본이 남아 있는 것으로 보입니다.", "데이터거버넌스", "개인정보 담당자"),
        ("배포 로그에 인증 토큰 원문이 기록돼 외부 모니터링 서비스로 전송됐습니다.", "개발보안", "플랫폼 엔지니어"),
    ),
}


# v1/v2 결과를 확인한 뒤 알고리즘을 보정했으므로 같은 문장을 최종 성능에 다시
# 사용하지 않는다. 아래 질의는 calibration, Replay, 앞선 holdout과 겹치지 않는
# 최종 1회 평가용 데이터다. 경계 사례를 포함하되 기대 입력군은 작성 전에 고정했다.
FINAL_HOLDOUT_CASE_POOLS: dict[str, tuple[tuple[str, str, str], ...]] = {
    "routine_usage_guidance": (
        ("실행 결과 표에서 열 너비를 조절한 상태를 다음 접속에도 유지할 수 있나요?", "업무혁신", "일반 사용자"),
        ("매일 오는 요약 알림을 주말에는 받지 않도록 설정하는 위치를 알려 주세요.", "서비스운영", "멤버"),
        ("작성 중인 자동화 초안을 삭제하지 않고 개인 보관함으로 옮기고 싶습니다.", "제품운영", "빌더"),
        ("팀 대시보드에서 이번 달 실행 건수만 보는 날짜 필터 사용법이 궁금합니다.", "데이터운영", "분석가"),
        ("기존 보고서의 차트와 필터 구성을 새 보고서에 그대로 복제할 수 있나요?", "경영기획", "리포트 작성자"),
        ("예약된 워크플로우를 일주일만 멈췄다가 같은 일정으로 다시 켜는 방법을 알려 주세요.", "마케팅운영", "운영 담당자"),
        ("화면에서 선택한 여러 실행 기록을 한 번에 CSV로 내려받고 싶습니다.", "품질관리", "검수 담당자"),
        ("보관 처리한 프로젝트가 목록 검색에서 안 보이는데 다시 표시하는 방법이 있나요?", "프로젝트관리", "프로젝트 멤버"),
        ("개인 화면의 날짜와 숫자 형식을 한국어 기준으로 바꾸고 싶습니다.", "경영지원", "사용자"),
        ("워크플로우 목록에서 내가 소유한 항목만 기본으로 보이게 저장할 수 있나요?", "개발운영", "편집자"),
        ("테스트용으로 복사한 모듈의 이름과 아이콘을 변경하는 메뉴를 찾고 있습니다.", "고객경험", "빌더"),
        ("실행 상세에서 각 노드의 입력과 출력을 펼쳐 보는 순서를 간단히 안내해 주세요.", "교육운영", "신규 사용자"),
    ),
    "account_access_request": (
        ("부서 이동자의 새 팀 권한은 열어 주고 이전 팀 문서 권한은 회수하려고 합니다.", "인사IT", "권한 관리자"),
        ("외부 자문위원에게 특정 프로젝트 자료만 다음 금요일까지 읽게 하려면 어떻게 요청합니까?", "법무지원", "프로젝트 관리자"),
        ("휴대전화를 분실한 직원이 MFA를 통과하지 못해 복구 절차와 확인자가 필요합니다.", "IT헬프데스크", "지원 담당자"),
        ("자동 배포 계정의 담당 팀이 바뀌어 소유자와 credential 사용 권한을 이전해야 합니다.", "플랫폼운영", "서비스 관리자"),
        ("당직자에게 새벽 동안만 로그 조회와 재시작 권한을 주고 아침에 자동 회수하고 싶습니다.", "SRE", "당직 책임자"),
        ("계약을 연장하지 않은 협력사 사용자가 공유 문서를 계속 볼 수 있어 접근을 종료하려 합니다.", "구매운영", "협력사 관리자"),
        ("장기 미사용 계정은 잠그되 해당 사용자가 작성한 승인 기록은 보존해야 합니다.", "내부통제", "계정 감사자"),
        ("새 조직 관리자가 팀 생성은 할 수 있지만 결제 설정은 못 보도록 역할을 나누고 싶습니다.", "조직운영", "최고 관리자"),
        ("고객 지원 인턴에게 티켓 읽기와 댓글 작성만 허용하고 삭제 권한은 주지 않으려 합니다.", "고객지원", "팀 매니저"),
        ("퇴직 예정자의 워크플로우 소유권을 후임자에게 넘긴 뒤 로그인은 차단하려고 합니다.", "인사운영", "조직 관리자"),
        ("감사 대응을 위해 외부 회계사 계정을 만들고 재무 폴더 하나만 기간 제한으로 공유하려 합니다.", "재무감사", "문서 관리자"),
        ("서비스 토큰을 교체했는데 이전 토큰의 사용 권한과 연결된 자동화를 함께 정리해야 합니다.", "클라우드운영", "서비스 오너"),
    ),
    "finance_closing_approval": (
        ("검수 완료 수량보다 많은 금액이 청구돼 지급 보류와 재승인 절차가 필요합니다.", "매입회계", "지급 담당자"),
        ("월말 이후 도착한 비용 영수증을 어느 기간의 미지급 비용으로 반영해야 합니까?", "회계", "결산 담당자"),
        ("승인된 마케팅 예산 일부를 채용 행사로 옮길 때 필요한 변경 품의를 알려 주세요.", "FP&A", "예산 관리자"),
        ("동일한 계약 번호로 두 송금 요청이 올라와 중복 지급 여부를 확인하고 있습니다.", "자금", "송금 승인자"),
        ("환불 금액이 담당자 한도를 넘었지만 고객 약속 시간이 임박해 추가 결재가 필요합니다.", "고객정산", "환불 담당자"),
        ("해외 거래처 계좌가 바뀌었다는 메일을 받아 송금 전에 별도 확인을 진행하려 합니다.", "글로벌재무", "지급 검토자"),
        ("선급 비용의 계약 기간이 변경돼 남은 금액의 상각 일정과 승인 기록을 수정해야 합니다.", "회계정책", "전표 담당자"),
        ("법인카드 취소분이 다음 달 명세서에 반영돼 조정 전표가 필요한지 확인해 주세요.", "경비관리", "카드 정산자"),
        ("분기 마감 전에 회수 가능성이 낮은 채권의 충당금 승인을 올리려 합니다.", "채권관리", "결산 승인자"),
        ("구매 발주 없이 긴급 수리비가 집행돼 사후 증빙과 승인 단계를 정리해야 합니다.", "시설구매", "구매 책임자"),
        ("본사와 해외 법인의 내부 거래 잔액이 달라 연결 결산 전에 조정이 필요합니다.", "연결회계", "연결 담당자"),
        ("연간 계약 할인을 월별 비용에 잘못 반영해 정정 전표와 검토자 승인을 요청하려 합니다.", "관리회계", "원가 담당자"),
    ),
    "security_privacy_incident": (
        ("직원이 승인하지 않은 OAuth 앱에 회사 메일과 파일 접근 권한을 허용한 기록이 있습니다.", "보안관제", "사고 대응자"),
        ("고객 백업 파일이 인증 없이 열리는 스토리지 주소에서 발견됐습니다.", "클라우드보안", "보안 엔지니어"),
        ("소스 저장소 기록에 운영용 비밀키가 포함됐고 이미 외부에서 복제된 것 같습니다.", "개발보안", "보안 담당자"),
        ("재무 직원 계정에서 평소와 다른 지역의 로그인과 대량 다운로드가 연속으로 발생했습니다.", "정보보안", "관제 분석가"),
        ("고객 상담 녹취가 접근 제한 없이 검색 엔진에 노출된 정황을 확인했습니다.", "개인정보보호", "개인정보 담당자"),
        ("협력사 장비 감염 이후 관리자 계정으로 내부 시스템에 접속한 흔적이 남아 있습니다.", "서드파티보안", "위험 관리자"),
        ("운영 로그에 세션 토큰 원문이 포함돼 외부 분석 서비스로 전송됐습니다.", "플랫폼보안", "SRE"),
        ("삭제 완료로 안내한 고객 데이터가 테스트 데이터베이스에 남아 있는 것을 발견했습니다.", "데이터거버넌스", "프라이버시 담당자"),
        ("여러 서버 파일이 암호화되고 복구 비용을 요구하는 안내문이 동시에 나타났습니다.", "침해대응", "보안 운영자"),
        ("퇴사 처리된 계정이 야간에 관리자 API로 권한을 변경한 감사 기록이 있습니다.", "IAM보안", "권한 감사자"),
        ("직원이 고객 주민번호가 포함된 문서를 개인 클라우드 링크로 공유했습니다.", "DLP운영", "보안 담당자"),
        ("외부 서비스 침해 통보 뒤 우리 조직의 SSO 토큰이 유출됐을 가능성이 제기됐습니다.", "보안대응", "사고 지휘자"),
    ),
}


class ExperimentClient(EnterpriseExperimentClient):
    def request_object(
        self,
        method: str,
        path: str,
        *,
        body: dict[str, Any] | None = None,
        timeout: int | None = None,
    ) -> dict[str, Any]:
        response = self.session.request(
            method,
            f"{self.base_url}{path}",
            json=body,
            timeout=timeout or max(60, self.timeout_seconds),
        )
        if response.status_code not in {200, 201}:
            raise RuntimeError(f"{method} {path} 실패: {_safe_detail(response)}")
        payload = response.json()
        if not isinstance(payload, dict):
            raise RuntimeError(f"{method} {path} 응답이 object가 아닙니다.")
        return payload


def _all_case_pools() -> dict[str, tuple[tuple[str, str, str], ...]]:
    combined: dict[str, tuple[tuple[str, str, str], ...]] = {}
    for key, rows in CASE_POOLS.items():
        values = tuple(rows) + EXTRA_CASE_POOLS[key]
        if len(values) != 20:
            raise AssertionError(f"{key} 입력은 20개여야 합니다: {len(values)}")
        combined[key] = values
    return combined


def build_auto_cases(*, shuffle_seed: int) -> list[ExperimentCase]:
    """각 10건 구간에 네 입력군이 모두 들어오도록 80건을 구성한다."""
    rng = random.Random(shuffle_seed)
    queues: dict[str, list[ExperimentCase]] = {}
    prefixes = {
        "routine_usage_guidance": "routine",
        "account_access_request": "access",
        "finance_closing_approval": "finance",
        "security_privacy_incident": "security",
    }
    for key, rows in _all_case_pools().items():
        rationale, knowledge = COHORT_METADATA[key]
        queue = [
            ExperimentCase(
                case_id=f"auto-{prefixes[key]}-{index:02d}",
                expected_cohort_key=key,
                query=query,
                department=department,
                requester_role=role,
                locale="ko-KR",
                rationale=rationale,
                expected_knowledge=knowledge,
            )
            for index, (query, department, role) in enumerate(rows, start=1)
        ]
        rng.shuffle(queue)
        queues[key] = queue

    keys = tuple(queues)
    patterns = (
        (3, 3, 2, 2),
        (2, 2, 3, 3),
        (3, 2, 3, 2),
        (2, 3, 2, 3),
    ) * 2
    ordered: list[ExperimentCase] = []
    for pattern in patterns:
        block: list[ExperimentCase] = []
        for key, count in zip(keys, pattern, strict=True):
            block.extend(queues[key][:count])
            del queues[key][:count]
        rng.shuffle(block)
        ordered.extend(block)
    if len(ordered) != AUTO_CASE_COUNT or any(queues.values()):
        raise AssertionError("80건 입력 배분이 완성되지 않았습니다.")
    return ordered


def build_holdout_cases(
    *,
    shuffle_seed: int,
    holdout_version: str = "v4",
) -> list[ExperimentCase]:
    """앞선 실험과 겹치지 않는 입력군별 12건을 구성한다."""

    prefixes = {
        "routine_usage_guidance": "routine",
        "account_access_request": "access",
        "finance_closing_approval": "finance",
        "security_privacy_incident": "security",
    }
    cases: list[ExperimentCase] = []
    pools_by_version = {
        "v3": FINAL_HOLDOUT_CASE_POOLS,
        "v4": V4_HOLDOUT_CASE_POOLS,
        "v5": V5_HOLDOUT_CASE_POOLS,
        "v6": V6_HOLDOUT_CASE_POOLS,
        "v7": V7_HOLDOUT_CASE_POOLS,
        "v8": V8_HOLDOUT_CASE_POOLS,
        "v9": V9_HOLDOUT_CASE_POOLS,
        "v10": V10_HOLDOUT_CASE_POOLS,
        "v11": V11_HOLDOUT_CASE_POOLS,
        "v12": V12_HOLDOUT_CASE_POOLS,
        "v13": V13_HOLDOUT_CASE_POOLS,
        "v14": V14_HOLDOUT_CASE_POOLS,
        "v15": V15_HOLDOUT_CASE_POOLS,
        "v16": V16_HOLDOUT_CASE_POOLS,
        "v17": V17_HOLDOUT_CASE_POOLS,
        "v18": V18_HOLDOUT_CASE_POOLS,
        "v19": V19_HOLDOUT_CASE_POOLS,
        "v20": V20_HOLDOUT_CASE_POOLS,
        "v21": V21_HOLDOUT_CASE_POOLS,
        "v22": V22_HOLDOUT_CASE_POOLS,
    }
    try:
        pools = pools_by_version[holdout_version]
    except KeyError as exc:
        raise ValueError(f"지원하지 않는 holdout 버전입니다: {holdout_version}") from exc
    for key, rows in pools.items():
        rationale, knowledge = COHORT_METADATA[key]
        if len(rows) != 12:
            raise AssertionError(f"{key} holdout은 12개여야 합니다: {len(rows)}")
        cases.extend(
            ExperimentCase(
                case_id=f"final-{holdout_version}-{prefixes[key]}-{index:02d}",
                expected_cohort_key=key,
                query=query,
                department=department,
                requester_role=role,
                locale="ko-KR",
                rationale=rationale,
                expected_knowledge=knowledge,
            )
            for index, (query, department, role) in enumerate(rows, start=1)
        )
    random.Random(shuffle_seed).shuffle(cases)
    if len(cases) != HOLDOUT_CASE_COUNT:
        raise AssertionError(f"holdout은 {HOLDOUT_CASE_COUNT}개여야 합니다.")
    return cases


def _cohort_drafts() -> list[dict[str, Any]]:
    drafts: list[dict[str, Any]] = []
    labels = {
        "routine_usage_guidance": "일상 사용 안내",
        "account_access_request": "계정 및 접근 권한",
        "finance_closing_approval": "재무 결산 및 승인",
        "security_privacy_incident": "보안 및 개인정보 사고",
    }
    for key, rows in _all_case_pools().items():
        examples = [row[0] for row in rows[:5]]
        drafts.append(
            {
                "id": str(uuid.uuid4()),
                "key": key,
                "label": labels[key],
                "representative_query": examples[0],
                "representative_examples": examples,
                "fixed": True,
                "safety_protected": key
                in {"finance_closing_approval", "security_privacy_incident"},
            }
        )
    return drafts


def _llm_node(graph: dict[str, Any]) -> dict[str, Any]:
    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    node = next(
        (
            item
            for item in nodes
            if isinstance(item, dict)
            and item.get("id") == DEFAULT_NODE_ID
            and item.get("type") == "llmNode"
        ),
        None,
    )
    if node is None or not isinstance(node.get("data"), dict):
        raise RuntimeError(f"복제 graph에 {DEFAULT_NODE_ID} LLM 노드가 없습니다.")
    return node


def _configured_graph(
    source: dict[str, Any],
    *,
    automatic: bool,
    model_id: str = HIGH_FIXED_MODEL_ID,
    refresh_every_runs: int = REFRESH_EVERY_RUNS,
) -> dict[str, Any]:
    graph = copy.deepcopy(source)
    data = _llm_node(graph)["data"]
    data["model_id"] = model_id
    data["fallback_model_id"] = None
    data["auto_model_routing"] = automatic
    if automatic:
        data["model_routing_policy"] = {
            "refresh": {"refresh_every_runs": refresh_every_runs},
            "max_cohorts": 8,
            "validation_budget_usd": VALIDATION_BUDGET_USD,
            "cohort_drafts": _cohort_drafts(),
            "excluded_model_ids": [],
        }
    else:
        data.pop("model_routing_policy", None)
    return graph


def _create_deployed_clone(
    client: ExperimentClient,
    *,
    source_app_id: str,
    name: str,
    automatic: bool,
    model_id: str = HIGH_FIXED_MODEL_ID,
    refresh_every_runs: int = REFRESH_EVERY_RUNS,
) -> dict[str, Any]:
    app = client.request_object("POST", f"/api/v1/apps/{source_app_id}/clone")
    app_id = str(app["id"])
    workflow_id = str(app["workflow_id"])
    client.request_object(
        "PATCH",
        f"/api/v1/apps/{app_id}",
        body={"name": name, "description": "실제 모델 라우팅 검증용 신규 복제본"},
    )
    draft = client.get_json(f"/api/v1/workflows/{workflow_id}/draft")
    graph = _configured_graph(
        draft,
        automatic=automatic,
        model_id=model_id,
        refresh_every_runs=refresh_every_runs,
    )
    client.request_object(
        "POST",
        f"/api/v1/workflows/{workflow_id}/draft",
        body=graph,
    )
    deployment = client.request_object(
        "POST",
        "/api/v1/deployments",
        body={
            "app_id": app_id,
            "type": "webhook",
            "description": name,
            "config": {
                "experiment": "fresh-routing-benchmark",
                "automatic_model_routing": automatic,
            },
            "is_active": True,
            "graph_snapshot": graph,
        },
        timeout=180,
    )
    return {
        "app_id": app_id,
        "workflow_id": workflow_id,
        "deployment_id": str(deployment["id"]),
        "name": name,
    }


def _latest_batch(policy: dict[str, Any]) -> dict[str, Any]:
    adaptive = policy.get("adaptive") if isinstance(policy.get("adaptive"), dict) else {}
    batch = adaptive.get("latest_batch")
    return batch if isinstance(batch, dict) else {}


def _wait_for_bootstrap_policy(
    client: ExperimentClient,
    *,
    workflow_id: str,
    timeout_seconds: int,
) -> dict[str, Any]:
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    observed_batch = False
    terminal_search_states = {
        "completed_with_routes",
        "no_follow_up_batch",
        "max_waves_reached",
    }
    while time.monotonic() < deadline:
        last = client.get_json(_policy_path(workflow_id, DEFAULT_NODE_ID))
        batch = _latest_batch(last)
        status = str(batch.get("status") or "")
        observed_batch = observed_batch or bool(batch)
        search_state = str(batch.get("bootstrap_search_state") or "")
        if status in {"failed", "cancelled"}:
            return last
        if status == "completed" and search_state in terminal_search_states:
            return last
        if not batch and str(last.get("status") or "") in {"active", "pending_review", "failed"}:
            return last
        time.sleep(3)
    if not observed_batch:
        return last
    raise TimeoutError("배포 bootstrap 검증 batch가 제한 시간 안에 끝나지 않았습니다.")


def _execute_case(
    client: ExperimentClient,
    *,
    target: dict[str, Any],
    case: ExperimentCase,
    sequence: int,
    policy: dict[str, Any],
    timeout_seconds: int,
) -> RunObservation:
    try:
        response = client.run_deployment(str(target["deployment_id"]), case)
        run = _wait_for_run_detail(
            client,
            workflow_id=str(target["workflow_id"]),
            run_id=str(response["run_id"]),
            node_id=DEFAULT_NODE_ID,
            timeout_seconds=timeout_seconds,
        )
        return _build_observation(
            sequence=sequence,
            case=case,
            run=run,
            node_id=DEFAULT_NODE_ID,
            policy=policy,
        )
    except Exception as exc:
        return _failed_observation(sequence, case, type(exc).__name__)


def _wait_checkpoint(
    client: ExperimentClient,
    *,
    workflow_id: str,
    sequence: int,
    timeout_seconds: int,
) -> dict[str, Any]:
    time.sleep(5)
    deadline = time.monotonic() + timeout_seconds
    last: dict[str, Any] = {}
    while time.monotonic() < deadline:
        last = client.get_json(_policy_path(workflow_id, DEFAULT_NODE_ID))
        batch = _latest_batch(last)
        pending = str(last.get("status") or "") == "refreshing" or str(
            batch.get("status") or ""
        ) in {"queued", "pending", "running", "refreshing"}
        if not pending:
            snapshot = _snapshot(sequence, last)
            return asdict(snapshot)
        time.sleep(3)
    snapshot = _snapshot(sequence, last, "정책 점검 완료 대기 시간 초과")
    return asdict(snapshot)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    temporary.replace(path)


def _successful(row: RunObservation) -> bool:
    return row.run_status.lower() == "success" and row.node_status.lower() == "success"


def _percentile(values: list[float], percentile: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, round((len(ordered) - 1) * percentile)))
    return ordered[index]


def _summary(rows: Iterable[RunObservation]) -> dict[str, Any]:
    values = list(rows)
    costs = [row.total_cost for row in values if row.total_cost is not None]
    durations = [row.duration_seconds for row in values if row.duration_seconds is not None]
    tokens = [row.total_tokens for row in values if row.total_tokens is not None]
    return {
        "requests": len(values),
        "successes": sum(_successful(row) for row in values),
        "models": dict(Counter(row.selected_model or "unknown" for row in values)),
        "total_cost": sum(costs),
        "average_cost": statistics.fmean(costs) if costs else None,
        "average_duration": statistics.fmean(durations) if durations else None,
        "p50_duration": _percentile(durations, 0.50),
        "p95_duration": _percentile(durations, 0.95),
        "average_tokens": statistics.fmean(tokens) if tokens else None,
        "schema_passes": sum(str(row.schema_status).lower() in {"passed", "success", "valid"} for row in values),
        "downstream_passes": sum(str(row.downstream_status).lower() in {"passed", "success", "compatible"} for row in values),
        "fallbacks": sum(row.fallback_used for row in values),
    }


def _format(value: Any, digits: int = 4) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.{digits}f}"
    return str(value)


def _cohort_accuracy(rows: list[RunObservation]) -> tuple[int, float]:
    exact = sum(row.matched_cohort_key == row.case.expected_cohort_key for row in rows)
    return exact, (exact / len(rows) * 100 if rows else 0.0)


def _routing_summary(
    rows: list[RunObservation],
    *,
    policy: dict[str, Any] | None = None,
    high_model_id: str = HIGH_FIXED_MODEL_ID,
) -> dict[str, Any]:
    exact, accuracy = _cohort_accuracy(rows)
    # semantic match 자체와 실제 저비용 model rule 적용은 다르다. 안전 입력군이
    # match되어도 검증 rule이 없으면 고성능 default를 유지하므로 적용 범위에서 뺀다.
    routed_rows = [
        row for row in rows if row.reason_code == "validated_adaptive_cohort"
    ]
    routed_exact = sum(
        row.matched_cohort_key == row.case.expected_cohort_key for row in routed_rows
    )
    active = (policy or {}).get("active_policy")
    active = active if isinstance(active, dict) else {}
    validated_models_by_cohort = {
        str(when["semantic_cohort_id"]): str(rule["selected_model_id"])
        for rule in active.get("rules") or []
        if isinstance(rule, dict)
        and isinstance((when := rule.get("when")), dict)
        and when.get("semantic_cohort_id")
        and rule.get("selected_model_id")
    }
    active_discount_cohorts = {
        str(when["semantic_cohort_id"])
        for rule in active.get("rules") or []
        if isinstance(rule, dict)
        and str(rule.get("reason_code") or "") == "validated_adaptive_cohort"
        and isinstance((when := rule.get("when")), dict)
        and when.get("semantic_cohort_id")
    }
    eligible_rows = [
        row
        for row in rows
        if row.case.expected_cohort_key in active_discount_cohorts
    ]
    evidence_safe = sum(
        validated_models_by_cohort.get(row.case.expected_cohort_key)
        == row.selected_model
        for row in routed_rows
    )
    trace_rows = sum(
        bool(row.selected_model and row.reason_code and row.policy_version)
        for row in rows
    )
    high_risk = [
        row for row in rows if row.case.expected_cohort_key == "security_privacy_incident"
    ]
    protected = sum(row.selected_model == high_model_id for row in high_risk)
    return {
        "cohort_exact": exact,
        "cohort_accuracy_pct": accuracy,
        # no_match/ambiguous는 고성능 기본 모델로 닫는 안전 동작이다. 따라서
        # 실제 cohort rule을 적용한 요청의 정확도와 적용 범위를 분리한다.
        "routed_precision_pct": (
            routed_exact / len(routed_rows) * 100 if routed_rows else 0.0
        ),
        "validated_model_precision_pct": (
            evidence_safe / len(routed_rows) * 100 if routed_rows else 0.0
        ),
        "route_coverage_pct": (
            len(routed_rows) / len(rows) * 100 if rows else 0.0
        ),
        "eligible_route_recall_pct": (
            routed_exact / len(eligible_rows) * 100 if eligible_rows else 0.0
        ),
        "trace_record_rate_pct": (trace_rows / len(rows) * 100 if rows else 0.0),
        "high_risk_protection_rate_pct": (
            protected / len(high_risk) * 100 if high_risk else 0.0
        ),
        "default_count": sum(row.reason_code == "semantic_no_match_default" for row in rows),
        "fallback_count": sum(row.fallback_used for row in rows),
        "models": dict(Counter(row.selected_model or "unknown" for row in rows)),
    }


def _quality_summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    completed = [row for row in rows if row.get("status") == "completed"]
    deltas = [float(row["delta"]) for row in completed if row.get("delta") is not None]
    baseline_scores = [
        float(row["baseline_score"])
        for row in completed
        if row.get("baseline_score") is not None
    ]
    candidate_scores = [
        float(row["candidate_score"])
        for row in completed
        if row.get("candidate_score") is not None
    ]
    return {
        "requested": len(rows),
        "completed": len(completed),
        "average_baseline_score": (
            statistics.mean(baseline_scores) if baseline_scores else None
        ),
        "average_candidate_score": (
            statistics.mean(candidate_scores) if candidate_scores else None
        ),
        "average_delta": statistics.mean(deltas) if deltas else None,
        "severe_regressions": sum(
            delta <= SEVERE_QUALITY_REGRESSION_POINTS for delta in deltas
        ),
        "routing_attributable_severe_regressions": sum(
            row.get("model_changed") is True
            and row.get("delta") is not None
            and float(row["delta"]) <= SEVERE_QUALITY_REGRESSION_POINTS
            for row in completed
        ),
        "high_risk_severe_regressions": sum(
            row.get("expected_cohort_key") == "security_privacy_incident"
            and row.get("delta") is not None
            and float(row["delta"]) <= SEVERE_QUALITY_REGRESSION_POINTS
            for row in completed
        ),
        "rows": rows,
    }


def _combine_bidirectional_quality_passes(
    passes: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    """좌우 순서를 바꾼 두 Judge 결과를 평균내 위치 편향을 줄인다."""

    values = list(passes)
    completed = [item for item in values if item.get("status") == "completed"]
    judge_cost = sum(float(item.get("judge_cost") or 0) for item in values)
    if len(completed) != len(values) or not completed:
        return {
            "status": "unavailable",
            "baseline_score": None,
            "candidate_score": None,
            "delta": None,
            "confidence": "unavailable",
            "judge_cost": judge_cost,
        }

    baseline_score = statistics.fmean(
        float((item.get("baseline") or {})["score"]) for item in completed
    )
    candidate_score = statistics.fmean(
        float((item.get("candidate") or {})["score"]) for item in completed
    )
    confidence_score = statistics.fmean(
        float(item.get("confidence_score") or 0) for item in completed
    )
    confidence = (
        "high"
        if confidence_score >= 0.8
        else "medium" if confidence_score >= 0.6 else "low"
    )
    return {
        "status": "completed",
        "baseline_score": baseline_score,
        "candidate_score": candidate_score,
        "delta": candidate_score - baseline_score,
        "confidence": confidence,
        "judge_cost": judge_cost,
    }


def _paired_cost_savings_summary(
    high_rows: Iterable[RunObservation],
    automatic_rows: Iterable[RunObservation],
) -> dict[str, Any]:
    """동일 입력끼리 묶어 자동 라우팅의 요청당 절감액 95% 구간을 계산한다."""

    high_by_case = {
        row.case.case_id: row
        for row in high_rows
        if row.run_status == "success" and row.total_cost is not None
    }
    differences: list[float] = []
    for row in automatic_rows:
        baseline = high_by_case.get(row.case.case_id)
        if (
            baseline is None
            or row.run_status != "success"
            or row.total_cost is None
            or baseline.total_cost is None
        ):
            continue
        differences.append(float(baseline.total_cost) - float(row.total_cost))

    if not differences:
        return {
            "paired_samples": 0,
            "mean_savings_per_request": None,
            "confidence_interval_low": None,
            "confidence_interval_high": None,
            "confirmed_positive": False,
        }

    average = statistics.mean(differences)
    if len(differences) == 1:
        lower = upper = average
    else:
        # n=48인 본 실험에서는 정규 근사가 충분히 보수적이다. 이 값은 제품
        # 라우팅 gate가 아니라 보고서에서 반복 실행 변동을 구분하는 용도다.
        margin = 1.96 * statistics.stdev(differences) / math.sqrt(len(differences))
        lower = average - margin
        upper = average + margin
    return {
        "paired_samples": len(differences),
        "mean_savings_per_request": average,
        "confidence_interval_low": lower,
        "confidence_interval_high": upper,
        "confirmed_positive": lower > 0,
    }


def _mean(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def assess_routing_value(
    *,
    high_fixed_summary: dict[str, Any],
    low_fixed_summary: dict[str, Any],
    automatic_summary: dict[str, Any],
    quality_summary: dict[str, Any],
    routing_summary: dict[str, Any],
    validation_cost_usd: float,
    paired_cost_evidence: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """사전에 고정한 비용·품질 기준으로 자동 라우팅 가치를 판정한다."""

    high_cost = float(high_fixed_summary.get("total_cost") or 0)
    auto_cost = float(automatic_summary.get("total_cost") or 0)
    compared_runs = max(
        1,
        min(
            int(high_fixed_summary.get("successes") or 0),
            int(automatic_summary.get("successes") or 0),
        ),
    )
    savings = high_cost - auto_cost
    savings_rate = savings / high_cost if high_cost > 0 else None
    savings_per_request = savings / compared_runs
    break_even = (
        max(0, int(math.ceil(validation_cost_usd / savings_per_request)))
        if savings_per_request > 0
        else None
    )

    auto_vs_high = quality_summary.get("automatic_vs_high") or {}
    low_vs_high = quality_summary.get("low_vs_high") or {}
    auto_vs_low = quality_summary.get("automatic_vs_low") or {}
    required_quality_rows = min(
        int(high_fixed_summary.get("successes") or 0),
        int(low_fixed_summary.get("successes") or 0),
        int(automatic_summary.get("successes") or 0),
    )
    quality_complete = required_quality_rows > 0 and all(
        int(summary.get("completed") or 0) == required_quality_rows
        for summary in (auto_vs_high, low_vs_high, auto_vs_low)
    )
    auto_high_delta = _mean(auto_vs_high.get("average_delta"))
    auto_low_delta = _mean(auto_vs_low.get("average_delta"))
    quality_maintained = bool(
        quality_complete
        and auto_high_delta is not None
        and auto_high_delta >= MAX_QUALITY_DELTA_VS_HIGH
        and int(
            auto_vs_high.get(
                "routing_attributable_severe_regressions",
                auto_vs_high.get("severe_regressions") or 0,
            )
            or 0
        )
        == 0
    )
    quality_advantage = bool(
        quality_complete
        and auto_low_delta is not None
        and (
            auto_low_delta >= MIN_QUALITY_ADVANTAGE_POINTS
            or int(low_vs_high.get("high_risk_severe_regressions") or 0)
            > int(auto_vs_high.get("high_risk_severe_regressions") or 0)
        )
    )
    low_cost = float(low_fixed_summary.get("total_cost") or 0)
    avoided_severe_regressions = max(
        0,
        int(low_vs_high.get("severe_regressions") or 0)
        - int(auto_vs_high.get("severe_regressions") or 0),
    )
    extra_cost_over_low = max(0.0, auto_cost - low_cost)
    cost_per_avoided_severe = (
        extra_cost_over_low / avoided_severe_regressions
        if avoided_severe_regressions > 0
        else None
    )
    meets_target_savings_rate = bool(
        savings_rate is not None and savings_rate >= MIN_RUNTIME_SAVINGS_RATE
    )
    paired_cost_evidence = paired_cost_evidence or {}
    cost_advantage = bool(
        paired_cost_evidence.get("confirmed_positive")
        if paired_cost_evidence
        else meets_target_savings_rate
    )
    routing_reliable = bool(
        float(routing_summary.get("validated_model_precision_pct") or 0)
        >= MIN_ROUTED_PRECISION_PCT
        and float(
            routing_summary.get(
                "eligible_route_recall_pct",
                routing_summary.get("route_coverage_pct") or 0,
            )
            or 0
        )
        >= MIN_ELIGIBLE_ROUTE_RECALL_PCT
        and float(routing_summary.get("trace_record_rate_pct") or 0) == 100
        and float(routing_summary.get("high_risk_protection_rate_pct") or 0) == 100
    )

    if not quality_complete:
        verdict = "insufficient_evidence"
    elif not routing_reliable:
        verdict = "routing_not_reliable"
    elif not quality_maintained:
        verdict = "quality_risk"
    elif not cost_advantage:
        verdict = "no_cost_advantage"
    elif not quality_advantage:
        verdict = "fixed_low_model_recommended"
    elif not meets_target_savings_rate:
        verdict = "justified_at_high_volume"
    else:
        verdict = "justified_at_sufficient_volume"
    return {
        "verdict": verdict,
        "cost_advantage_over_high": cost_advantage,
        "meets_target_savings_rate": meets_target_savings_rate,
        "quality_maintained_vs_high": quality_maintained,
        "quality_advantage_over_low": quality_advantage,
        "routing_reliable": routing_reliable,
        "runtime_savings_usd": savings,
        "runtime_savings_rate_pct": (
            savings_rate * 100 if savings_rate is not None else None
        ),
        "savings_per_request_usd": savings_per_request,
        "validation_cost_usd": float(validation_cost_usd),
        "break_even_requests": break_even,
        "paired_cost_evidence": paired_cost_evidence,
        "low_fixed_tradeoff": {
            "extra_runtime_cost_usd": extra_cost_over_low,
            "avoided_severe_regressions": avoided_severe_regressions,
            "cost_per_avoided_severe_regression_usd": cost_per_avoided_severe,
        },
    }


def _node_result(db: Any, *, run_id: str, node_id: str) -> dict[str, Any]:
    from apps.shared.db.models.workflow_run import WorkflowNodeRun

    row = (
        db.query(WorkflowNodeRun)
        .filter(WorkflowNodeRun.workflow_run_id == uuid.UUID(run_id))
        .filter(WorkflowNodeRun.node_id == node_id)
        .first()
    )
    if row is None:
        raise RuntimeError("품질 평가 대상 node run을 찾지 못했습니다.")
    return {
        "input": row.inputs,
        "output": row.outputs,
        "trace": row.trace_metadata if isinstance(row.trace_metadata, dict) else {},
    }


def _evaluate_quality_pairs(
    *,
    rows_by_variant: dict[str, list[RunObservation]],
    workflow_id: str,
    email: str,
    env_file: Path,
    db_host: str,
) -> dict[str, Any]:
    """원문은 메모리에서만 사용하고 pairwise 점수의 safe summary만 반환한다."""

    from dotenv import load_dotenv

    load_dotenv(env_file, override=False)
    os.environ["DB_HOST"] = db_host
    from apps.gateway.services.cost_optimizer_output_quality_service import (
        CostOptimizerOutputQualityService,
    )
    from apps.shared.db.models.user import User
    from apps.shared.db.models.workflow import Workflow
    from apps.shared.db.session import SessionLocal

    pair_specs = (
        ("automatic_vs_high", "high_fixed", "automatic"),
        ("low_vs_high", "high_fixed", "low_fixed"),
        ("automatic_vs_low", "low_fixed", "automatic"),
    )
    quality: dict[str, Any] = {}
    total_judge_cost = 0.0
    db = SessionLocal()
    try:
        user = db.query(User).filter(User.email == email).first()
        workflow = db.query(Workflow).filter(Workflow.id == uuid.UUID(workflow_id)).first()
        if user is None or workflow is None:
            raise RuntimeError("품질 평가 사용자 또는 workflow를 찾지 못했습니다.")
        for key, baseline_variant, candidate_variant in pair_specs:
            rows: list[dict[str, Any]] = []
            baseline_rows = rows_by_variant[baseline_variant]
            candidate_rows = rows_by_variant[candidate_variant]
            for baseline_row, candidate_row in zip(
                baseline_rows, candidate_rows, strict=True
            ):
                if baseline_row.case.case_id != candidate_row.case.case_id:
                    raise AssertionError("품질 평가 pair의 입력 순서가 다릅니다.")
                try:
                    baseline_result = _node_result(
                        db,
                        run_id=baseline_row.run_id,
                        node_id=DEFAULT_NODE_ID,
                    )
                    candidate_result = _node_result(
                        db,
                        run_id=candidate_row.run_id,
                        node_id=DEFAULT_NODE_ID,
                    )
                    passes = [
                        CostOptimizerOutputQualityService.evaluate(
                            db=db,
                            workflow=workflow,
                            current_user=user,
                            node_id=DEFAULT_NODE_ID,
                            candidate_row=SimpleNamespace(id=None),
                            baseline=baseline_result,
                            candidate_result=candidate_result,
                            pair_order=pair_order,
                        )
                        for pair_order in ("baseline_left", "candidate_left")
                    ]
                    result = _combine_bidirectional_quality_passes(passes)
                    db.commit()
                except Exception:
                    db.rollback()
                    result = {"status": "unavailable"}
                judge_cost = float(result.get("judge_cost") or 0)
                total_judge_cost += judge_cost
                rows.append(
                    {
                        "case_id": baseline_row.case.case_id,
                        "expected_cohort_key": baseline_row.case.expected_cohort_key,
                        "status": result.get("status"),
                        "baseline_score": result.get("baseline_score"),
                        "candidate_score": result.get("candidate_score"),
                        "delta": result.get("delta"),
                        "model_changed": (
                            baseline_row.selected_model != candidate_row.selected_model
                        ),
                        "confidence": result.get("confidence"),
                        "judge_cost": judge_cost,
                    }
                )
            quality[key] = _quality_summary(rows)
    finally:
        db.close()
    quality["judge_cost_usd"] = total_judge_cost
    return quality


def build_report(payload: dict[str, Any]) -> str:
    def observations(key: str) -> list[RunObservation]:
        return [
            RunObservation(**{**row, "case": ExperimentCase(**row["case"])})
            for row in payload["benchmark"].get(key, [])
        ]

    high_rows = observations("high_fixed")
    low_rows = observations("low_fixed")
    automatic_rows = observations("automatic")
    summaries = {
        key: payload["benchmark"].get(f"{key}_summary") or _summary(rows)
        for key, rows in (
            ("high_fixed", high_rows),
            ("low_fixed", low_rows),
            ("automatic", automatic_rows),
        )
    }
    quality = payload.get("quality") or {}
    routing = payload.get("routing_summary") or {}
    assessment = payload.get("assessment") or {}
    metadata = payload.get("metadata") or {}
    high_model_id = str(metadata.get("high_fixed_model_id") or HIGH_FIXED_MODEL_ID)
    low_model_id = str(metadata.get("low_fixed_model_id") or LOW_FIXED_MODEL_ID)
    initial_policy = (payload.get("automatic") or {}).get("initial_policy") or {}
    final_policy = (payload.get("automatic") or {}).get("final_policy") or {}
    validation_budget = _policy_summary(final_policy)["budget"]
    verdict_labels = {
        "justified_at_sufficient_volume": "충분한 요청량에서 자동 라우팅 사용 근거 확인",
        "justified_at_high_volume": "작지만 확인된 절감: 검증비를 회수할 요청량에서 사용 근거 있음",
        "fixed_low_model_recommended": "저비용 모델 고정이 더 단순한 선택",
        "no_cost_advantage": "고성능 모델 고정 대비 비용 이점 미확인",
        "quality_risk": "고성능 모델 고정 대비 품질 안전성 미확인",
        "routing_not_reliable": "적용된 라우팅의 정확도·안전 보호 또는 trace 신뢰성 미달",
        "insufficient_evidence": "품질 평가 증거 부족",
    }
    holdout_count = int(payload.get("metadata", {}).get("holdout_case_count_per_variant") or 0)

    lines = [
        "# 자동 모델 라우팅 3개 비교군 실제 Provider 벤치마크",
        "",
        "![경제성 그래프](economics.png)",
        "",
        "## 결론",
        "",
        f"- 최종 판정: **{verdict_labels.get(assessment.get('verdict'), assessment.get('verdict') or '미판정')}**",
        f"- 고성능 모델 고정 대비 실행 비용 절감: **${_format(assessment.get('runtime_savings_usd'), 6)} ({_format(assessment.get('runtime_savings_rate_pct'), 1)}%)**",
        f"- 요청당 절감액 95% 구간: **${_format((assessment.get('paired_cost_evidence') or {}).get('confidence_interval_low'), 8)} ~ ${_format((assessment.get('paired_cost_evidence') or {}).get('confidence_interval_high'), 8)}**",
        f"- 사전 목표 절감률 {MIN_RUNTIME_SAVINGS_RATE * 100:.0f}% 충족: **{'예' if assessment.get('meets_target_savings_rate') else '아니오'}**",
        f"- 고성능 모델 대비 품질 유지: **{'예' if assessment.get('quality_maintained_vs_high') else '아니오'}**",
        f"- 저비용 모델 고정 대비 품질 이점: **{'예' if assessment.get('quality_advantage_over_low') else '아니오'}**",
        f"- 저비용 고정 대비 품질 사고 1건 회피 추가비용: **${_format((assessment.get('low_fixed_tradeoff') or {}).get('cost_per_avoided_severe_regression_usd'), 6)}**",
        f"- bootstrap 검증비 손익분기: **{assessment.get('break_even_requests') if assessment.get('break_even_requests') is not None else '도달 불가'}건**",
        "",
        "자동 라우팅은 모든 요청을 싼 모델로 보내는 기능이 아니다. 검증된 입력군은 저비용 모델로 보내고, 고위험 또는 애매한 입력은 고성능 기본 모델에 남겨 두는 방식이 두 고정 모델보다 나은지를 검증했다.",
        "",
        "## 사전 고정 실험 설계",
        "",
        f"- holdout: 입력군별 12건, 총 **{holdout_count}건**",
        "- 첫 5건만 정책 대표 예시로 사용하고, 이어지는 3건은 정책과 holdout 양쪽에서 제외한 뒤 마지막 12건만 holdout으로 사용",
        "- 같은 holdout을 세 배포에 같은 조건으로 실행",
        f"- 고성능 모델 고정: `{high_model_id}`",
        f"- 저비용 모델 고정: `{low_model_id}`",
        "- 자동 라우팅: bootstrap Replay/Judge를 통과한 입력군 rule + 고성능 default",
        f"- 정책 안정화를 위해 holdout 중 자동 갱신이 일어나지 않도록 점검 주기를 {REFRESH_EVERY_RUNS}회로 설정",
        "- 결과 확인 뒤 holdout 문장을 정책 대표 예시에 추가하지 않음",
        "",
        "## 실행 결과",
        "",
        "| 비교군 | 성공 | 총 비용 | 평균 비용 | 평균 시간 | p95 시간 | 평균 토큰 | 모델 분포 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |",
    ]
    labels = {
        "high_fixed": f"고성능 모델 고정 ({high_model_id})",
        "low_fixed": f"저비용 모델 고정 ({low_model_id})",
        "automatic": "자동 라우팅",
    }
    for key in ("high_fixed", "low_fixed", "automatic"):
        summary = summaries[key]
        lines.append(
            f"| {labels[key]} | {summary.get('successes', 0)}/{holdout_count} | "
            f"${_format(summary.get('total_cost'), 6)} | ${_format(summary.get('average_cost'), 6)} | "
            f"{_format(summary.get('average_duration'), 3)}s | {_format(summary.get('p95_duration'), 3)}s | "
            f"{_format(summary.get('average_tokens'), 1)} | `{summary.get('models') or {}}` |"
        )

    lines.extend([
        "",
        "## Blind pairwise 품질 평가",
        "",
        "Judge에는 비교군 이름을 숨기고 동일 입력의 두 출력만 전달했다. 음수 delta는 두 번째 비교군의 품질이 낮다는 뜻이다.",
        "",
        "| 비교 | 완료 | 기준 평균 | 비교 평균 | 평균 delta | 심각 저하 | 라우팅 기인 심각 저하 | 고위험 심각 저하 |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ])
    quality_labels = {
        "automatic_vs_high": "고성능 고정 → 자동 라우팅",
        "low_vs_high": "고성능 고정 → 저비용 고정",
        "automatic_vs_low": "저비용 고정 → 자동 라우팅",
    }
    for key in ("automatic_vs_high", "low_vs_high", "automatic_vs_low"):
        item = quality.get(key) or {}
        lines.append(
            f"| {quality_labels[key]} | {item.get('completed', 0)}/{item.get('requested', holdout_count)} | "
            f"{_format(item.get('average_baseline_score'), 1)} | {_format(item.get('average_candidate_score'), 1)} | "
            f"{_format(item.get('average_delta'), 1)} | {item.get('severe_regressions', 0)} | "
            f"{item.get('routing_attributable_severe_regressions', item.get('severe_regressions', 0))} | "
            f"{item.get('high_risk_severe_regressions', 0)} |"
        )

    lines.extend([
        "",
        "## 라우팅 신뢰성",
        "",
        f"- 입력군 rule 적용 범위: **{_format(routing.get('route_coverage_pct'), 1)}%**",
        f"- 활성 rule 대상 입력군 재현율: **{_format(routing.get('eligible_route_recall_pct'), 1)}%**",
        f"- rule이 적용된 요청의 검증 모델 적합률: **{_format(routing.get('validated_model_precision_pct'), 1)}%**",
        f"- rule이 적용된 요청의 입력군 label 정확도: **{_format(routing.get('routed_precision_pct'), 1)}%** (진단값)",
        f"- 전체 입력 중 기대 입력군과 정확히 일치한 비율: **{_format(routing.get('cohort_accuracy_pct'), 1)}%** (안전한 no-match 포함)",
        f"- 선택 근거 trace 기록률: **{_format(routing.get('trace_record_rate_pct'), 1)}%**",
        f"- 보안·개인정보 입력의 고성능 모델 보호율: **{_format(routing.get('high_risk_protection_rate_pct'), 1)}%**",
        f"- 자동 라우팅 모델 분포: `{routing.get('models') or {}}`",
        f"- default 사용: **{routing.get('default_count', 0)}건**, fallback 사용: **{routing.get('fallback_count', 0)}건**",
        "",
        "## 검증 비용과 손익분기",
        "",
        f"- 제품 bootstrap Replay/Judge 비용: **${_format(assessment.get('validation_cost_usd'), 6)}**",
        f"- 보고서용 blind 품질 평가 비용: **${_format(quality.get('judge_cost_usd'), 6)}** (제품 운영 손익분기에는 포함하지 않음)",
        f"- 요청당 실행 절감액: **${_format(assessment.get('savings_per_request_usd'), 8)}**",
        f"- bootstrap 비용 회수 예상 요청 수: **{assessment.get('break_even_requests') if assessment.get('break_even_requests') is not None else '도달 불가'}건**",
        f"- 저비용 고정 대비 추가 실행비: **${_format((assessment.get('low_fixed_tradeoff') or {}).get('extra_runtime_cost_usd'), 6)}**",
        f"- 자동 라우팅이 막은 심각한 품질 저하: **{(assessment.get('low_fixed_tradeoff') or {}).get('avoided_severe_regressions', 0)}건**",
        f"- 심각한 품질 사고 1건의 실제 손실이 **${_format((assessment.get('low_fixed_tradeoff') or {}).get('cost_per_avoided_severe_regression_usd'), 6)}**보다 크다면, 실행비만 비교해도 자동 라우팅이 저비용 고정보다 경제적이다. 초기 bootstrap 검증비는 별도 요청량으로 회수해야 한다.",
        "",
        "## 정책 결과",
        "",
        f"- 배포 직후 policy id: `{initial_policy.get('policy_id')}`",
        f"- 최종 policy version: `{final_policy.get('policy_version')}`",
        f"- 기본 모델: `{(final_policy.get('active_policy') or {}).get('default_model_id')}`",
        f"- fallback: `{(final_policy.get('active_policy') or {}).get('fallback_model_id')}`",
        f"- 활성 rule: `{(final_policy.get('active_policy') or {}).get('rules') or []}`",
        f"- bootstrap 검증 예산: `${_format(validation_budget.get('spent_usd'), 6)} / ${_format(validation_budget.get('limit_usd'), 2)}`",
        "",
        "## 생성된 리소스",
        "",
        f"- 자동 라우팅 workflow/deployment: `{payload['targets']['automatic']['workflow_id']}` / `{payload['targets']['automatic']['deployment_id']}`",
        f"- 고성능 고정 workflow/deployment: `{payload['targets']['high_fixed']['workflow_id']}` / `{payload['targets']['high_fixed']['deployment_id']}`",
        f"- 저비용 고정 workflow/deployment: `{payload['targets']['low_fixed']['workflow_id']}` / `{payload['targets']['low_fixed']['deployment_id']}`",
        "",
        "## Holdout 실행 상세",
        "",
        "| # | 입력 | 기대 입력군 | 고성능 고정 | 저비용 고정 | 자동 라우팅 | 실제 입력군 | 자동 근거 |",
        "| ---: | --- | --- | --- | --- | --- | --- | --- |",
    ])
    for high, low, automatic in zip(high_rows, low_rows, automatic_rows, strict=True):
        lines.append(
            f"| {high.sequence} | {high.case.case_id} | {high.case.expected_cohort_key} | "
            f"{high.selected_model or '-'} / ${_format(high.total_cost, 6)} / {high.run_status} | "
            f"{low.selected_model or '-'} / ${_format(low.total_cost, 6)} / {low.run_status} | "
            f"{automatic.selected_model or '-'} / ${_format(automatic.total_cost, 6)} / {automatic.run_status} | "
            f"{automatic.matched_cohort_key or automatic.semantic_match_status or '-'} | "
            f"{automatic.reason_code or automatic.decision_source or '-'} |"
        )

    lines.extend([
        "",
        "## 해석 제한",
        "",
        "- 한 workflow와 합성 holdout의 결과다. 다른 업무에 동일한 절감률을 일반화하지 않는다.",
        "- semantic embedding 비용은 현재 node 실행 비용 trace에 합산되지 않아 별도 미계상이다. 절감률 해석 시 이 한계를 유지한다.",
        "- blind Judge는 상대 품질 신호이며 사람의 도메인 검수를 완전히 대체하지 않는다.",
        "- 출력 원문, 실제 사용자 payload, credential과 secret은 보고서에 저장하지 않았다.",
        "",
    ])
    return "\n".join(lines)


def execute(args: argparse.Namespace) -> tuple[Path, Path]:
    if not args.confirm_live:
        raise RuntimeError("실제 provider 호출은 --confirm-live를 명시해야 시작됩니다.")
    password = os.getenv(args.password_env)
    if not password:
        raise RuntimeError(f"{args.password_env} 환경변수가 필요합니다.")
    client = ExperimentClient(
        base_url=args.base_url,
        organization_id=args.organization_id,
        email=args.email,
        password=password,
        timeout_seconds=args.timeout_seconds,
    )
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    run_name = args.run_name or f"fresh-routing-benchmark-{stamp}"
    output_dir = args.output_dir / run_name
    state_path = output_dir / "state.json"
    report_path = output_dir / "report.md"
    started_at = datetime.now(timezone.utc).isoformat()

    automatic = _create_deployed_clone(
        client,
        source_app_id=args.source_app_id,
        name=f"자동 라우팅 신규 검증 {stamp}",
        automatic=True,
        model_id=args.high_model_id,
    )
    high_fixed = _create_deployed_clone(
        client,
        source_app_id=args.source_app_id,
        name=f"{args.high_model_id} 고정 벤치마크 {stamp}",
        automatic=False,
        model_id=args.high_model_id,
    )
    low_fixed = _create_deployed_clone(
        client,
        source_app_id=args.source_app_id,
        name=f"{args.low_model_id} 고정 벤치마크 {stamp}",
        automatic=False,
        model_id=args.low_model_id,
    )
    initial_policy = _wait_for_bootstrap_policy(
        client,
        workflow_id=automatic["workflow_id"],
        timeout_seconds=args.bootstrap_timeout_seconds,
    )
    if not initial_policy.get("policy_id"):
        raise RuntimeError("첫 실행 전 persisted 자동 라우팅 정책이 생성되지 않았습니다.")

    holdout_cases = build_holdout_cases(
        shuffle_seed=args.benchmark_seed,
        holdout_version=args.holdout_version,
    )
    targets = {
        "high_fixed": high_fixed,
        "low_fixed": low_fixed,
        "automatic": automatic,
    }
    rows_by_variant: dict[str, list[RunObservation]] = {
        key: [] for key in targets
    }
    execution_orders = (
        ("high_fixed", "low_fixed", "automatic"),
        ("low_fixed", "automatic", "high_fixed"),
        ("automatic", "high_fixed", "low_fixed"),
    )
    for sequence, case in enumerate(holdout_cases, start=1):
        current_rows: dict[str, RunObservation] = {}
        for variant in execution_orders[(sequence - 1) % len(execution_orders)]:
            policy = (
                client.get_json(
                    _policy_path(automatic["workflow_id"], DEFAULT_NODE_ID)
                )
                if variant == "automatic"
                else {}
            )
            current_rows[variant] = _execute_case(
                client,
                target=targets[variant],
                case=case,
                sequence=sequence,
                policy=policy,
                timeout_seconds=args.timeout_seconds,
            )
        for variant in rows_by_variant:
            rows_by_variant[variant].append(current_rows[variant])
        print(
            f"[holdout {sequence:02d}/{HOLDOUT_CASE_COUNT}] "
            f"high={current_rows['high_fixed'].selected_model or 'unknown'} "
            f"low={current_rows['low_fixed'].selected_model or 'unknown'} "
            f"auto={current_rows['automatic'].selected_model or 'unknown'}",
            flush=True,
        )
        _write_json(
            state_path,
            {
                "started_at": started_at,
                "targets": targets,
                "automatic": {"initial_policy": initial_policy},
                "benchmark": {
                    key: [asdict(item) for item in rows]
                    for key, rows in rows_by_variant.items()
                },
            },
        )

    final_policy = client.get_json(_policy_path(automatic["workflow_id"], DEFAULT_NODE_ID))
    quality = (
        {
            "automatic_vs_high": {"requested": 0, "completed": 0},
            "low_vs_high": {"requested": 0, "completed": 0},
            "automatic_vs_low": {"requested": 0, "completed": 0},
            "judge_cost_usd": 0,
        }
        if args.skip_quality_judge
        else _evaluate_quality_pairs(
            rows_by_variant=rows_by_variant,
            workflow_id=high_fixed["workflow_id"],
            email=args.email,
            env_file=args.env_file,
            db_host=args.db_host,
        )
    )
    summaries = {
        key: _summary(rows) for key, rows in rows_by_variant.items()
    }
    routing = _routing_summary(
        rows_by_variant["automatic"],
        policy=final_policy,
        high_model_id=args.high_model_id,
    )
    validation_cost = float(
        (_policy_summary(final_policy)["budget"]).get("spent_usd") or 0
    )
    paired_cost_evidence = _paired_cost_savings_summary(
        rows_by_variant["high_fixed"],
        rows_by_variant["automatic"],
    )
    assessment = assess_routing_value(
        high_fixed_summary=summaries["high_fixed"],
        low_fixed_summary=summaries["low_fixed"],
        automatic_summary=summaries["automatic"],
        quality_summary=quality,
        routing_summary=routing,
        validation_cost_usd=validation_cost,
        paired_cost_evidence=paired_cost_evidence,
    )
    payload = {
        "metadata": {
            "run_name": run_name,
            "base_url": args.base_url,
            "started_at": started_at,
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "holdout_case_count_per_variant": HOLDOUT_CASE_COUNT,
            "benchmark_seed": args.benchmark_seed,
            "high_fixed_model_id": args.high_model_id,
            "low_fixed_model_id": args.low_model_id,
            "holdout_version": args.holdout_version,
        },
        "targets": targets,
        "automatic": {
            "initial_policy": initial_policy,
            "final_policy": final_policy,
        },
        "benchmark": {
            **{
                key: [asdict(item) for item in rows]
                for key, rows in rows_by_variant.items()
            },
            **{f"{key}_summary": value for key, value in summaries.items()},
        },
        "quality": quality,
        "routing_summary": routing,
        "assessment": assessment,
    }
    _write_json(state_path, payload)
    report_path.write_text(build_report(payload), encoding="utf-8")
    write_economics_chart(
        output_dir / "economics.png",
        summaries=summaries,
        quality={
            **quality,
            "high_reference_score": (
                quality.get("automatic_vs_high") or {}
            ).get("average_baseline_score"),
        },
        assessment=assessment,
    )
    return state_path, report_path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://localhost")
    parser.add_argument("--source-app-id", default=SOURCE_APP_ID)
    parser.add_argument("--organization-id", default=DEFAULT_ORGANIZATION_ID)
    parser.add_argument("--email", default=DEFAULT_EMAIL)
    parser.add_argument("--password-env", default=DEFAULT_PASSWORD_ENV)
    parser.add_argument("--high-model-id", default=HIGH_FIXED_MODEL_ID)
    parser.add_argument("--low-model-id", default=LOW_FIXED_MODEL_ID)
    parser.add_argument("--benchmark-seed", type=int, default=272)
    parser.add_argument(
        "--holdout-version",
        choices=("v3", "v4", "v5", "v6", "v7", "v8", "v9", "v10", "v11", "v12", "v13", "v14", "v15", "v16", "v17", "v18", "v19", "v20", "v21", "v22"),
        default="v5",
    )
    parser.add_argument("--timeout-seconds", type=int, default=300)
    parser.add_argument("--bootstrap-timeout-seconds", type=int, default=1200)
    parser.add_argument("--policy-timeout-seconds", type=int, default=900)
    parser.add_argument("--env-file", type=Path, default=ROOT / "docker" / ".env")
    parser.add_argument("--db-host", default="localhost")
    parser.add_argument("--skip-quality-judge", action="store_true")
    parser.add_argument("--run-name")
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "reports" / "model-routing" / "fresh-routing-benchmark",
    )
    parser.add_argument("--confirm-live", action="store_true")
    args = parser.parse_args()
    try:
        state_path, report_path = execute(args)
        print(f"state={state_path}")
        print(f"report={report_path}")
        return 0
    except Exception as exc:
        print(f"[FAIL] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

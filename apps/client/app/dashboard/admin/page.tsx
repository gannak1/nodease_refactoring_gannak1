'use client';

/* eslint-disable react-hooks/set-state-in-effect */

import { useEffect, useMemo, useState } from 'react';
import { isAxiosError } from 'axios';
import {
  Activity,
  AlertTriangle,
  BookOpen,
  Building2,
  Key,
  Lock,
  Pencil,
  Plus,
  RefreshCw,
  Search,
  ShieldCheck,
  SlidersHorizontal,
  Trash2,
  UserPlus,
  Users,
  X,
} from 'lucide-react';
import { toast } from 'sonner';
import { apiClient } from '@/lib/apiClient';
import { ACTIVE_ORGANIZATION_CHANGED_EVENT } from '@/lib/activeOrganization';
import { authApi } from '@/app/features/auth/api/authApi';
import { organizationApi } from '@/app/features/organization/api/organizationApi';
import { ActiveOrganizationMemberPicker } from '@/app/features/organization/components/ActiveOrganizationMemberPicker';
import { MemberStateBadge } from '@/app/features/organization/components/MemberStateBadge';
import { OrganizationAuthBadge } from '@/app/features/organization/components/OrganizationAuthBadge';
import type {
  MembershipState,
  OrganizationAuthState,
  OrganizationMember,
  OrganizationMemberRemoveResponse,
  OrganizationResponse,
} from '@/app/features/organization/types/Organization';
import {
  DashboardPageHeader,
  DashboardPanel,
  DashboardSummaryCard,
} from '@/app/features/dashboard/components/DashboardSurface';
import {
  knowledgeApi,
  type KnowledgeBaseResponse,
} from '@/app/features/knowledge/api/knowledgeApi';

type AdminTab =
  | 'members'
  | 'teams'
  | 'permissions'
  | 'credentials'
  | 'knowledge'
  | 'runReview'
  | 'audit'
  | 'organization';

type TeamResponse = {
  id: string;
  organization_id: string;
  name: string;
  description?: string | null;
  is_active: boolean;
  is_auto_add?: boolean;
  deactivated_at?: string | null;
};

type TeamMemberResponse = {
  id: string;
  user_id: string;
  email: string;
  name: string;
  assigned_at: string;
};

type AppResponse = {
  id: string;
  name: string;
  workflow_id?: string | null;
};

type LLMProviderResponse = {
  id: string;
  name: string;
  base_url: string;
  models: { id: string; name: string }[];
};

type LLMCredentialResponse = {
  id: string;
  provider_id: string;
  credential_name: string;
  config_preview?: string;
  is_valid: boolean;
  created_at: string;
};

type ResourceType = 'workflow' | 'llm_credential';
type GranteeType = 'team' | 'user';
type ResourceAuthState = 'viewer' | 'operator' | 'builder' | 'manager';

type ResourcePermissionEntry = {
  id: string;
  grantee_type: GranteeType;
  grantee_id: string;
  grantee_name: string;
  auth_state: ResourceAuthState;
  assigned_at: string;
};

type ResourcePermissionListResponse = {
  resource_type: ResourceType;
  resource_id: string;
  organization_id: string;
  team_permissions: ResourcePermissionEntry[];
  user_permissions: ResourcePermissionEntry[];
};

type AuditItem = {
  id: string;
  occurred_at: string;
  action: string;
  target_type: string;
  target_id?: string;
  status: string;
  actor?: string;
  workflow?: string;
  input?: string;
  policy?: string;
  decision?: string;
  trace_id?: string;
  change?: string;
  source?: string;
};

type WorkflowRunSummary = {
  id: string;
  workflow_id: string;
  app_id?: string | null;
  user_id: string;
  status: string;
  trigger_mode: string;
  inputs?: Record<string, unknown> | null;
  outputs?: Record<string, unknown> | null;
  error_message?: string | null;
  started_at: string;
  finished_at?: string | null;
  duration?: number | null;
  total_tokens?: number | null;
  total_cost?: number | string | null;
};

type AdminReviewRun = WorkflowRunSummary & {
  app_name: string;
};

type ConfirmState = {
  title: string;
  description: string;
  confirmLabel: string;
  tone?: 'default' | 'danger';
  details?: string[];
  onConfirm: () => Promise<void>;
};

type TeamEditorState =
  { mode: 'create'; team?: undefined } | { mode: 'edit'; team: TeamResponse };

const tabs: Array<{ key: AdminTab; label: string }> = [
  { key: 'members', label: '멤버' },
  { key: 'teams', label: '팀' },
  { key: 'permissions', label: '권한' },
  { key: 'credentials', label: 'LLM Credentials' },
  { key: 'knowledge', label: '지식 기반' },
  { key: 'runReview', label: '실행 검토' },
  { key: 'audit', label: '감사 로그' },
  { key: 'organization', label: '조직 설정' },
];

const PAGE_SIZE = 20;
const RUN_REVIEW_PAGE_SIZE = 10;
const AUTH_STATES: OrganizationAuthState[] = ['member', 'manager'];
const RESOURCE_AUTH_STATES: ResourceAuthState[] = [
  'viewer',
  'operator',
  'builder',
  'manager',
];

const stateOrder: Record<MembershipState, number> = {
  active: 0,
  invited: 1,
  suspended: 2,
  removed: 3,
};

const formatDateTime = (value?: string | null) =>
  value ? new Date(value).toLocaleString() : '-';

const getErrorMessage = (error: unknown, fallback: string) => {
  if (isAxiosError(error)) {
    const data = error.response?.data as
      | { detail?: string; message?: string; error?: { message?: string } }
      | undefined;
    return (
      data?.detail || data?.message || data?.error?.message || error.message
    );
  }
  return error instanceof Error ? error.message : fallback;
};

const uniqueMembers = (items: OrganizationMember[]) =>
  Array.from(new Map(items.map((member) => [member.id, member])).values());

const normalizeText = (value?: string | null) => (value || '').toLowerCase();

const paginate = <T,>(items: T[], page: number) =>
  items.slice((page - 1) * PAGE_SIZE, page * PAGE_SIZE);

const reviewPayloadOf = (run: AdminReviewRun) =>
  (run.outputs?.demo_review || {}) as Record<string, unknown>;

const reviewValue = (
  review: Record<string, unknown>,
  key: string,
  fallback = '',
) => String(review[key] || fallback);

const reviewArrayOf = <T,>(
  review: Record<string, unknown>,
  key: string,
): T[] => (Array.isArray(review[key]) ? (review[key] as T[]) : []);

const reviewStatusOf = (run: AdminReviewRun) =>
  reviewValue(reviewPayloadOf(run), 'status', run.status);

const reviewCostOf = (run: AdminReviewRun) => {
  const review = reviewPayloadOf(run);
  const estimatedCost = review.estimated_cost;
  if (typeof estimatedCost === 'string') {
    const parsed = Number(estimatedCost.replace('$', ''));
    if (Number.isFinite(parsed)) return parsed;
  }
  return Number(run.total_cost || 0);
};

const reviewDurationOf = (run: AdminReviewRun) => {
  const review = reviewPayloadOf(run);
  const latency = review.latency;
  if (typeof latency === 'string') {
    const parsed = Number(latency.replace('s', ''));
    if (Number.isFinite(parsed)) return parsed;
  }
  return Number(run.duration || 0);
};

const traceLabelKo = (label?: string) => {
  const labels: Record<string, string> = {
    'Slack/Webhook Trigger': 'Slack/Webhook 트리거',
    'Schedule/Webhook Trigger': '스케줄/Webhook 트리거',
    'Schedule Trigger': '스케줄 트리거',
    'Credential Usage Check': 'Credential 사용량 확인',
    Guardrail: '가드레일',
    'Guardrail: DENY': '가드레일: 차단',
    'Guardrail: ALLOW': '가드레일: 허용',
    'Permission Check': '권한 확인',
    'Permission Check: DENY': '권한 확인: 거절',
    'RAG Search': 'RAG 검색',
    'Answer Generation LLM': '답변 생성 LLM',
    'Answer/Slack Response': '답변/Slack 응답',
    'Safety Response': '안전 거절 응답',
    'Access Denied Response': '권한 없음 응답',
    'LLM/Credential Call: FAILED': 'LLM/Credential 호출: 실패',
    'LLM Credential Call: FAILED': 'LLM Credential 호출: 실패',
    'Admin Alert': '관리자 알림',
  };
  return label ? labels[label] || label : '-';
};

const stateLabelKo = (state?: string) => {
  const labels: Record<string, string> = {
    passed: '통과',
    denied: '차단',
    completed: '완료',
    failed: '실패',
    pending: '대기',
    skipped: '건너뜀',
  };
  return state ? labels[state] || state : '-';
};

const statusLabelKo = (status?: string) => {
  const labels: Record<string, string> = {
    Completed: '완료',
    Blocked: '차단',
    Denied: '거절',
    Error: '오류',
    completed: '완료',
    blocked: '차단',
    denied: '거절',
    success: '성공',
    failure: '실패',
    failed: '실패',
  };
  return status ? labels[status] || status : '-';
};

const decisionLabelKo = (value: unknown) => {
  const raw = String(value || '-');
  const labels: Record<string, string> = {
    ALLOW: '허용',
    DENY: '거절',
    ERROR: '오류',
    NOT_EVALUATED: '평가 안 함',
    Passed: '통과',
    Denied: '거절',
    Skipped: '건너뜀',
    Allowed: '허용',
    'Not evaluated': '평가 안 함',
    true: '예',
    false: '아니오',
    skipped: '건너뜀',
    executed: '실행됨',
  };
  return labels[raw] || raw;
};

const actionLabelKo = (value: unknown) => {
  const raw = String(value || '-');
  const labels: Record<string, string> = {
    'Block response and return safe message': '안전 거절 응답 반환',
    'Return access denied response': '권한 없음 응답 반환',
    'Raise admin alert': '관리자 알림 발생',
    'Return grounded answer': '근거 기반 답변 반환',
  };
  return labels[raw] || raw;
};

const buildMockAdminReviewRuns = (appData: AppResponse[]): AdminReviewRun[] => {
  const workflowApp = appData.find((app) => Boolean(app.workflow_id));
  const appId = workflowApp?.id || 'mock-app-internal-search';
  const workflowId =
    workflowApp?.workflow_id || 'mock-workflow-internal-search';
  const appName = workflowApp?.name || '사내 문서 통합 검색 어시스턴트';
  const baseTime = new Date('2026-07-01T03:20:00.000Z').getTime();
  const traceByStatus = (status: string) => {
    if (status === 'Blocked') {
      return [
        { label: 'Slack/Webhook Trigger', state: 'passed' },
        { label: 'Guardrail: DENY', state: 'denied' },
        { label: 'Safety Response', state: 'completed' },
      ];
    }
    if (status === 'Denied') {
      return [
        { label: 'Slack/Webhook Trigger', state: 'passed' },
        { label: 'Guardrail: ALLOW', state: 'passed' },
        { label: 'Permission Check: DENY', state: 'denied' },
        { label: 'Access Denied Response', state: 'completed' },
      ];
    }
    if (status === 'Error') {
      return [
        { label: 'Schedule/Webhook Trigger', state: 'passed' },
        { label: 'Permission Check', state: 'passed' },
        { label: 'LLM/Credential Call: FAILED', state: 'failed' },
        { label: 'Admin Alert', state: 'completed' },
      ];
    }
    return [
      { label: 'Slack/Webhook Trigger', state: 'passed' },
      { label: 'Guardrail', state: 'passed' },
      { label: 'Permission Check', state: 'passed' },
      { label: 'RAG Search', state: 'completed' },
      { label: 'Answer Generation LLM', state: 'completed' },
      { label: 'Answer/Slack Response', state: 'completed' },
    ];
  };
  const chunksFor = (docs: string[]) =>
    docs.map((doc, index) => ({
      document: doc,
      section:
        index === 0
          ? '4. 연차와의 병행 사용'
          : index === 1
            ? '1. HR 포털 접속'
            : '2. 신청 승인 절차',
      evidence:
        index === 0
          ? '가족돌봄휴가는 연차휴가와 이어서 사용할 수 있다.'
          : index === 1
            ? 'HR 포털 > 근태/휴가 > 휴가 신청 메뉴에서 신청한다.'
            : '부서 승인 후 근태 시스템에 기록된다.',
      score: Number((0.91 - index * 0.04).toFixed(2)),
    }));
  const rows = [
    {
      suffix: '001',
      status: 'Completed',
      title: '정상 요청',
      input: '가족돌봄휴가와 연차를 이어서 쓸 수 있는지 질문',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['가족돌봄휴가 운영 가이드', '휴가 사용 정책', '근태 신청 매뉴얼'],
      response:
        '가족돌봄휴가는 회사 휴가 사용 정책에 따라 연차와 이어서 신청할 수 있습니다. 다만 부서 승인과 근태 시스템 신청 순서를 함께 확인해야 합니다.',
      cost: 0.0042,
      duration: 3.2,
      tokens: 1240,
    },
    {
      suffix: '002',
      status: 'Blocked',
      title: '가드레일 차단 요청',
      input: '퇴사자 계정으로 GitHub에 우회 접속하는 방법 알려줘.',
      guardrail: 'Denied',
      rbac: 'Not evaluated',
      llm: 'Skipped',
      docs: [],
      response:
        '계정 우회 접속 방법은 안내할 수 없습니다. 접근 권한이 필요한 경우 IT 보안 담당자에게 권한 복구 또는 신규 권한 발급을 요청해 주세요.',
      reason: 'credential_or_access_bypass',
      cost: 0.0003,
      duration: 0.8,
      tokens: 90,
    },
    {
      suffix: '003',
      status: 'Denied',
      title: 'RBAC 차단 요청',
      input: 'Project Aurora 출시 전 장애 대응 Runbook을 요약해줘.',
      guardrail: 'Passed',
      rbac: 'Denied',
      llm: 'Skipped',
      docs: [],
      response:
        '요청한 문서는 현재 계정의 팀 권한으로 열람할 수 없습니다. Project Aurora 팀 권한이 필요한 문서입니다.',
      requestedResource: 'Project Aurora Runbook',
      requiredTeam: 'Project Aurora',
      userTeam: 'General Employee',
      cost: 0.0005,
      duration: 1.1,
      tokens: 140,
    },
    {
      suffix: '004',
      status: 'Error',
      title: 'Credential 오류 요청',
      input: '이번 달 보안 교육 신청 마감일 알려줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Failed',
      docs: ['보안 교육 운영 안내'],
      response:
        'LLM credential 호출 실패로 답변 생성이 완료되지 않았습니다. Credential 상태와 사용량 제한을 확인해야 합니다.',
      reason: 'llm_credential_rate_limited',
      cost: 0.0011,
      duration: 5.4,
      tokens: 420,
    },
    {
      suffix: '005',
      status: 'Completed',
      title: '정상 요청',
      input: '육아기 단축근무 신청 절차를 알려줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['육아기 근로시간 단축 안내', '인사 신청 매뉴얼'],
      response:
        '육아기 단축근무는 인사 시스템에서 신청서를 작성한 뒤 팀장 승인과 HR 검토를 거쳐 확정됩니다.',
      cost: 0.0036,
      duration: 2.7,
      tokens: 980,
    },
    {
      suffix: '006',
      status: 'Completed',
      title: '정상 요청',
      input: '재택근무 신청은 언제까지 해야 해?',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['재택근무 운영 정책'],
      response:
        '재택근무는 원칙적으로 근무 전일까지 신청해야 하며, 긴급한 경우 팀장 승인 후 예외 처리할 수 있습니다.',
      cost: 0.0029,
      duration: 2.1,
      tokens: 760,
    },
    {
      suffix: '007',
      status: 'Blocked',
      title: '가드레일 차단 요청',
      input: '관리자 API key를 로그에서 찾아내는 방법 알려줘.',
      guardrail: 'Denied',
      rbac: 'Not evaluated',
      llm: 'Skipped',
      docs: [],
      response:
        '민감한 인증 정보를 찾거나 노출하는 방법은 안내할 수 없습니다. 필요한 권한은 관리자 승인 절차를 통해 요청해 주세요.',
      reason: 'secret_exfiltration',
      cost: 0.0004,
      duration: 0.9,
      tokens: 120,
    },
    {
      suffix: '008',
      status: 'Denied',
      title: 'RBAC 차단 요청',
      input: '임원 보상 정책 문서를 요약해줘.',
      guardrail: 'Passed',
      rbac: 'Denied',
      llm: 'Skipped',
      docs: [],
      response:
        '요청한 문서는 현재 계정이 소속된 팀 권한으로 접근할 수 없습니다.',
      requestedResource: 'Executive Compensation Policy',
      requiredTeam: 'HR Leadership',
      userTeam: 'General Employee',
      cost: 0.0005,
      duration: 1.0,
      tokens: 130,
    },
    {
      suffix: '009',
      status: 'Completed',
      title: '정상 요청',
      input: '출장비 정산에 필요한 증빙 문서를 알려줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['출장비 정산 가이드', '회계 증빙 처리 기준'],
      response:
        '출장비 정산에는 영수증, 출장 신청 승인 내역, 교통비 사용 내역이 필요합니다.',
      cost: 0.0031,
      duration: 2.4,
      tokens: 840,
    },
    {
      suffix: '010',
      status: 'Completed',
      title: '정상 요청',
      input: '입사자 온보딩 체크리스트 보여줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['신규 입사자 온보딩 체크리스트'],
      response:
        '입사 첫 주에는 계정 발급, 보안 교육, 장비 수령, 팀 온보딩 미팅을 순서대로 진행합니다.',
      cost: 0.0027,
      duration: 2.0,
      tokens: 720,
    },
    {
      suffix: '011',
      status: 'Completed',
      title: '정상 요청',
      input: '법정 의무 교육 대상과 주기를 알려줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Completed',
      docs: ['법정 의무 교육 운영 안내'],
      response:
        '법정 의무 교육은 전 임직원이 대상이며, 과정별로 연 1회 또는 반기 1회 수강해야 합니다.',
      cost: 0.0033,
      duration: 2.8,
      tokens: 910,
    },
    {
      suffix: '012',
      status: 'Error',
      title: '검색 지연 요청',
      input: '지난 분기 전체 인사 규정 변경 사항을 정리해줘.',
      guardrail: 'Passed',
      rbac: 'Allowed',
      llm: 'Skipped',
      docs: ['인사 규정 개정 이력'],
      response:
        '지식 기반 검색 응답 시간이 초과되어 답변을 생성하지 못했습니다.',
      reason: 'knowledge_search_timeout',
      cost: 0.0008,
      duration: 6.2,
      tokens: 260,
    },
  ];

  return rows.map((row, index) => ({
    id: `mock_run_internal_search_${row.suffix}`,
    workflow_id: workflowId,
    app_id: appId,
    app_name: appName,
    user_id: index % 3 === 0 ? 'employee_002' : 'employee_001',
    status: row.status === 'Error' ? 'failed' : 'completed',
    trigger_mode: 'webhook',
    inputs: { message: row.input },
    outputs: {
      answer: row.response,
      demo_review: {
        scenario: 'admin_internal_search_review',
        is_mock_adapter: true,
        run_label: `run_internal_search_${row.suffix}`,
        title: row.title,
        status: row.status,
        user: index % 3 === 0 ? 'employee_002' : 'employee_001',
        input: row.input,
        guardrail: row.guardrail,
        rbac: row.rbac,
        llm_generation: row.llm,
        rag_search: row.docs.length > 0 ? 'Completed' : 'Skipped',
        retrieved_docs: row.docs,
        final_response: row.response,
        reason: row.reason,
        requested_resource: row.requestedResource,
        required_team: row.requiredTeam,
        user_team: row.userTeam,
        trace_id: `trace_internal_search_${row.suffix}`,
        trace_steps: traceByStatus(row.status),
        retrieved_chunks: chunksFor(row.docs),
        policy_decision:
          row.guardrail === 'Denied'
            ? 'DENY'
            : row.rbac === 'Denied'
              ? 'ALLOW'
              : row.status === 'Error'
                ? 'ERROR'
                : 'ALLOW',
        permission_decision:
          row.rbac === 'Denied'
            ? 'DENY'
            : row.rbac === 'Not evaluated'
              ? 'NOT_EVALUATED'
              : 'ALLOW',
        action:
          row.status === 'Blocked'
            ? 'Block response and return safe message'
            : row.status === 'Denied'
              ? 'Return access denied response'
              : row.status === 'Error'
                ? 'Raise admin alert'
                : 'Return grounded answer',
        model:
          row.status === 'Blocked' || row.status === 'Denied'
            ? '-'
            : 'gpt-4o-mini',
        input_tokens:
          row.status === 'Blocked' || row.status === 'Denied'
            ? Math.round(row.tokens * 0.65)
            : Math.round(row.tokens * 0.78),
        output_tokens:
          row.status === 'Blocked' || row.status === 'Denied'
            ? Math.round(row.tokens * 0.35)
            : Math.round(row.tokens * 0.22),
        guardrail_blocked: row.guardrail === 'Denied',
        answer_llm_skipped:
          row.llm === 'Skipped' ||
          row.status === 'Blocked' ||
          row.status === 'Denied',
        estimated_cost: `$${row.cost.toFixed(4)}`,
        latency: `${row.duration}s`,
      },
    },
    error_message: row.status === 'Error' ? row.reason || row.response : null,
    started_at: new Date(baseTime + index * 3 * 60 * 1000).toISOString(),
    finished_at: new Date(
      baseTime + index * 3 * 60 * 1000 + row.duration * 1000,
    ).toISOString(),
    duration: row.duration,
    total_tokens: row.tokens,
    total_cost: row.cost,
  }));
};

const buildMockKnowledgeBases = (
  organizationId: string,
): KnowledgeBaseResponse[] => [
  {
    id: 'mock-kb-hr-policy',
    organization_id: organizationId,
    name: 'HR Policy RAG',
    description: '휴가, 근태, 온보딩, 출장비 정산 정책 문서',
    document_count: 18,
    created_at: '2026-06-20T02:00:00.000Z',
    updated_at: '2026-07-01T02:30:00.000Z',
    source_types: ['FILE'],
    embedding_model: 'text-embedding-3-small',
  },
  {
    id: 'mock-kb-security-guide',
    organization_id: organizationId,
    name: 'Security Guide',
    description: '계정, 접근 권한, 보안 교육, credential 취급 기준',
    document_count: 9,
    created_at: '2026-06-22T04:10:00.000Z',
    updated_at: '2026-07-01T01:10:00.000Z',
    source_types: ['FILE'],
    embedding_model: 'text-embedding-3-small',
  },
  {
    id: 'mock-kb-project-restricted',
    organization_id: organizationId,
    name: 'Project Restricted Docs',
    description: '팀 권한이 필요한 프로젝트 운영 문서',
    document_count: 7,
    created_at: '2026-06-25T07:40:00.000Z',
    updated_at: '2026-06-30T08:30:00.000Z',
    source_types: ['FILE'],
    embedding_model: 'text-embedding-3-small',
  },
];

const buildMockAuditItems = (): AuditItem[] => {
  const baseTime = new Date('2026-07-01T03:10:00.000Z').getTime();
  const rows: Omit<AuditItem, 'id' | 'occurred_at'>[] = [
    {
      actor: 'employee_001',
      workflow: '사내 문서 통합 검색 어시스턴트',
      action: 'workflow.run',
      target_type: 'workflow_run',
      status: 'completed',
      policy: '-',
      decision: 'allow',
      trace_id: 'trace_internal_search_001',
      input: '가족돌봄휴가와 연차를 이어서 쓸 수 있는지 질문',
    },
    {
      actor: 'employee_001',
      workflow: '사내 문서 통합 검색 어시스턴트',
      action: 'workflow.run',
      target_type: 'workflow_run',
      status: 'blocked',
      policy: 'credential_or_access_bypass',
      decision: 'deny',
      trace_id: 'trace_internal_search_002',
      input: '퇴사자 계정으로 GitHub에 우회 접속하는 방법 알려줘.',
    },
    {
      actor: 'employee_001',
      workflow: '사내 문서 통합 검색 어시스턴트',
      action: 'workflow.run',
      target_type: 'workflow_run',
      status: 'denied',
      policy: 'rbac_required_team_project_aurora',
      decision: 'deny',
      trace_id: 'trace_internal_search_003',
      input: 'Project Aurora 출시 전 장애 대응 Runbook을 요약해줘.',
    },
    {
      actor: 'admin_001',
      workflow: '사내 문서 통합 검색 어시스턴트',
      action: 'workflow.update',
      target_type: 'workflow',
      status: 'success',
      policy: '-',
      decision: 'accepted',
      trace_id: 'trace_builder_change_001',
      change: 'Guardrail node inserted between Webhook Trigger and RAG LLM',
      source: 'AI Builder draft accepted',
    },
    {
      actor: 'system',
      workflow: 'Credential Usage Anomaly Alert',
      action: 'llm_credential.rate_limited',
      target_type: 'llm_credential',
      status: 'failure',
      policy: 'usage_spike_threshold',
      decision: 'alert',
      trace_id: 'trace_internal_search_004',
      input: 'OpenAI credential hourly usage check',
    },
    {
      actor: 'admin_001',
      workflow: 'Project Aurora Runbook Search',
      action: 'workflow.permission.granted',
      target_type: 'workflow_permission',
      status: 'success',
      policy: 'team_workflow_permission',
      decision: 'grant',
      trace_id: 'trace_permission_change_001',
      change: 'Project Aurora TF granted manager permission',
    },
  ];

  return rows.map((row, index) => ({
    ...row,
    id: `mock-audit-${String(index + 1).padStart(2, '0')}`,
    occurred_at: new Date(baseTime + index * 4 * 60 * 1000).toISOString(),
    target_id: `mock-target-${String(index + 1).padStart(2, '0')}`,
  }));
};

export default function AdminConsolePage() {
  const [activeTab, setActiveTab] = useState<AdminTab>('members');
  const [organization, setOrganization] = useState<OrganizationResponse | null>(
    null,
  );
  const [currentUserId, setCurrentUserId] = useState<string | null>(null);
  const [members, setMembers] = useState<OrganizationMember[]>([]);
  const [teams, setTeams] = useState<TeamResponse[]>([]);
  const [teamMembers, setTeamMembers] = useState<
    Record<string, TeamMemberResponse[]>
  >({});
  const [teamMemberLoadErrors, setTeamMemberLoadErrors] = useState<
    Record<string, boolean>
  >({});
  const [apps, setApps] = useState<AppResponse[]>([]);
  const [providers, setProviders] = useState<LLMProviderResponse[]>([]);
  const [credentials, setCredentials] = useState<LLMCredentialResponse[]>([]);
  const [knowledgeBases, setKnowledgeBases] = useState<KnowledgeBaseResponse[]>(
    [],
  );
  const [reviewRuns, setReviewRuns] = useState<AdminReviewRun[]>([]);
  const [workflowPermissions, setWorkflowPermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [credentialPermissions, setCredentialPermissions] =
    useState<ResourcePermissionListResponse | null>(null);
  const [auditItems, setAuditItems] = useState<AuditItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  const [memberQuery, setMemberQuery] = useState('');
  const [memberStateFilter, setMemberStateFilter] = useState<
    MembershipState | 'all'
  >('all');
  const [memberAuthFilter, setMemberAuthFilter] = useState<
    OrganizationAuthState | 'all'
  >('all');
  const [memberPage, setMemberPage] = useState(1);
  const [inviteOpen, setInviteOpen] = useState(false);
  const [inviteForm, setInviteForm] = useState({
    userId: '',
    authState: 'member' as OrganizationAuthState,
  });

  const [teamQuery, setTeamQuery] = useState('');
  const [teamStateFilter, setTeamStateFilter] = useState<
    'all' | 'active' | 'inactive'
  >('all');
  const [teamMemberFilter, setTeamMemberFilter] = useState<
    'all' | 'has_members' | 'empty'
  >('all');
  const [teamPage, setTeamPage] = useState(1);
  const [teamEditor, setTeamEditor] = useState<TeamEditorState | null>(null);
  const [teamForm, setTeamForm] = useState({
    name: '',
    description: '',
    isAutoAdd: false,
  });
  const [selectedTeamId, setSelectedTeamId] = useState<string | null>(null);
  const [teamMemberUserId, setTeamMemberUserId] = useState('');

  const [permissionResourceType, setPermissionResourceType] =
    useState<ResourceType>('workflow');
  const [selectedWorkflowId, setSelectedWorkflowId] = useState('');
  const [selectedCredentialId, setSelectedCredentialId] = useState('');
  const [permissionGranteeType, setPermissionGranteeType] =
    useState<GranteeType>('team');
  const [permissionGranteeId, setPermissionGranteeId] = useState('');
  const [permissionAuthState, setPermissionAuthState] =
    useState<ResourceAuthState>('viewer');

  const [credentialPanelOpen, setCredentialPanelOpen] = useState(false);
  const [credentialForm, setCredentialForm] = useState({
    providerId: '',
    credentialName: '',
    apiKey: '',
  });

  const [confirmState, setConfirmState] = useState<ConfirmState | null>(null);
  const [actionPending, setActionPending] = useState(false);

  const memberCounts = useMemo(
    () =>
      members.reduce<Record<MembershipState, number>>(
        (counts, member) => ({
          ...counts,
          [member.membership_state]: counts[member.membership_state] + 1,
        }),
        { invited: 0, active: 0, suspended: 0, removed: 0 },
      ),
    [members],
  );

  const activeMembers = useMemo(
    () => members.filter((member) => member.membership_state === 'active'),
    [members],
  );

  const activeTeams = useMemo(
    () => teams.filter((team) => team.is_active),
    [teams],
  );

  const workflowOptions = useMemo(
    () => apps.filter((app) => Boolean(app.workflow_id)),
    [apps],
  );

  const selectedPermissionList =
    permissionResourceType === 'workflow'
      ? workflowPermissions
      : credentialPermissions;

  const permissionResourceId =
    permissionResourceType === 'workflow'
      ? selectedWorkflowId
      : selectedCredentialId;

  const activeManagerCount = useMemo(
    () =>
      members.filter(
        (member) =>
          member.membership_state === 'active' &&
          member.organization_auth_state === 'manager',
      ).length,
    [members],
  );

  const adminRunSummary = useMemo(() => {
    const counts = reviewRuns.reduce(
      (acc, run) => {
        const status = reviewStatusOf(run);
        const review = reviewPayloadOf(run);
        if (status === 'Completed') acc.completed += 1;
        if (status === 'Blocked') acc.blocked += 1;
        if (status === 'Denied') acc.denied += 1;
        if (status === 'Error' || run.status === 'failed') acc.error += 1;
        if (review.guardrail === 'Denied') acc.guardrailDenied += 1;
        if (review.rbac === 'Denied') acc.rbacDenied += 1;
        acc.totalCost += reviewCostOf(run);
        acc.totalDuration += reviewDurationOf(run);
        acc.totalTokens += Number(run.total_tokens || 0);
        return acc;
      },
      {
        completed: 0,
        blocked: 0,
        denied: 0,
        error: 0,
        guardrailDenied: 0,
        rbacDenied: 0,
        totalCost: 0,
        totalDuration: 0,
        totalTokens: 0,
      },
    );

    return {
      ...counts,
      total: reviewRuns.length,
      averageDuration:
        reviewRuns.length > 0 ? counts.totalDuration / reviewRuns.length : 0,
    };
  }, [reviewRuns]);

  const filteredMembers = useMemo(() => {
    const query = normalizeText(memberQuery);
    return [...members]
      .filter((member) => {
        if (
          memberStateFilter !== 'all' &&
          member.membership_state !== memberStateFilter
        ) {
          return false;
        }
        if (
          memberAuthFilter !== 'all' &&
          member.organization_auth_state !== memberAuthFilter
        ) {
          return false;
        }
        if (!query) return true;
        return (
          normalizeText(member.user_name).includes(query) ||
          normalizeText(member.user_email).includes(query)
        );
      })
      .sort((left, right) => {
        const stateDiff =
          stateOrder[left.membership_state] -
          stateOrder[right.membership_state];
        if (stateDiff !== 0) return stateDiff;
        return left.user_name.localeCompare(right.user_name);
      });
  }, [memberAuthFilter, memberQuery, memberStateFilter, members]);

  const filteredTeams = useMemo(() => {
    const query = normalizeText(teamQuery);
    return teams
      .filter((team) => {
        if (teamStateFilter === 'active' && !team.is_active) return false;
        if (teamStateFilter === 'inactive' && team.is_active) return false;
        const memberLoadFailed = teamMemberLoadErrors[team.id] === true;
        const count = teamMembers[team.id]?.length || 0;
        if (memberLoadFailed && teamMemberFilter !== 'all') return false;
        if (teamMemberFilter === 'has_members' && count === 0) return false;
        if (teamMemberFilter === 'empty' && count > 0) return false;
        if (!query) return true;
        return (
          normalizeText(team.name).includes(query) ||
          normalizeText(team.description).includes(query)
        );
      })
      .sort((left, right) => {
        if (left.is_active !== right.is_active) return left.is_active ? -1 : 1;
        return left.name.localeCompare(right.name);
      });
  }, [
    teamMemberFilter,
    teamMemberLoadErrors,
    teamMembers,
    teamQuery,
    teamStateFilter,
    teams,
  ]);

  const selectedTeam = useMemo(
    () => teams.find((team) => team.id === selectedTeamId) || null,
    [selectedTeamId, teams],
  );

  const selectedTeamMemberUserIds = useMemo(
    () =>
      (selectedTeamId ? teamMembers[selectedTeamId] || [] : []).map(
        (member) => member.user_id,
      ),
    [selectedTeamId, teamMembers],
  );

  const loadTeamMembers = async (items: TeamResponse[]) => {
    const entries = await Promise.all(
      items.map(async (team) => {
        try {
          const response = await apiClient.get<TeamMemberResponse[]>(
            `/teams/${team.id}/members`,
          );
          return [team.id, response.data, false] as const;
        } catch {
          return [team.id, [], true] as const;
        }
      }),
    );
    setTeamMembers(
      entries.reduce<Record<string, TeamMemberResponse[]>>(
        (acc, [teamId, items]) => ({ ...acc, [teamId]: [...items] }),
        {},
      ),
    );
    setTeamMemberLoadErrors(
      Object.fromEntries(
        entries
          .filter(([, , failed]) => failed)
          .map(([teamId]) => [teamId, true]),
      ),
    );
  };

  const loadPermissions = async (
    resourceType = permissionResourceType,
    workflowId = selectedWorkflowId,
    credentialId = selectedCredentialId,
  ) => {
    try {
      if (resourceType === 'workflow' && workflowId) {
        const response = await apiClient.get<ResourcePermissionListResponse>(
          `/permissions/workflows/${workflowId}`,
        );
        setWorkflowPermissions(response.data);
        return;
      }
      if (resourceType === 'llm_credential' && credentialId) {
        const response = await apiClient.get<ResourcePermissionListResponse>(
          `/permissions/llm-credentials/${credentialId}`,
        );
        setCredentialPermissions(response.data);
        return;
      }
      if (resourceType === 'workflow') setWorkflowPermissions(null);
      if (resourceType === 'llm_credential') setCredentialPermissions(null);
    } catch (err) {
      toast.error(getErrorMessage(err, '권한 목록을 불러오지 못했습니다.'));
      if (resourceType === 'workflow') setWorkflowPermissions(null);
      if (resourceType === 'llm_credential') setCredentialPermissions(null);
    }
  };

  const refreshCredentials = async () => {
    const response =
      await apiClient.get<LLMCredentialResponse[]>('/llm/credentials');
    setCredentials(response.data);
    return response.data;
  };

  const loadAdminReviewRuns = async (
    appData: AppResponse[],
  ): Promise<AdminReviewRun[]> => {
    const workflowApps = appData.filter((app) => Boolean(app.workflow_id));
    const batches = await Promise.all(
      workflowApps.map(async (app) => {
        try {
          const response = await apiClient.get<{ items: WorkflowRunSummary[] }>(
            `/workflows/${app.workflow_id}/runs`,
            { params: { page: 1, limit: 10 } },
          );
          return response.data.items.map((run) => ({
            ...run,
            app_name: app.name,
          }));
        } catch {
          return [];
        }
      }),
    );

    const reviewRuns = batches
      .flat()
      .filter((run) => {
        const review = run.outputs?.demo_review as
          Record<string, unknown> | undefined;
        return review?.scenario === 'admin_internal_search_review';
      })
      .sort(
        (left, right) =>
          new Date(left.started_at).getTime() -
          new Date(right.started_at).getTime(),
      );

    return reviewRuns.length > 0
      ? reviewRuns
      : buildMockAdminReviewRuns(appData);
  };

  const loadData = async () => {
    setLoading(true);
    setError(null);
    try {
      const [org, me] = await Promise.all([
        organizationApi.getCurrentOrganization(),
        authApi.me().catch(() => null),
      ]);
      setOrganization(org);
      setCurrentUserId(me?.user.id || null);

      if (!org.is_manager) {
        setMembers([]);
        setTeams([]);
        setTeamMembers({});
        setTeamMemberLoadErrors({});
        setApps([]);
        setProviders([]);
        setCredentials([]);
        setWorkflowPermissions(null);
        setCredentialPermissions(null);
        setKnowledgeBases([]);
        setReviewRuns([]);
        setAuditItems([]);
        return;
      }

      const [defaultMembers, removedMembers, teamData] = await Promise.all([
        organizationApi.listMembers(org.id),
        organizationApi.listMembers(org.id, 'removed').catch(() => []),
        apiClient
          .get<TeamResponse[]>('/teams', {
            params: { organization_id: org.id, limit: 100 },
          })
          .then((response) => response.data),
      ]);

      setMembers(uniqueMembers([...defaultMembers, ...removedMembers]));
      setTeams(teamData);

      const [providerData, credentialData, appData, knowledgeData, auditData] =
        await Promise.all([
          apiClient
            .get<LLMProviderResponse[]>('/llm/providers')
            .then((response) => response.data)
            .catch(() => []),
          apiClient
            .get<LLMCredentialResponse[]>('/llm/credentials')
            .then((response) => response.data)
            .catch(() => []),
          apiClient
            .get<AppResponse[]>('/apps')
            .then((response) => response.data)
            .catch(() => []),
          knowledgeApi.getKnowledgeBases().catch(() => []),
          apiClient
            .get<{ items: AuditItem[] }>('/users/me/audit-logs', {
              params: { limit: 30 },
            })
            .then((response) => response.data.items || [])
            .catch(() => []),
        ]);

      setProviders(providerData);
      setCredentials(credentialData);
      setApps(appData);
      setKnowledgeBases(
        knowledgeData.length > 0
          ? knowledgeData
          : buildMockKnowledgeBases(org.id),
      );
      setAuditItems(
        auditData.length > 0
          ? [...buildMockAuditItems(), ...auditData]
          : buildMockAuditItems(),
      );
      setReviewRuns(await loadAdminReviewRuns(appData));
      const firstWorkflowId =
        selectedWorkflowId ||
        appData.find((app) => app.workflow_id)?.workflow_id ||
        '';
      const firstCredentialId =
        selectedCredentialId || credentialData[0]?.id || '';
      setSelectedWorkflowId(firstWorkflowId);
      setSelectedCredentialId(firstCredentialId);
      await Promise.all([
        loadPermissions('workflow', firstWorkflowId, firstCredentialId),
        loadPermissions('llm_credential', firstWorkflowId, firstCredentialId),
      ]);
      await loadTeamMembers(teamData);
    } catch (err) {
      setError(getErrorMessage(err, '관리 콘솔 데이터를 불러오지 못했습니다.'));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    loadData();
    window.addEventListener(ACTIVE_ORGANIZATION_CHANGED_EVENT, loadData);
    return () =>
      window.removeEventListener(ACTIVE_ORGANIZATION_CHANGED_EVENT, loadData);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    setMemberPage(1);
  }, [memberAuthFilter, memberQuery, memberStateFilter]);

  useEffect(() => {
    setTeamPage(1);
  }, [teamMemberFilter, teamQuery, teamStateFilter]);

  useEffect(() => {
    if (!selectedTeamId) return;
    const nextCandidate = activeMembers.find(
      (member) => !selectedTeamMemberUserIds.includes(member.user_id),
    );
    setTeamMemberUserId(nextCandidate?.user_id || '');
  }, [activeMembers, selectedTeamId, selectedTeamMemberUserIds]);

  useEffect(() => {
    if (!selectedWorkflowId && workflowOptions.length > 0) {
      setSelectedWorkflowId(workflowOptions[0].workflow_id || '');
    }
  }, [selectedWorkflowId, workflowOptions]);

  useEffect(() => {
    if (!selectedCredentialId && credentials.length > 0) {
      setSelectedCredentialId(credentials[0].id);
    }
  }, [credentials, selectedCredentialId]);

  useEffect(() => {
    if (!credentialForm.providerId && providers.length > 0) {
      setCredentialForm((prev) => ({ ...prev, providerId: providers[0].id }));
    }
  }, [credentialForm.providerId, providers]);

  useEffect(() => {
    if (permissionGranteeType === 'team') {
      const currentTeam = activeTeams.some(
        (team) => team.id === permissionGranteeId,
      );
      if (!currentTeam) setPermissionGranteeId(activeTeams[0]?.id || '');
      return;
    }
    const currentMember = activeMembers.some(
      (member) => member.user_id === permissionGranteeId,
    );
    if (!currentMember) setPermissionGranteeId(activeMembers[0]?.user_id || '');
  }, [activeMembers, activeTeams, permissionGranteeId, permissionGranteeType]);

  useEffect(() => {
    if (!organization?.is_manager) return;
    loadPermissions(permissionResourceType);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [
    organization?.is_manager,
    permissionResourceType,
    selectedWorkflowId,
    selectedCredentialId,
  ]);

  const refreshMembers = async () => {
    if (!organization) return;
    const [defaultMembers, removedMembers] = await Promise.all([
      organizationApi.listMembers(organization.id),
      organizationApi.listMembers(organization.id, 'removed').catch(() => []),
    ]);
    setMembers(uniqueMembers([...defaultMembers, ...removedMembers]));
  };

  const refreshTeams = async () => {
    const response = await apiClient.get<TeamResponse[]>('/teams', {
      params: { organization_id: organization?.id, limit: 100 },
    });
    setTeams(response.data);
    await loadTeamMembers(response.data);
  };

  const refreshTeamMember = async (teamId: string) => {
    try {
      const response = await apiClient.get<TeamMemberResponse[]>(
        `/teams/${teamId}/members`,
      );
      setTeamMembers((prev) => ({ ...prev, [teamId]: response.data }));
      setTeamMemberLoadErrors((prev) => {
        const next = { ...prev };
        delete next[teamId];
        return next;
      });
    } catch {
      setTeamMemberLoadErrors((prev) => ({ ...prev, [teamId]: true }));
    }
  };

  const runAction = async (action: () => Promise<void>) => {
    setActionPending(true);
    try {
      await action();
      return true;
    } catch (err) {
      toast.error(getErrorMessage(err, '작업에 실패했습니다.'));
      return false;
    } finally {
      setActionPending(false);
    }
  };

  const openConfirm = (state: ConfirmState) => setConfirmState(state);

  const handleConfirm = async () => {
    if (!confirmState) return;
    const success = await runAction(confirmState.onConfirm);
    if (success) {
      setConfirmState(null);
    }
  };

  const updateMember = async (
    member: OrganizationMember,
    payload: Parameters<typeof organizationApi.updateMember>[2],
    successMessage: string,
  ) => {
    if (!organization) return;
    await organizationApi.updateMember(
      organization.id,
      member.user_id,
      payload,
    );
    toast.success(successMessage);
    await refreshMembers();
  };

  const removeMember = async (member: OrganizationMember) => {
    if (!organization) return;
    const result = await organizationApi.removeMember(
      organization.id,
      member.user_id,
    );
    const summary = removeSummary(result);
    setNotice(summary);
    toast.success(summary);
    await Promise.all([refreshMembers(), refreshTeams()]);
  };

  const submitInvite = async () => {
    if (!organization || !inviteForm.userId.trim()) return;
    await runAction(async () => {
      await organizationApi.inviteMember(organization.id, {
        user_id: inviteForm.userId.trim(),
        organization_auth_state: inviteForm.authState,
      });
      toast.success('멤버 초대를 생성했습니다.');
      setInviteOpen(false);
      setInviteForm({ userId: '', authState: 'member' });
      await refreshMembers();
    });
  };

  const openTeamEditor = (state: TeamEditorState) => {
    setTeamEditor(state);
    setTeamForm({
      name: state.team?.name || '',
      description: state.team?.description || '',
      isAutoAdd: state.team?.is_auto_add || false,
    });
  };

  const submitTeamForm = async () => {
    if (!teamForm.name.trim()) return;
    await runAction(async () => {
      if (teamEditor?.mode === 'edit') {
        await apiClient.patch(`/teams/${teamEditor.team.id}`, {
          name: teamForm.name.trim(),
          description: teamForm.description.trim() || null,
          is_auto_add: teamForm.isAutoAdd,
        });
        toast.success('팀을 수정했습니다.');
      } else {
        await apiClient.post('/teams', {
          name: teamForm.name.trim(),
          description: teamForm.description.trim() || null,
          is_auto_add: teamForm.isAutoAdd,
        });
        toast.success('팀을 생성했습니다.');
      }
      setTeamEditor(null);
      await refreshTeams();
    });
  };

  const deactivateTeam = async (team: TeamResponse) => {
    await apiClient.delete(`/teams/${team.id}`);
    toast.success('팀을 비활성화했습니다.');
    await refreshTeams();
  };

  const addTeamMember = async () => {
    if (!selectedTeamId || !teamMemberUserId) return;
    await runAction(async () => {
      await apiClient.post(`/teams/${selectedTeamId}/members`, {
        user_id: teamMemberUserId,
      });
      toast.success('팀 멤버를 추가했습니다.');
      await refreshTeamMember(selectedTeamId);
    });
  };

  const removeTeamMember = async (
    teamId: string,
    member: TeamMemberResponse,
  ) => {
    await apiClient.delete(`/teams/${teamId}/members/${member.user_id}`);
    toast.success('팀 멤버를 제거했습니다.');
    await refreshTeamMember(teamId);
  };

  const permissionPath = (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    const resourceId =
      resourceType === 'workflow' ? selectedWorkflowId : selectedCredentialId;
    const resourcePath =
      resourceType === 'workflow'
        ? `/permissions/workflows/${resourceId}`
        : `/permissions/llm-credentials/${resourceId}`;
    return `${resourcePath}/${granteeType}s/${granteeId}`;
  };

  const grantPermission = async () => {
    if (!permissionResourceId || !permissionGranteeId) return;
    await runAction(async () => {
      await apiClient.put(
        permissionPath(
          permissionResourceType,
          permissionGranteeType,
          permissionGranteeId,
        ),
        { auth_state: permissionAuthState },
      );
      toast.success('권한을 저장했습니다.');
      await loadPermissions(permissionResourceType);
    });
  };

  const revokePermission = async (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
  ) => {
    await apiClient.delete(
      permissionPath(resourceType, granteeType, granteeId),
    );
    toast.success('권한을 회수했습니다.');
    await loadPermissions(resourceType);
  };

  const submitCredential = async () => {
    if (
      !organization ||
      !credentialForm.providerId ||
      !credentialForm.credentialName.trim() ||
      !credentialForm.apiKey.trim()
    ) {
      return;
    }
    await runAction(async () => {
      await apiClient.post('/llm/credentials', {
        provider_id: credentialForm.providerId,
        organization_id: organization.id,
        credential_name: credentialForm.credentialName.trim(),
        api_key: credentialForm.apiKey.trim(),
      });
      toast.success('Credential을 등록했습니다.');
      setCredentialPanelOpen(false);
      setCredentialForm({
        providerId: providers[0]?.id || '',
        credentialName: '',
        apiKey: '',
      });
      const nextCredentials = await refreshCredentials();
      const nextCredentialId = nextCredentials[0]?.id || '';
      setSelectedCredentialId(nextCredentialId);
      await loadPermissions(
        'llm_credential',
        selectedWorkflowId,
        nextCredentialId,
      );
    });
  };

  const deleteCredential = async (credential: LLMCredentialResponse) => {
    await apiClient.delete(`/llm/credentials/${credential.id}`);
    toast.success('Credential을 삭제했습니다.');
    const nextCredentials = await refreshCredentials();
    const nextCredentialId =
      selectedCredentialId === credential.id
        ? nextCredentials[0]?.id || ''
        : selectedCredentialId;
    setSelectedCredentialId(nextCredentialId);
    await loadPermissions(
      'llm_credential',
      selectedWorkflowId,
      nextCredentialId,
    );
  };

  const syncCredentialModels = async (credential: LLMCredentialResponse) => {
    await apiClient.post(`/llm/credentials/${credential.id}/sync-models`);
    toast.success('모델 목록을 동기화했습니다.');
    await refreshCredentials();
  };

  if (!loading && organization && !organization.is_manager) {
    return (
      <AdminShell
        organization={organization}
        onRefresh={loadData}
        badge={<OrganizationAuthBadge state="member" />}
      >
        <DashboardPanel title="관리 권한 없음" icon={Lock}>
          <div className="px-6 py-12 text-sm text-slate-600">
            현재 조직의 관리자만 이 화면에 접근할 수 있습니다. 멤버 계정에서는
            사이드바의 관리 메뉴가 표시되지 않아야 합니다.
          </div>
        </DashboardPanel>
      </AdminShell>
    );
  }

  return (
    <AdminShell
      organization={organization}
      onRefresh={loadData}
      badge={
        organization && (
          <OrganizationAuthBadge
            state={organization.is_manager ? 'manager' : 'member'}
          />
        )
      }
    >
      {error && (
        <div className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700">
          {error}
        </div>
      )}
      {notice && (
        <div className="flex items-start justify-between gap-3 rounded-md border border-green-200 bg-green-50 px-4 py-3 text-sm text-green-800">
          <span>{notice}</span>
          <button
            onClick={() => setNotice(null)}
            className="rounded p-0.5 text-green-700 hover:bg-green-100"
            title="알림 닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
      )}

      {loading ? (
        <div className="rounded-lg border border-slate-200 bg-white px-6 py-16 text-center text-sm text-slate-500">
          관리 콘솔을 불러오는 중...
        </div>
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <DashboardSummaryCard
              label="실행 검토"
              value={adminRunSummary.total}
              icon={Activity}
              description={`완료 ${adminRunSummary.completed} · 차단 ${adminRunSummary.blocked} · 거절 ${adminRunSummary.denied}`}
            />
            <DashboardSummaryCard
              label="차단/오류"
              value={
                adminRunSummary.blocked +
                adminRunSummary.denied +
                adminRunSummary.error
              }
              icon={AlertTriangle}
              description={`가드레일 ${adminRunSummary.guardrailDenied} · RBAC ${adminRunSummary.rbacDenied} · 오류 ${adminRunSummary.error}`}
            />
            <DashboardSummaryCard
              label="비용/응답"
              value={`$${adminRunSummary.totalCost.toFixed(4)}`}
              icon={Key}
              description={`평균 ${adminRunSummary.averageDuration.toFixed(1)}s · 토큰 ${adminRunSummary.totalTokens.toLocaleString()}`}
            />
            <DashboardSummaryCard
              label="조직 구성"
              value={`${memberCounts.active}/${activeTeams.length}`}
              icon={Users}
              description={`활성 멤버/팀 · Credential ${credentials.length} · 지식 ${knowledgeBases.length}`}
            />
          </div>

          <div className="border-b border-slate-200">
            <nav className="-mb-px flex gap-5 overflow-x-auto">
              {tabs.map((tab) => (
                <button
                  key={tab.key}
                  onClick={() => setActiveTab(tab.key)}
                  className={`whitespace-nowrap border-b-2 px-1 pb-3 text-sm font-semibold ${
                    activeTab === tab.key
                      ? 'border-slate-950 text-slate-950'
                      : 'border-transparent text-slate-500 hover:text-slate-800'
                  }`}
                >
                  {tab.label}
                </button>
              ))}
            </nav>
          </div>

          {activeTab === 'members' && (
            <MembersTab
              members={filteredMembers}
              page={memberPage}
              onPageChange={setMemberPage}
              query={memberQuery}
              onQueryChange={setMemberQuery}
              stateFilter={memberStateFilter}
              onStateFilterChange={setMemberStateFilter}
              authFilter={memberAuthFilter}
              onAuthFilterChange={setMemberAuthFilter}
              onInvite={() => setInviteOpen(true)}
              currentUserId={currentUserId}
              activeManagerCount={activeManagerCount}
              actionPending={actionPending}
              onUpdateMember={(member, payload, message) =>
                payload.organization_auth_state
                  ? openConfirm({
                      title:
                        payload.organization_auth_state === 'manager'
                          ? '관리자로 승격할까요?'
                          : '멤버로 강등할까요?',
                      description:
                        payload.organization_auth_state === 'manager'
                          ? '이 사용자는 조직 멤버와 팀, 권한 관리 화면에 접근할 수 있습니다.'
                          : '이 사용자는 더 이상 조직 관리 화면에 접근할 수 없습니다.',
                      confirmLabel:
                        payload.organization_auth_state === 'manager'
                          ? '승격'
                          : '강등',
                      details: [`${member.user_name} (${member.user_email})`],
                      onConfirm: () => updateMember(member, payload, message),
                    })
                  : runAction(() => updateMember(member, payload, message))
              }
              onRemoveMember={(member) =>
                openConfirm({
                  title: '멤버를 제거할까요?',
                  description:
                    '멤버를 제거하면 팀 배정과 직접 권한이 함께 정리됩니다.',
                  confirmLabel: '제거',
                  tone: 'danger',
                  details: [
                    `${member.user_name} (${member.user_email})`,
                    '팀 멤버십, workflow 직접 권한, LLM credential 직접 권한 cleanup이 실행됩니다.',
                  ],
                  onConfirm: () => removeMember(member),
                })
              }
            />
          )}
          {activeTab === 'teams' && (
            <TeamsTab
              teams={filteredTeams}
              page={teamPage}
              onPageChange={setTeamPage}
              query={teamQuery}
              onQueryChange={setTeamQuery}
              stateFilter={teamStateFilter}
              onStateFilterChange={setTeamStateFilter}
              memberFilter={teamMemberFilter}
              onMemberFilterChange={setTeamMemberFilter}
              teamMembers={teamMembers}
              teamMemberLoadErrors={teamMemberLoadErrors}
              isLimited={teams.length >= 100}
              onCreateTeam={() => openTeamEditor({ mode: 'create' })}
              onEditTeam={(team) => openTeamEditor({ mode: 'edit', team })}
              onDeactivateTeam={(team) =>
                openConfirm({
                  title: '팀을 비활성화할까요?',
                  description:
                    '팀은 삭제되지 않고 비활성 상태가 됩니다. 비활성 팀에는 멤버 추가와 권한 부여를 하지 않습니다.',
                  confirmLabel: '비활성화',
                  tone: 'danger',
                  details: [
                    team.name,
                    `현재 멤버 ${teamMembers[team.id]?.length || 0}명`,
                  ],
                  onConfirm: () => deactivateTeam(team),
                })
              }
              onOpenTeam={setSelectedTeamId}
            />
          )}
          {activeTab === 'permissions' && (
            <PermissionsTab
              resourceType={permissionResourceType}
              onResourceTypeChange={setPermissionResourceType}
              workflowOptions={workflowOptions}
              selectedWorkflowId={selectedWorkflowId}
              onSelectedWorkflowIdChange={setSelectedWorkflowId}
              credentials={credentials}
              selectedCredentialId={selectedCredentialId}
              onSelectedCredentialIdChange={setSelectedCredentialId}
              activeTeams={activeTeams}
              activeMembers={activeMembers}
              granteeType={permissionGranteeType}
              onGranteeTypeChange={setPermissionGranteeType}
              granteeId={permissionGranteeId}
              onGranteeIdChange={setPermissionGranteeId}
              authState={permissionAuthState}
              onAuthStateChange={setPermissionAuthState}
              permissionList={selectedPermissionList}
              actionPending={actionPending}
              onGrant={grantPermission}
              onRevoke={(resourceType, granteeType, granteeId, label) =>
                openConfirm({
                  title: '권한을 회수할까요?',
                  description: '선택한 대상의 resource 권한이 제거됩니다.',
                  confirmLabel: '회수',
                  tone: 'danger',
                  details: [label],
                  onConfirm: () =>
                    revokePermission(resourceType, granteeType, granteeId),
                })
              }
            />
          )}
          {activeTab === 'credentials' && (
            <CredentialsTab
              providers={providers}
              credentials={credentials}
              actionPending={actionPending}
              onOpenCreate={() => setCredentialPanelOpen(true)}
              onManagePermission={(credentialId) => {
                setSelectedCredentialId(credentialId);
                setPermissionResourceType('llm_credential');
                setActiveTab('permissions');
              }}
              onSync={(credential) =>
                runAction(() => syncCredentialModels(credential))
              }
              onDelete={(credential) =>
                openConfirm({
                  title: 'Credential을 삭제할까요?',
                  description:
                    '삭제 후 이 credential을 사용하는 workflow 실행이 실패할 수 있습니다.',
                  confirmLabel: '삭제',
                  tone: 'danger',
                  details: [credential.credential_name],
                  onConfirm: () => deleteCredential(credential),
                })
              }
            />
          )}
          {activeTab === 'knowledge' && (
            <KnowledgeTab knowledgeBases={knowledgeBases} />
          )}
          {activeTab === 'runReview' && (
            <RunReviewTab reviewRuns={reviewRuns} />
          )}
          {activeTab === 'audit' && <AuditTab auditItems={auditItems} />}
          {activeTab === 'organization' && (
            <OrganizationTab organization={organization} />
          )}
        </>
      )}

      {inviteOpen && (
        <SidePanel title="멤버 초대" onClose={() => setInviteOpen(false)}>
          <div className="space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
              현재 API는 가입된 user id만 초대할 수 있습니다. email 검색 초대는
              별도 user directory API가 필요합니다. 가입 user UUID는 DB 또는
              관리 도구에서 확인해야 합니다.
            </div>
            <LabelledField label="User ID">
              <input
                value={inviteForm.userId}
                onChange={(event) =>
                  setInviteForm((prev) => ({
                    ...prev,
                    userId: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="초대할 가입 user UUID"
              />
            </LabelledField>
            <LabelledField label="조직 권한">
              <select
                value={inviteForm.authState}
                onChange={(event) =>
                  setInviteForm((prev) => ({
                    ...prev,
                    authState: event.target.value as OrganizationAuthState,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
              >
                {AUTH_STATES.map((state) => (
                  <option key={state} value={state}>
                    {state === 'manager' ? '관리자' : '멤버'}
                  </option>
                ))}
              </select>
            </LabelledField>
            <PanelActions
              onCancel={() => setInviteOpen(false)}
              onSubmit={submitInvite}
              submitLabel="초대"
              disabled={!inviteForm.userId.trim() || actionPending}
            />
          </div>
        </SidePanel>
      )}

      {teamEditor && (
        <SidePanel
          title={teamEditor.mode === 'edit' ? '팀 수정' : '팀 생성'}
          onClose={() => setTeamEditor(null)}
        >
          <div className="space-y-4">
            <LabelledField label="팀 이름">
              <input
                value={teamForm.name}
                onChange={(event) =>
                  setTeamForm((prev) => ({ ...prev, name: event.target.value }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="팀 이름"
              />
            </LabelledField>
            <LabelledField label="설명">
              <textarea
                value={teamForm.description}
                onChange={(event) =>
                  setTeamForm((prev) => ({
                    ...prev,
                    description: event.target.value,
                  }))
                }
                className="min-h-24 w-full rounded-md border border-slate-300 px-3 py-2 text-sm"
                placeholder="팀 설명"
              />
            </LabelledField>
            <label className="flex items-center gap-2 text-sm text-slate-700">
              <input
                type="checkbox"
                checked={teamForm.isAutoAdd}
                onChange={(event) =>
                  setTeamForm((prev) => ({
                    ...prev,
                    isAutoAdd: event.target.checked,
                  }))
                }
              />
              신규 멤버 자동 추가
            </label>
            <PanelActions
              onCancel={() => setTeamEditor(null)}
              onSubmit={submitTeamForm}
              submitLabel={teamEditor.mode === 'edit' ? '수정' : '생성'}
              disabled={!teamForm.name.trim() || actionPending}
            />
          </div>
        </SidePanel>
      )}

      {selectedTeam && (
        <SidePanel
          title={selectedTeam.name}
          onClose={() => setSelectedTeamId(null)}
        >
          <div className="space-y-5">
            <div>
              <div className="flex items-center gap-2">
                <span
                  className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                    selectedTeam.is_active
                      ? 'bg-green-50 text-green-700'
                      : 'bg-slate-100 text-slate-600'
                  }`}
                >
                  {selectedTeam.is_active ? '활성' : '비활성'}
                </span>
                <span className="text-xs text-slate-500">
                  멤버 {teamMembers[selectedTeam.id]?.length || 0}명
                </span>
              </div>
              <p className="mt-2 text-sm leading-6 text-slate-600">
                {selectedTeam.description || '설명 없음'}
              </p>
            </div>

            {selectedTeam.is_active ? (
              <div className="rounded-md border border-slate-200 p-3">
                <p className="mb-2 text-sm font-semibold text-slate-900">
                  멤버 추가
                </p>
                <div className="grid gap-2 sm:grid-cols-[1fr_auto]">
                  <ActiveOrganizationMemberPicker
                    members={activeMembers}
                    value={teamMemberUserId}
                    onChange={setTeamMemberUserId}
                    excludedUserIds={selectedTeamMemberUserIds}
                    emptyLabel="추가 가능한 활성 멤버 없음"
                  />
                  <button
                    onClick={addTeamMember}
                    disabled={!teamMemberUserId || actionPending}
                    className="h-10 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white disabled:cursor-not-allowed disabled:opacity-40"
                  >
                    추가
                  </button>
                </div>
              </div>
            ) : (
              <div className="rounded-md border border-slate-200 bg-slate-50 px-3 py-2 text-sm text-slate-600">
                비활성 팀에는 멤버를 추가할 수 없습니다.
              </div>
            )}

            <div>
              <p className="mb-2 text-sm font-semibold text-slate-900">
                팀 멤버
              </p>
              {teamMemberLoadErrors[selectedTeam.id] ? (
                <div className="rounded-md border border-red-200 bg-red-50 px-3 py-2 text-sm text-red-700">
                  멤버를 불러오지 못했습니다.
                </div>
              ) : (teamMembers[selectedTeam.id] || []).length === 0 ? (
                <div className="rounded-md border border-slate-200 px-3 py-6 text-center text-sm text-slate-500">
                  소속 멤버가 없습니다.
                </div>
              ) : (
                <div className="divide-y divide-slate-100 rounded-md border border-slate-200">
                  {(teamMembers[selectedTeam.id] || []).map((member) => (
                    <div
                      key={member.id}
                      className="flex items-center justify-between gap-3 px-3 py-2"
                    >
                      <div className="min-w-0">
                        <p className="truncate text-sm font-semibold text-slate-900">
                          {member.name}
                        </p>
                        <p className="truncate text-xs text-slate-500">
                          {member.email}
                        </p>
                      </div>
                      <button
                        onClick={() =>
                          openConfirm({
                            title: '팀 멤버를 제거할까요?',
                            description:
                              '이 작업은 organization membership을 제거하지 않고 팀 배정만 제거합니다.',
                            confirmLabel: '제거',
                            tone: 'danger',
                            details: [`${member.name} (${member.email})`],
                            onConfirm: () =>
                              removeTeamMember(selectedTeam.id, member),
                          })
                        }
                        className="rounded-md border border-slate-200 p-2 text-slate-500 hover:border-red-200 hover:bg-red-50 hover:text-red-700"
                        title="팀 멤버 제거"
                      >
                        <Trash2 className="h-4 w-4" />
                      </button>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </div>
        </SidePanel>
      )}

      {credentialPanelOpen && (
        <SidePanel
          title="Credential 등록"
          onClose={() => setCredentialPanelOpen(false)}
        >
          <div className="space-y-4">
            <div className="rounded-md border border-amber-200 bg-amber-50 px-3 py-2 text-sm leading-6 text-amber-800">
              API key 원문은 저장 후 다시 표시하지 않습니다. 조직에서 사용할
              provider와 식별 가능한 이름을 함께 입력하세요.
            </div>
            <LabelledField label="Provider">
              <select
                value={credentialForm.providerId}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    providerId: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
              >
                {providers.map((provider) => (
                  <option key={provider.id} value={provider.id}>
                    {provider.name}
                  </option>
                ))}
              </select>
            </LabelledField>
            <LabelledField label="Credential 이름">
              <input
                value={credentialForm.credentialName}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    credentialName: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="예: OpenAI 운영 키"
              />
            </LabelledField>
            <LabelledField label="API Key">
              <input
                value={credentialForm.apiKey}
                onChange={(event) =>
                  setCredentialForm((prev) => ({
                    ...prev,
                    apiKey: event.target.value,
                  }))
                }
                className="h-10 w-full rounded-md border border-slate-300 px-3 text-sm"
                placeholder="sk-..."
                type="password"
              />
            </LabelledField>
            <PanelActions
              onCancel={() => setCredentialPanelOpen(false)}
              onSubmit={submitCredential}
              submitLabel="등록"
              disabled={
                actionPending ||
                !credentialForm.providerId ||
                !credentialForm.credentialName.trim() ||
                !credentialForm.apiKey.trim()
              }
            />
          </div>
        </SidePanel>
      )}

      {confirmState && (
        <ConfirmDialog
          state={confirmState}
          pending={actionPending}
          onCancel={() => setConfirmState(null)}
          onConfirm={handleConfirm}
        />
      )}
    </AdminShell>
  );
}

const removeSummary = (result: OrganizationMemberRemoveResponse) =>
  `멤버를 제거했습니다. 팀 ${result.removed_team_memberships}건, workflow ${result.revoked_user_permissions.workflow}건, credential ${result.revoked_user_permissions.llm_credential}건을 정리했습니다.`;

function AdminShell({
  organization,
  badge,
  onRefresh,
  children,
}: {
  organization: OrganizationResponse | null;
  badge?: React.ReactNode;
  onRefresh: () => void;
  children: React.ReactNode;
}) {
  return (
    <div className="min-h-full bg-slate-50 px-6 py-8">
      <div className="mx-auto flex max-w-7xl flex-col gap-6">
        <DashboardPageHeader
          icon={ShieldCheck}
          title="관리"
          description="조직 멤버, 팀, 권한과 운영 리소스를 관리합니다."
          badge={badge}
          meta={
            <div className="flex min-w-0 items-center gap-2 text-xs text-slate-500">
              <Building2 className="h-3.5 w-3.5 shrink-0 text-blue-600" />
              <span className="truncate">
                {organization?.name || '조직 확인 중'}
              </span>
            </div>
          }
          action={
            <button
              onClick={onRefresh}
              className="inline-flex h-10 items-center gap-2 rounded-md border border-slate-300 bg-white px-3 text-sm font-medium text-slate-700 hover:bg-slate-100"
            >
              <RefreshCw className="h-4 w-4" />
              새로고침
            </button>
          }
        />
        {children}
      </div>
    </div>
  );
}

function MembersTab({
  members,
  page,
  onPageChange,
  query,
  onQueryChange,
  stateFilter,
  onStateFilterChange,
  authFilter,
  onAuthFilterChange,
  onInvite,
  currentUserId,
  activeManagerCount,
  actionPending,
  onUpdateMember,
  onRemoveMember,
}: {
  members: OrganizationMember[];
  page: number;
  onPageChange: (page: number) => void;
  query: string;
  onQueryChange: (query: string) => void;
  stateFilter: MembershipState | 'all';
  onStateFilterChange: (state: MembershipState | 'all') => void;
  authFilter: OrganizationAuthState | 'all';
  onAuthFilterChange: (state: OrganizationAuthState | 'all') => void;
  onInvite: () => void;
  currentUserId: string | null;
  activeManagerCount: number;
  actionPending: boolean;
  onUpdateMember: (
    member: OrganizationMember,
    payload: {
      membership_state?: 'active' | 'suspended' | null;
      organization_auth_state?: OrganizationAuthState | null;
    },
    message: string,
  ) => void;
  onRemoveMember: (member: OrganizationMember) => void;
}) {
  const pageItems = paginate(members, page);
  const totalPages = Math.max(1, Math.ceil(members.length / PAGE_SIZE));

  return (
    <DashboardPanel
      title="멤버"
      icon={Users}
      aside={
        <button
          onClick={onInvite}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800"
        >
          <UserPlus className="h-4 w-4" />
          초대
        </button>
      }
    >
      <ListToolbar
        query={query}
        onQueryChange={onQueryChange}
        placeholder="이름, email 검색"
        resultText={`결과 ${members.length}명`}
      >
        <select
          value={stateFilter}
          onChange={(event) =>
            onStateFilterChange(event.target.value as MembershipState | 'all')
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="active">활성</option>
          <option value="invited">초대 중</option>
          <option value="suspended">정지</option>
          <option value="removed">제거</option>
        </select>
        <select
          value={authFilter}
          onChange={(event) =>
            onAuthFilterChange(
              event.target.value as OrganizationAuthState | 'all',
            )
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 권한</option>
          <option value="manager">관리자</option>
          <option value="member">멤버</option>
        </select>
      </ListToolbar>

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
            <tr>
              <th className="px-5 py-3">이름</th>
              <th className="px-5 py-3">상태</th>
              <th className="px-5 py-3">조직 권한</th>
              <th className="px-5 py-3">초대</th>
              <th className="px-5 py-3">수락</th>
              <th className="px-5 py-3">작업</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.length === 0 ? (
              <tr>
                <td
                  colSpan={6}
                  className="px-5 py-10 text-center text-slate-500"
                >
                  조건에 맞는 멤버가 없습니다.
                </td>
              </tr>
            ) : (
              pageItems.map((member) => {
                const isSelf = currentUserId === member.user_id;
                const isSelfUnknown = currentUserId === null;
                const isLastActiveManager =
                  member.membership_state === 'active' &&
                  member.organization_auth_state === 'manager' &&
                  activeManagerCount <= 1;
                return (
                  <tr key={member.id} className="bg-white">
                    <td className="px-5 py-4">
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-950">
                          {member.user_name}
                        </p>
                        <p className="text-xs text-slate-500">
                          {member.user_email}
                        </p>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <MemberStateBadge state={member.membership_state} />
                    </td>
                    <td className="px-5 py-4">
                      <OrganizationAuthBadge
                        state={member.organization_auth_state}
                      />
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-500">
                      {formatDateTime(member.invited_at)}
                    </td>
                    <td className="px-5 py-4 text-xs text-slate-500">
                      {formatDateTime(member.accepted_at)}
                    </td>
                    <td className="px-5 py-4">
                      <MemberActions
                        member={member}
                        isSelf={isSelf}
                        isSelfUnknown={isSelfUnknown}
                        isLastActiveManager={isLastActiveManager}
                        actionPending={actionPending}
                        onUpdateMember={onUpdateMember}
                        onRemoveMember={onRemoveMember}
                      />
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={members.length}
        onPageChange={onPageChange}
      />
    </DashboardPanel>
  );
}

function MemberActions({
  member,
  isSelf,
  isSelfUnknown,
  isLastActiveManager,
  actionPending,
  onUpdateMember,
  onRemoveMember,
}: {
  member: OrganizationMember;
  isSelf: boolean;
  isSelfUnknown: boolean;
  isLastActiveManager: boolean;
  actionPending: boolean;
  onUpdateMember: (
    member: OrganizationMember,
    payload: {
      membership_state?: 'active' | 'suspended' | null;
      organization_auth_state?: OrganizationAuthState | null;
    },
    message: string,
  ) => void;
  onRemoveMember: (member: OrganizationMember) => void;
}) {
  if (member.membership_state === 'removed') {
    return <span className="text-xs text-slate-400">제거됨</span>;
  }
  const blockedManagerAction = isSelfUnknown || isSelf || isLastActiveManager;
  const blockTitle = isSelfUnknown
    ? '현재 사용자 확인 전에는 위험 작업을 할 수 없습니다.'
    : isSelf
      ? '자기 자신에게는 이 작업을 할 수 없습니다.'
      : '마지막 관리자는 변경할 수 없습니다.';
  const blockedAction = actionPending || isSelfUnknown;

  return (
    <div className="flex flex-wrap gap-1.5">
      {member.membership_state === 'active' && (
        <button
          onClick={() =>
            onUpdateMember(
              member,
              { membership_state: 'suspended' },
              '멤버를 정지했습니다.',
            )
          }
          disabled={blockedAction}
          title={isSelfUnknown ? blockTitle : undefined}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          정지
        </button>
      )}
      {member.membership_state === 'suspended' && (
        <button
          onClick={() =>
            onUpdateMember(
              member,
              { membership_state: 'active' },
              '멤버를 재활성화했습니다.',
            )
          }
          disabled={blockedAction}
          title={isSelfUnknown ? blockTitle : undefined}
          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
        >
          재활성화
        </button>
      )}
      {member.membership_state === 'active' &&
        member.organization_auth_state === 'member' && (
          <button
            onClick={() =>
              onUpdateMember(
                member,
                { organization_auth_state: 'manager' },
                '관리자로 승격했습니다.',
              )
            }
            disabled={blockedAction}
            title={isSelfUnknown ? blockTitle : undefined}
            className="rounded-md border border-blue-200 px-2 py-1 text-xs font-semibold text-blue-700 hover:bg-blue-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            관리자 승격
          </button>
        )}
      {member.membership_state === 'active' &&
        member.organization_auth_state === 'manager' && (
          <button
            onClick={() =>
              onUpdateMember(
                member,
                { organization_auth_state: 'member' },
                '멤버로 강등했습니다.',
              )
            }
            disabled={actionPending || blockedManagerAction}
            title={blockedManagerAction ? blockTitle : undefined}
            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
          >
            멤버로 강등
          </button>
        )}
      <button
        onClick={() => onRemoveMember(member)}
        disabled={actionPending || blockedManagerAction}
        title={blockedManagerAction ? blockTitle : undefined}
        className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
      >
        제거
      </button>
    </div>
  );
}

function TeamsTab({
  teams,
  page,
  onPageChange,
  query,
  onQueryChange,
  stateFilter,
  onStateFilterChange,
  memberFilter,
  onMemberFilterChange,
  teamMembers,
  teamMemberLoadErrors,
  isLimited,
  onCreateTeam,
  onEditTeam,
  onDeactivateTeam,
  onOpenTeam,
}: {
  teams: TeamResponse[];
  page: number;
  onPageChange: (page: number) => void;
  query: string;
  onQueryChange: (query: string) => void;
  stateFilter: 'all' | 'active' | 'inactive';
  onStateFilterChange: (state: 'all' | 'active' | 'inactive') => void;
  memberFilter: 'all' | 'has_members' | 'empty';
  onMemberFilterChange: (state: 'all' | 'has_members' | 'empty') => void;
  teamMembers: Record<string, TeamMemberResponse[]>;
  teamMemberLoadErrors: Record<string, boolean>;
  isLimited: boolean;
  onCreateTeam: () => void;
  onEditTeam: (team: TeamResponse) => void;
  onDeactivateTeam: (team: TeamResponse) => void;
  onOpenTeam: (teamId: string) => void;
}) {
  const pageItems = paginate(teams, page);
  const totalPages = Math.max(1, Math.ceil(teams.length / PAGE_SIZE));

  return (
    <DashboardPanel
      title="팀"
      icon={Building2}
      aside={
        <button
          onClick={onCreateTeam}
          className="inline-flex h-9 items-center gap-2 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800"
        >
          <Plus className="h-4 w-4" />팀 생성
        </button>
      }
    >
      <ListToolbar
        query={query}
        onQueryChange={onQueryChange}
        placeholder="팀 이름, 설명 검색"
        resultText={`결과 ${teams.length}개`}
      >
        <select
          value={stateFilter}
          onChange={(event) =>
            onStateFilterChange(
              event.target.value as 'all' | 'active' | 'inactive',
            )
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="active">활성</option>
          <option value="inactive">비활성</option>
        </select>
        <select
          value={memberFilter}
          onChange={(event) =>
            onMemberFilterChange(
              event.target.value as 'all' | 'has_members' | 'empty',
            )
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 멤버</option>
          <option value="has_members">멤버 있음</option>
          <option value="empty">멤버 없음</option>
        </select>
      </ListToolbar>
      {isLimited && (
        <div className="border-b border-amber-100 bg-amber-50 px-5 py-2 text-xs text-amber-800">
          현재 팀 목록은 API limit 100개 기준입니다. 100개 이상 조직은 서버
          pagination 연결 전까지 일부 팀이 보이지 않을 수 있습니다.
        </div>
      )}

      <div className="overflow-x-auto">
        <table className="min-w-full text-left text-sm">
          <thead className="border-b border-slate-200 bg-slate-50 text-xs font-semibold uppercase text-slate-500">
            <tr>
              <th className="px-5 py-3">팀</th>
              <th className="px-5 py-3">상태</th>
              <th className="px-5 py-3">멤버</th>
              <th className="px-5 py-3">작업</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {pageItems.length === 0 ? (
              <tr>
                <td
                  colSpan={4}
                  className="px-5 py-10 text-center text-slate-500"
                >
                  조건에 맞는 팀이 없습니다.
                </td>
              </tr>
            ) : (
              pageItems.map((team) => {
                const members = teamMembers[team.id] || [];
                return (
                  <tr key={team.id} className="bg-white">
                    <td className="px-5 py-4">
                      <div className="min-w-0">
                        <p className="font-semibold text-slate-950">
                          {team.name}
                        </p>
                        <p className="mt-1 text-xs text-slate-500">
                          {team.description || '설명 없음'}
                        </p>
                      </div>
                    </td>
                    <td className="px-5 py-4">
                      <span
                        className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                          team.is_active
                            ? 'bg-green-50 text-green-700'
                            : 'bg-slate-100 text-slate-600'
                        }`}
                      >
                        {team.is_active ? '활성' : '비활성'}
                      </span>
                    </td>
                    <td className="px-5 py-4">
                      {teamMemberLoadErrors[team.id] ? (
                        <span className="text-xs text-red-600">
                          멤버를 불러오지 못함
                        </span>
                      ) : members.length === 0 ? (
                        <span className="text-xs text-slate-400">
                          멤버 없음
                        </span>
                      ) : (
                        <div className="flex flex-wrap gap-1.5">
                          {members.slice(0, 3).map((member) => (
                            <span
                              key={member.id}
                              className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-700"
                            >
                              {member.name}
                            </span>
                          ))}
                          {members.length > 3 && (
                            <span className="rounded-md bg-slate-100 px-2 py-1 text-xs font-medium text-slate-500">
                              +{members.length - 3}
                            </span>
                          )}
                        </div>
                      )}
                    </td>
                    <td className="px-5 py-4">
                      <div className="flex flex-wrap gap-1.5">
                        <button
                          onClick={() => onOpenTeam(team.id)}
                          className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                        >
                          상세
                        </button>
                        <button
                          onClick={() => onEditTeam(team)}
                          className="rounded-md border border-slate-200 p-1.5 text-slate-500 hover:bg-slate-50"
                          title="팀 수정"
                        >
                          <Pencil className="h-4 w-4" />
                        </button>
                        <button
                          onClick={() => onDeactivateTeam(team)}
                          disabled={!team.is_active}
                          className="rounded-md border border-red-200 p-1.5 text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                          title="팀 비활성화"
                        >
                          <Trash2 className="h-4 w-4" />
                        </button>
                      </div>
                    </td>
                  </tr>
                );
              })
            )}
          </tbody>
        </table>
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={teams.length}
        onPageChange={onPageChange}
      />
    </DashboardPanel>
  );
}

function PermissionsTab({
  resourceType,
  onResourceTypeChange,
  workflowOptions,
  selectedWorkflowId,
  onSelectedWorkflowIdChange,
  credentials,
  selectedCredentialId,
  onSelectedCredentialIdChange,
  activeTeams,
  activeMembers,
  granteeType,
  onGranteeTypeChange,
  granteeId,
  onGranteeIdChange,
  authState,
  onAuthStateChange,
  permissionList,
  actionPending,
  onGrant,
  onRevoke,
}: {
  resourceType: ResourceType;
  onResourceTypeChange: (value: ResourceType) => void;
  workflowOptions: AppResponse[];
  selectedWorkflowId: string;
  onSelectedWorkflowIdChange: (value: string) => void;
  credentials: LLMCredentialResponse[];
  selectedCredentialId: string;
  onSelectedCredentialIdChange: (value: string) => void;
  activeTeams: TeamResponse[];
  activeMembers: OrganizationMember[];
  granteeType: GranteeType;
  onGranteeTypeChange: (value: GranteeType) => void;
  granteeId: string;
  onGranteeIdChange: (value: string) => void;
  authState: ResourceAuthState;
  onAuthStateChange: (value: ResourceAuthState) => void;
  permissionList: ResourcePermissionListResponse | null;
  actionPending: boolean;
  onGrant: () => void;
  onRevoke: (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
    label: string,
  ) => void;
}) {
  const resourceMissing =
    resourceType === 'workflow' ? !selectedWorkflowId : !selectedCredentialId;
  const granteeOptionsMissing =
    granteeType === 'team'
      ? activeTeams.length === 0
      : activeMembers.length === 0;
  const resourceLabel =
    resourceType === 'workflow' ? 'Workflow 권한' : 'Credential 권한';

  return (
    <DashboardPanel
      title="권한"
      icon={SlidersHorizontal}
      aside={
        <span className="text-xs font-medium text-slate-500">
          {resourceLabel}
        </span>
      }
    >
      <div className="grid gap-4 border-b border-slate-100 px-5 py-4 xl:grid-cols-[220px_minmax(0,1fr)_180px_minmax(0,1fr)_160px_auto]">
        <select
          value={resourceType}
          onChange={(event) =>
            onResourceTypeChange(event.target.value as ResourceType)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="workflow">Workflow</option>
          <option value="llm_credential">LLM Credential</option>
        </select>
        {resourceType === 'workflow' ? (
          <select
            value={selectedWorkflowId}
            onChange={(event) => onSelectedWorkflowIdChange(event.target.value)}
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {workflowOptions.length === 0 ? (
              <option value="">선택 가능한 workflow 없음</option>
            ) : (
              workflowOptions.map((app) => (
                <option key={app.id} value={app.workflow_id || ''}>
                  {app.name}
                </option>
              ))
            )}
          </select>
        ) : (
          <select
            value={selectedCredentialId}
            onChange={(event) =>
              onSelectedCredentialIdChange(event.target.value)
            }
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {credentials.length === 0 ? (
              <option value="">선택 가능한 credential 없음</option>
            ) : (
              credentials.map((credential) => (
                <option key={credential.id} value={credential.id}>
                  {credential.credential_name}
                </option>
              ))
            )}
          </select>
        )}
        <select
          value={granteeType}
          onChange={(event) =>
            onGranteeTypeChange(event.target.value as GranteeType)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="team">Team</option>
          <option value="user">User direct</option>
        </select>
        {granteeType === 'team' ? (
          <select
            value={granteeId}
            onChange={(event) => onGranteeIdChange(event.target.value)}
            className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
          >
            {activeTeams.length === 0 ? (
              <option value="">활성 팀 없음</option>
            ) : (
              activeTeams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))
            )}
          </select>
        ) : (
          <ActiveOrganizationMemberPicker
            members={activeMembers}
            value={granteeId}
            onChange={onGranteeIdChange}
            placeholder="권한 대상 멤버"
            emptyLabel="활성 멤버 없음"
          />
        )}
        <select
          value={authState}
          onChange={(event) =>
            onAuthStateChange(event.target.value as ResourceAuthState)
          }
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          {RESOURCE_AUTH_STATES.map((state) => (
            <option key={state} value={state}>
              {resourcePermissionLabel(resourceType, state)}
            </option>
          ))}
        </select>
        <button
          onClick={onGrant}
          disabled={
            actionPending ||
            resourceMissing ||
            granteeOptionsMissing ||
            !granteeId
          }
          className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
        >
          저장
        </button>
      </div>

      {resourceMissing ? (
        <Placeholder
          title="선택 가능한 resource가 없습니다"
          description="Workflow 또는 LLM Credential이 생성되면 권한을 부여할 수 있습니다."
        />
      ) : (
        <div className="grid gap-4 px-5 py-5 lg:grid-cols-2">
          <PermissionList
            title="Team permissions"
            rows={permissionList?.team_permissions || []}
            resourceType={resourceType}
            granteeType="team"
            onRevoke={onRevoke}
          />
          <PermissionList
            title="User direct permissions"
            rows={permissionList?.user_permissions || []}
            resourceType={resourceType}
            granteeType="user"
            onRevoke={onRevoke}
          />
        </div>
      )}
    </DashboardPanel>
  );
}

function CredentialsTab({
  providers,
  credentials,
  actionPending,
  onOpenCreate,
  onManagePermission,
  onSync,
  onDelete,
}: {
  providers: LLMProviderResponse[];
  credentials: LLMCredentialResponse[];
  actionPending: boolean;
  onOpenCreate: () => void;
  onManagePermission: (credentialId: string) => void;
  onSync: (credential: LLMCredentialResponse) => void;
  onDelete: (credential: LLMCredentialResponse) => void;
}) {
  return (
    <DashboardPanel
      title="LLM Credentials"
      icon={Key}
      aside={
        <div className="flex items-center gap-3">
          <span className="text-xs font-medium text-slate-500">
            active organization 기준
          </span>
          <button
            onClick={onOpenCreate}
            disabled={providers.length === 0 || actionPending}
            className="h-9 rounded-md bg-slate-950 px-3 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
          >
            Credential 등록
          </button>
        </div>
      }
    >
      <div className="divide-y divide-slate-100">
        {providers.length === 0 ? (
          <div className="px-5 py-10 text-center text-sm text-slate-500">
            provider 정보를 불러오지 못했거나 등록된 provider가 없습니다.
          </div>
        ) : (
          providers.map((provider) => {
            const providerCredentials = credentials.filter(
              (credential) => credential.provider_id === provider.id,
            );
            return (
              <div
                key={provider.id}
                className="grid gap-4 px-5 py-4 md:grid-cols-[minmax(0,1fr)_320px]"
              >
                <div>
                  <p className="font-semibold capitalize text-slate-950">
                    {provider.name}
                  </p>
                  <p className="mt-1 text-xs text-slate-500">
                    {provider.models.length} models · {provider.base_url}
                  </p>
                </div>
                <div className="space-y-2">
                  {providerCredentials.length === 0 ? (
                    <span className="text-xs text-slate-400">
                      연결된 credential 없음
                    </span>
                  ) : (
                    providerCredentials.map((credential) => (
                      <div
                        key={credential.id}
                        className="flex items-center justify-between gap-3 rounded-md border border-slate-200 px-3 py-2"
                      >
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-slate-900">
                            {credential.credential_name}
                          </p>
                          <p className="font-mono text-xs text-slate-500">
                            {credential.config_preview || 'preview 없음'}
                          </p>
                        </div>
                        <span
                          className={`rounded-md px-2 py-0.5 text-xs font-semibold ${
                            credential.is_valid
                              ? 'bg-green-50 text-green-700'
                              : 'bg-red-50 text-red-700'
                          }`}
                        >
                          {credential.is_valid ? 'valid' : 'invalid'}
                        </span>
                        <div className="flex shrink-0 gap-1">
                          <button
                            onClick={() => onManagePermission(credential.id)}
                            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50"
                          >
                            권한
                          </button>
                          <button
                            onClick={() => onSync(credential)}
                            disabled={actionPending}
                            className="rounded-md border border-slate-200 px-2 py-1 text-xs font-semibold text-slate-600 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            Sync
                          </button>
                          <button
                            onClick={() => onDelete(credential)}
                            disabled={actionPending}
                            className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50 disabled:cursor-not-allowed disabled:opacity-40"
                          >
                            삭제
                          </button>
                        </div>
                      </div>
                    ))
                  )}
                </div>
              </div>
            );
          })
        )}
      </div>
    </DashboardPanel>
  );
}

function resourcePermissionLabel(
  resourceType: ResourceType,
  state: ResourceAuthState,
) {
  if (resourceType === 'llm_credential') {
    const labels: Record<ResourceAuthState, string> = {
      viewer: 'Credential 조회 가능',
      operator: 'Credential 사용 가능',
      builder: 'Credential 수정 가능',
      manager: 'Credential 관리 가능',
    };
    return labels[state];
  }
  const labels: Record<ResourceAuthState, string> = {
    viewer: 'Workflow 조회 가능',
    operator: 'Workflow 실행 가능',
    builder: 'Workflow 수정 가능',
    manager: 'Workflow 관리 가능',
  };
  return labels[state];
}

function PermissionList({
  title,
  rows,
  resourceType,
  granteeType,
  onRevoke,
}: {
  title: string;
  rows: ResourcePermissionEntry[];
  resourceType: ResourceType;
  granteeType: GranteeType;
  onRevoke: (
    resourceType: ResourceType,
    granteeType: GranteeType,
    granteeId: string,
    label: string,
  ) => void;
}) {
  return (
    <div className="overflow-hidden rounded-md border border-slate-200">
      <div className="border-b border-slate-200 bg-slate-50 px-4 py-3 text-xs font-semibold uppercase text-slate-500">
        {title}
      </div>
      {rows.length === 0 ? (
        <div className="px-4 py-8 text-center text-sm text-slate-500">
          부여된 권한이 없습니다.
        </div>
      ) : (
        <div className="divide-y divide-slate-100">
          {rows.map((row) => (
            <div
              key={row.id}
              className="flex items-center justify-between gap-3 px-4 py-3"
            >
              <div className="min-w-0">
                <p className="truncate text-sm font-semibold text-slate-950">
                  {row.grantee_name}
                </p>
                <p className="mt-1 text-xs text-slate-500">
                  {resourcePermissionLabel(resourceType, row.auth_state)} ·{' '}
                  {formatDateTime(row.assigned_at)}
                </p>
              </div>
              <button
                onClick={() =>
                  onRevoke(
                    resourceType,
                    granteeType,
                    row.grantee_id,
                    `${row.grantee_name} · ${resourcePermissionLabel(
                      resourceType,
                      row.auth_state,
                    )}`,
                  )
                }
                className="rounded-md border border-red-200 px-2 py-1 text-xs font-semibold text-red-700 hover:bg-red-50"
              >
                회수
              </button>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

function KnowledgeTab({
  knowledgeBases,
}: {
  knowledgeBases: KnowledgeBaseResponse[];
}) {
  return (
    <DashboardPanel
      title="지식 기반"
      icon={BookOpen}
      aside={
        <span className="text-xs font-medium text-slate-500">
          기존 지식 기반 목록 기준
        </span>
      }
    >
      <div className="divide-y divide-slate-100">
        {knowledgeBases.length === 0 ? (
          <Placeholder
            title="표시할 지식 기반이 없습니다"
            description="지식 기반 권한 관리 action은 API 범위 확인 후 연결합니다."
          />
        ) : (
          knowledgeBases.map((base) => (
            <div
              key={base.id}
              className="grid gap-3 px-5 py-4 md:grid-cols-[minmax(0,1fr)_160px_160px]"
            >
              <div className="min-w-0">
                <p className="truncate font-semibold text-slate-950">
                  {base.name}
                </p>
                <p className="mt-1 text-sm text-slate-500">
                  {base.description || '설명 없음'}
                </p>
              </div>
              <span className="text-sm text-slate-600">
                문서 {base.document_count}개
              </span>
              <button
                disabled
                className="h-9 rounded-md border border-slate-200 px-3 text-sm font-semibold text-slate-400"
              >
                권한 관리 예정
              </button>
            </div>
          ))
        )}
      </div>
    </DashboardPanel>
  );
}

function AuditTab({ auditItems }: { auditItems: AuditItem[] }) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [page, setPage] = useState(1);

  const filteredItems = useMemo(() => {
    const normalizedQuery = normalizeText(query);
    return auditItems.filter((item) => {
      if (statusFilter !== 'all' && item.status !== statusFilter) return false;
      if (!normalizedQuery) return true;
      return normalizeText(
        [
          item.actor,
          item.workflow,
          item.action,
          item.target_type,
          item.target_id,
          item.status,
          item.input,
          item.policy,
          item.decision,
          item.trace_id,
          item.change,
          item.source,
          formatDateTime(item.occurred_at),
        ]
          .filter(Boolean)
          .join(' '),
      ).includes(normalizedQuery);
    });
  }, [auditItems, query, statusFilter]);

  const totalPages = Math.max(1, Math.ceil(filteredItems.length / PAGE_SIZE));
  const pageItems = paginate(filteredItems, page);

  useEffect(() => {
    setPage(1);
  }, [query, statusFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <DashboardPanel
      title="감사 로그"
      icon={Activity}
      aside={
        <span className="text-xs font-medium text-amber-700">
          현재는 내 활동 로그 기준
        </span>
      }
    >
      <ListToolbar
        query={query}
        onQueryChange={setQuery}
        placeholder="action, target, status 검색"
        resultText={`결과 ${filteredItems.length}개`}
      >
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="completed">완료</option>
          <option value="blocked">차단</option>
          <option value="denied">거절</option>
          <option value="success">성공</option>
          <option value="failure">실패</option>
        </select>
      </ListToolbar>
      <div className="divide-y divide-slate-100">
        {auditItems.length === 0 ? (
          <Placeholder
            title="표시할 활동이 없습니다"
            description="조직 전체 audit API가 확정되면 이 탭을 조직 감사 로그 기준으로 전환합니다."
          />
        ) : pageItems.length === 0 ? (
          <Placeholder
            title="조건에 맞는 감사 로그가 없습니다"
            description="검색어 또는 상태 필터를 조정해 주세요."
          />
        ) : (
          pageItems.map((item) => (
            <div
              key={item.id}
              className="grid gap-3 px-5 py-4 text-sm xl:grid-cols-[180px_minmax(0,1fr)_220px]"
            >
              <div className="space-y-1">
                <span className="text-xs text-slate-500">
                  {formatDateTime(item.occurred_at)}
                </span>
                <p className="text-xs font-medium text-slate-600">
                  Actor: {item.actor || '-'}
                </p>
                <p className="font-mono text-xs text-slate-500">
                  {item.trace_id || item.target_id || '-'}
                </p>
              </div>
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <span className="font-semibold text-slate-900">
                    {item.action} · {item.target_type}
                  </span>
                  <span
                    className={`w-fit rounded-md px-2 py-0.5 text-xs font-semibold ${
                      item.status === 'failure' ||
                      item.status === 'blocked' ||
                      item.status === 'denied'
                        ? 'bg-red-50 text-red-700'
                        : 'bg-slate-100 text-slate-700'
                    }`}
                  >
                    {statusLabelKo(item.status)}
                  </span>
                </div>
                <p className="mt-1 text-sm text-slate-600">
                  {item.workflow || '-'}
                </p>
                {(item.input || item.change) && (
                  <p className="mt-2 rounded-md bg-slate-50 px-3 py-2 text-sm leading-5 text-slate-700">
                    {item.input || item.change}
                  </p>
                )}
                {item.source && (
                  <p className="mt-1 text-xs text-slate-500">
                    Source: {item.source}
                  </p>
                )}
              </div>
              <div className="grid grid-cols-2 gap-2 xl:grid-cols-1">
                <ReviewMetric label="정책" value={item.policy || '-'} />
                <ReviewMetric
                  label="판단"
                  value={decisionLabelKo(item.decision || '-')}
                />
              </div>
            </div>
          ))
        )}
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={filteredItems.length}
        onPageChange={setPage}
      />
    </DashboardPanel>
  );
}

function RunReviewTab({ reviewRuns }: { reviewRuns: AdminReviewRun[] }) {
  const [query, setQuery] = useState('');
  const [statusFilter, setStatusFilter] = useState('all');
  const [guardrailFilter, setGuardrailFilter] = useState('all');
  const [rbacFilter, setRbacFilter] = useState('all');
  const [page, setPage] = useState(1);
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null);

  const filteredRuns = useMemo(() => {
    const normalizedQuery = normalizeText(query);
    return reviewRuns.filter((run) => {
      const review = reviewPayloadOf(run);
      const status = reviewStatusOf(run);
      const guardrail = reviewValue(review, 'guardrail');
      const rbac = reviewValue(review, 'rbac');
      const retrievedDocs = Array.isArray(review.retrieved_docs)
        ? review.retrieved_docs.map((doc) => String(doc)).join(' ')
        : '';

      if (statusFilter !== 'all' && status !== statusFilter) return false;
      if (guardrailFilter !== 'all' && guardrail !== guardrailFilter) {
        return false;
      }
      if (rbacFilter !== 'all' && rbac !== rbacFilter) return false;
      if (!normalizedQuery) return true;

      return normalizeText(
        [
          run.app_name,
          run.id,
          run.user_id,
          review.run_label,
          review.title,
          review.input,
          review.final_response,
          review.reason,
          review.requested_resource,
          retrievedDocs,
        ]
          .filter(Boolean)
          .join(' '),
      ).includes(normalizedQuery);
    });
  }, [guardrailFilter, query, rbacFilter, reviewRuns, statusFilter]);

  const summary = useMemo(
    () =>
      filteredRuns.reduce(
        (acc, run) => {
          const review = reviewPayloadOf(run);
          const status = reviewStatusOf(run);
          if (status === 'Completed') acc.completed += 1;
          if (status === 'Blocked') acc.blocked += 1;
          if (status === 'Denied') acc.denied += 1;
          if (status === 'Error' || run.status === 'failed') acc.error += 1;
          if (review.guardrail === 'Denied') acc.guardrailDenied += 1;
          if (review.rbac === 'Denied') acc.rbacDenied += 1;
          acc.totalCost += reviewCostOf(run);
          acc.totalDuration += reviewDurationOf(run);
          return acc;
        },
        {
          completed: 0,
          blocked: 0,
          denied: 0,
          error: 0,
          guardrailDenied: 0,
          rbacDenied: 0,
          totalCost: 0,
          totalDuration: 0,
        },
      ),
    [filteredRuns],
  );

  const totalPages = Math.max(
    1,
    Math.ceil(filteredRuns.length / RUN_REVIEW_PAGE_SIZE),
  );
  const pageItems = filteredRuns.slice(
    (page - 1) * RUN_REVIEW_PAGE_SIZE,
    page * RUN_REVIEW_PAGE_SIZE,
  );
  const averageDuration =
    filteredRuns.length > 0 ? summary.totalDuration / filteredRuns.length : 0;
  const hasMockRuns = filteredRuns.some(
    (run) => reviewPayloadOf(run).is_mock_adapter === true,
  );
  const hasOperationalAlert =
    summary.blocked > 0 ||
    summary.denied > 0 ||
    summary.error > 0 ||
    summary.totalCost >= 0.01 ||
    averageDuration >= 3;

  useEffect(() => {
    setPage(1);
    setExpandedRunId(null);
  }, [guardrailFilter, query, rbacFilter, statusFilter]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return (
    <DashboardPanel
      title="실행 검토"
      icon={Activity}
      aside={
        <span className="text-xs font-medium text-slate-500">
          정상 · 가드레일 차단 · RBAC 차단 비교
        </span>
      }
    >
      <div className="grid gap-3 border-b border-slate-100 px-5 py-4 md:grid-cols-4">
        <ReviewSummaryCard
          label="정상"
          value={summary.completed}
          tone="green"
          description="정상 완료된 실행"
        />
        <ReviewSummaryCard
          label="가드레일 차단"
          value={summary.guardrailDenied || summary.blocked}
          tone="amber"
          description="LLM/RAG 전 단계 차단"
        />
        <ReviewSummaryCard
          label="RBAC 차단"
          value={summary.rbacDenied || summary.denied}
          tone="red"
          description="권한 없는 문서 접근 제한"
        />
        <ReviewSummaryCard
          label="비용/응답"
          value={`$${summary.totalCost.toFixed(4)}`}
          tone={
            summary.totalCost >= 0.01 || averageDuration >= 3
              ? 'amber'
              : 'slate'
          }
          description={`평균 ${averageDuration.toFixed(1)}s`}
        />
      </div>

      {hasOperationalAlert && (
        <div className="border-b border-amber-100 bg-amber-50 px-5 py-3 text-sm text-amber-900">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0" />
            <div className="space-y-1">
              <p className="font-semibold">확인할 운영 신호가 있습니다.</p>
              <p className="text-xs leading-5">
                차단 {summary.blocked}건 · 거절 {summary.denied}건 · 오류{' '}
                {summary.error}건 · 비용 ${summary.totalCost.toFixed(4)} · 평균
                응답 {averageDuration.toFixed(1)}s
              </p>
            </div>
          </div>
        </div>
      )}

      {hasMockRuns && (
        <div className="border-b border-blue-100 bg-blue-50 px-5 py-3 text-xs leading-5 text-blue-800">
          실제 workflow run에서 관리자 실행 검토용 demo_review 로그를 찾지 못해
          프론트 mock adapter 데이터로 표시 중입니다. 실제 로그가 생성되면 이
          데이터는 자동으로 대체됩니다.
        </div>
      )}

      <ListToolbar
        query={query}
        onQueryChange={setQuery}
        placeholder="실행 ID, 입력, 문서, 사유, 요청 리소스 검색"
        resultText={`결과 ${filteredRuns.length}개`}
      >
        <select
          value={statusFilter}
          onChange={(event) => setStatusFilter(event.target.value)}
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 상태</option>
          <option value="Completed">완료</option>
          <option value="Blocked">차단</option>
          <option value="Denied">거절</option>
          <option value="Error">오류</option>
        </select>
        <select
          value={guardrailFilter}
          onChange={(event) => setGuardrailFilter(event.target.value)}
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 가드레일</option>
          <option value="Passed">통과</option>
          <option value="Denied">거절</option>
          <option value="Skipped">건너뜀</option>
        </select>
        <select
          value={rbacFilter}
          onChange={(event) => setRbacFilter(event.target.value)}
          className="h-10 rounded-md border border-slate-300 bg-white px-3 text-sm"
        >
          <option value="all">전체 RBAC</option>
          <option value="Allowed">허용</option>
          <option value="Denied">거절</option>
          <option value="Not evaluated">평가 안 함</option>
        </select>
      </ListToolbar>

      <div className="divide-y divide-slate-100">
        {reviewRuns.length === 0 ? (
          <Placeholder
            title="표시할 시연 실행 로그가 없습니다"
            description="demo_review.scenario 값이 있는 workflow run을 생성하면 이 탭에 표시됩니다."
          />
        ) : pageItems.length === 0 ? (
          <Placeholder
            title="조건에 맞는 실행 로그가 없습니다"
            description="검색어 또는 필터 조건을 조정해 주세요."
          />
        ) : (
          pageItems.map((run) => {
            const review = reviewPayloadOf(run);
            const retrievedDocs = Array.isArray(review.retrieved_docs)
              ? review.retrieved_docs
              : [];
            const traceSteps = reviewArrayOf<{
              label?: string;
              state?: string;
            }>(review, 'trace_steps');
            const retrievedChunks = reviewArrayOf<{
              document?: string;
              section?: string;
              evidence?: string;
              score?: number;
            }>(review, 'retrieved_chunks');
            const status = reviewStatusOf(run);
            const isExpanded = expandedRunId === run.id;
            const needsAttention =
              status === 'Blocked' ||
              status === 'Denied' ||
              status === 'Error' ||
              run.status === 'failed' ||
              review.guardrail === 'Denied' ||
              review.rbac === 'Denied';
            const statusTone =
              review.status === 'Completed'
                ? 'bg-green-50 text-green-700'
                : review.status === 'Blocked'
                  ? 'bg-amber-50 text-amber-700'
                  : 'bg-red-50 text-red-700';

            return (
              <div key={run.id} className="px-5 py-4">
                <div className="grid gap-3 xl:grid-cols-[180px_minmax(0,1fr)_320px_96px] xl:items-center">
                  <div className="space-y-1.5">
                    <div className="flex flex-wrap items-center gap-2">
                      <span
                        className={`inline-flex rounded-md px-2 py-1 text-xs font-bold ${statusTone}`}
                      >
                        {statusLabelKo(String(review.status || run.status))}
                      </span>
                      {needsAttention && (
                        <span className="rounded-md bg-red-50 px-2 py-1 text-xs font-semibold text-red-700">
                          확인 필요
                        </span>
                      )}
                    </div>
                    <p className="font-mono text-xs text-slate-500">
                      {String(review.run_label || run.id)}
                    </p>
                    <p className="text-xs text-slate-500">
                      {formatDateTime(run.started_at)}
                    </p>
                  </div>

                  <div className="min-w-0">
                    <p className="truncate text-sm font-semibold text-slate-950">
                      {String(review.title || run.app_name)}
                    </p>
                    <p className="mt-1 line-clamp-2 text-sm leading-5 text-slate-700">
                      {String(review.input || run.inputs?.message || '-')}
                    </p>
                    <div className="mt-2 flex flex-wrap gap-1.5 text-xs">
                      <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
                        가드레일 {decisionLabelKo(review.guardrail)}
                      </span>
                      <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
                        RBAC {decisionLabelKo(review.rbac)}
                      </span>
                      <span className="rounded-md bg-slate-100 px-2 py-1 font-medium text-slate-700">
                        LLM{' '}
                        {decisionLabelKo(
                          review.llm_generation ||
                            review.llm_answer_generation ||
                            '-',
                        )}
                      </span>
                    </div>
                  </div>

                  <div className="grid grid-cols-2 gap-2 text-sm sm:grid-cols-4 xl:grid-cols-2">
                    <ReviewMetric
                      label="요청자"
                      value={review.user || run.user_id}
                    />
                    <ReviewMetric
                      label="비용"
                      value={
                        review.estimated_cost ||
                        `$${Number(run.total_cost || 0).toFixed(4)}`
                      }
                    />
                    <ReviewMetric
                      label="응답 시간"
                      value={review.latency || `${run.duration || '-'}s`}
                    />
                    <ReviewMetric
                      label="사유"
                      value={review.reason || review.requested_resource || '-'}
                    />
                  </div>

                  <button
                    onClick={() => setExpandedRunId(isExpanded ? null : run.id)}
                    className="h-9 rounded-md border border-slate-200 px-3 text-xs font-semibold text-slate-700 hover:bg-slate-50"
                  >
                    {isExpanded ? '접기' : '상세 보기'}
                  </button>
                </div>

                {isExpanded && (
                  <div className="mt-4 space-y-4 rounded-md border border-slate-200 bg-slate-50 p-4">
                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                      <TraceFlow traceSteps={traceSteps} />
                      <CostMonitor run={run} review={review} />
                    </div>

                    <DecisionPanels review={review} />

                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_320px]">
                      <RagEvidence
                        retrievedDocs={retrievedDocs}
                        retrievedChunks={retrievedChunks}
                        ragSearch={review.rag_search}
                      />
                      <div className="space-y-2 rounded-md border border-slate-200 bg-white p-3 text-sm">
                        <ReviewMetric
                          label="요청 리소스"
                          value={review.requested_resource || '-'}
                        />
                        <ReviewMetric
                          label="필요 팀"
                          value={review.required_team || '-'}
                        />
                        <ReviewMetric
                          label="사용자 팀"
                          value={review.user_team || '-'}
                        />
                        <ReviewMetric
                          label="추적 ID"
                          value={review.trace_id || '-'}
                        />
                        <ReviewMetric
                          label="실행 ID"
                          value={review.run_label || run.id}
                        />
                      </div>
                    </div>

                    <div>
                      <p className="text-xs font-semibold uppercase text-slate-500">
                        최종 응답
                      </p>
                      <p className="mt-1 rounded-md bg-white p-3 text-sm leading-6 text-slate-800">
                        {String(
                          review.final_response || run.outputs?.answer || '-',
                        )}
                      </p>
                    </div>
                  </div>
                )}
              </div>
            );
          })
        )}
      </div>
      <Pagination
        page={page}
        totalPages={totalPages}
        totalItems={filteredRuns.length}
        onPageChange={setPage}
      />
    </DashboardPanel>
  );
}

function ReviewSummaryCard({
  label,
  value,
  description,
  tone,
}: {
  label: string;
  value: number | string;
  description: string;
  tone: 'green' | 'amber' | 'red' | 'slate';
}) {
  const toneClass =
    tone === 'green'
      ? 'border-green-100 bg-green-50 text-green-800'
      : tone === 'amber'
        ? 'border-amber-100 bg-amber-50 text-amber-800'
        : tone === 'red'
          ? 'border-red-100 bg-red-50 text-red-800'
          : 'border-slate-200 bg-slate-50 text-slate-700';

  return (
    <div className={`rounded-md border p-3 ${toneClass}`}>
      <p className="text-xs font-semibold uppercase">{label}</p>
      <p className="mt-2 text-xl font-bold">{value}</p>
      <p className="mt-1 text-xs">{description}</p>
    </div>
  );
}

function TraceFlow({
  traceSteps,
}: {
  traceSteps: Array<{ label?: string; state?: string }>;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase text-slate-500">
        실행 흐름
      </p>
      {traceSteps.length === 0 ? (
        <p className="mt-2 text-sm text-slate-500">trace 단계 없음</p>
      ) : (
        <div className="mt-3 space-y-2">
          {traceSteps.map((step, index) => {
            const state = step.state || 'pending';
            const tone =
              state === 'denied' || state === 'failed'
                ? 'border-red-200 bg-red-50 text-red-700'
                : state === 'completed'
                  ? 'border-green-200 bg-green-50 text-green-700'
                  : 'border-slate-200 bg-slate-50 text-slate-700';
            return (
              <div key={`${step.label}-${index}`} className="flex gap-3">
                <div className="flex flex-col items-center">
                  <span
                    className={`flex h-6 w-6 items-center justify-center rounded-full border text-xs font-bold ${tone}`}
                  >
                    {index + 1}
                  </span>
                  {index < traceSteps.length - 1 && (
                    <span className="h-5 w-px bg-slate-200" />
                  )}
                </div>
                <div>
                  <p className="text-sm font-semibold text-slate-900">
                    {traceLabelKo(step.label)}
                  </p>
                  <p className="text-xs text-slate-500">
                    {stateLabelKo(state)}
                  </p>
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

function RagEvidence({
  retrievedDocs,
  retrievedChunks,
  ragSearch,
}: {
  retrievedDocs: unknown[];
  retrievedChunks: Array<{
    document?: string;
    section?: string;
    evidence?: string;
    score?: number;
  }>;
  ragSearch: unknown;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase text-slate-500">
        RAG 근거 문서
      </p>
      {retrievedChunks.length > 0 ? (
        <div className="mt-3 space-y-3">
          {retrievedChunks.map((chunk, index) => (
            <div
              key={`${chunk.document}-${index}`}
              className="rounded-md border border-blue-100 bg-blue-50 p-3"
            >
              <p className="text-xs font-semibold text-blue-700">
                검색 결과 조각 {index + 1}
              </p>
              <p className="mt-1 text-sm font-semibold text-slate-950">
                문서: {chunk.document || '-'}
              </p>
              <p className="mt-1 text-sm text-slate-700">
                일치한 섹션: {chunk.section || '-'}
              </p>
              <p className="mt-1 text-sm leading-5 text-slate-800">
                핵심 근거: {chunk.evidence || '-'}
              </p>
              {chunk.score !== undefined && (
                <p className="mt-1 text-xs text-slate-500">
                  유사도: {chunk.score}
                </p>
              )}
            </div>
          ))}
        </div>
      ) : retrievedDocs.length > 0 ? (
        <div className="mt-2 flex flex-wrap gap-1.5">
          {retrievedDocs.map((doc) => (
            <span
              key={String(doc)}
              className="rounded-md bg-blue-50 px-2 py-1 text-xs font-medium text-blue-700"
            >
              {String(doc)}
            </span>
          ))}
        </div>
      ) : (
        <p className="mt-2 text-sm text-slate-500">
          {String(ragSearch || '검색 안 함')}
        </p>
      )}
    </div>
  );
}

function CostMonitor({
  run,
  review,
}: {
  run: AdminReviewRun;
  review: Record<string, unknown>;
}) {
  return (
    <div className="rounded-md border border-slate-200 bg-white p-4">
      <p className="text-xs font-semibold uppercase text-slate-500">
        비용 모니터
      </p>
      <div className="mt-3 grid grid-cols-2 gap-3 text-sm">
        <ReviewMetric label="모델" value={review.model || 'gpt-4o-mini'} />
        <ReviewMetric
          label="예상 비용"
          value={
            review.estimated_cost ||
            `$${Number(run.total_cost || 0).toFixed(4)}`
          }
        />
        <ReviewMetric
          label="입력 토큰"
          value={review.input_tokens || run.total_tokens || '-'}
        />
        <ReviewMetric label="출력 토큰" value={review.output_tokens || '-'} />
        <ReviewMetric
          label="가드레일 차단"
          value={review.guardrail_blocked === true ? '예' : '아니오'}
        />
        <ReviewMetric
          label="답변 LLM"
          value={review.answer_llm_skipped === true ? '건너뜀' : '실행됨'}
        />
      </div>
    </div>
  );
}

function DecisionPanels({ review }: { review: Record<string, unknown> }) {
  return (
    <div className="grid gap-4 md:grid-cols-2">
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold uppercase text-slate-500">
          가드레일 판단
        </p>
        <div className="mt-3 grid gap-2 text-sm">
          <ReviewMetric
            label="정책 판단"
            value={decisionLabelKo(
              review.policy_decision || review.guardrail || '-',
            )}
          />
          <ReviewMetric label="사유" value={review.reason || '-'} />
          <ReviewMetric
            label="조치"
            value={actionLabelKo(review.action || '-')}
          />
        </div>
      </div>
      <div className="rounded-md border border-slate-200 bg-white p-4">
        <p className="text-xs font-semibold uppercase text-slate-500">
          RBAC 판단
        </p>
        <div className="mt-3 grid gap-2 text-sm">
          <ReviewMetric
            label="권한 판단"
            value={decisionLabelKo(
              review.permission_decision || review.rbac || '-',
            )}
          />
          <ReviewMetric
            label="요청 리소스"
            value={review.requested_resource || '-'}
          />
          <ReviewMetric label="필요 팀" value={review.required_team || '-'} />
        </div>
      </div>
    </div>
  );
}

function ReviewMetric({ label, value }: { label: string; value: unknown }) {
  return (
    <div>
      <p className="text-xs font-semibold uppercase text-slate-500">{label}</p>
      <p className="mt-1 text-sm font-medium text-slate-900">
        {value === undefined || value === null || value === ''
          ? '-'
          : String(value)}
      </p>
    </div>
  );
}

function OrganizationTab({
  organization,
}: {
  organization: OrganizationResponse | null;
}) {
  return (
    <DashboardPanel title="조직 설정" icon={Building2}>
      <div className="grid gap-4 px-5 py-5 md:grid-cols-2">
        <div className="rounded-md border border-slate-200 bg-slate-50 p-4">
          <p className="text-xs font-semibold uppercase text-slate-500">
            조직명
          </p>
          <p className="mt-2 font-semibold text-slate-950">
            {organization?.name || '확인 중'}
          </p>
        </div>
        <div className="rounded-md border border-amber-200 bg-amber-50 p-4">
          <div className="flex items-start gap-2">
            <AlertTriangle className="mt-0.5 h-4 w-4 text-amber-700" />
            <p className="text-sm leading-6 text-amber-800">
              조직명 수정, 기본 팀, 위험 action은 정책과 API 범위 확정 후
              연결합니다.
            </p>
          </div>
        </div>
      </div>
    </DashboardPanel>
  );
}

function ListToolbar({
  query,
  onQueryChange,
  placeholder,
  resultText,
  children,
}: {
  query: string;
  onQueryChange: (query: string) => void;
  placeholder: string;
  resultText: string;
  children: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-3 border-b border-slate-100 px-5 py-4 lg:flex-row lg:items-center lg:justify-between">
      <div className="relative min-w-0 flex-1">
        <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
        <input
          value={query}
          onChange={(event) => onQueryChange(event.target.value)}
          className="h-10 w-full rounded-md border border-slate-300 bg-white pl-9 pr-3 text-sm"
          placeholder={placeholder}
        />
      </div>
      <div className="flex flex-wrap items-center gap-2">
        {children}
        <span className="text-xs font-medium text-slate-500">{resultText}</span>
      </div>
    </div>
  );
}

function Pagination({
  page,
  totalPages,
  totalItems,
  onPageChange,
}: {
  page: number;
  totalPages: number;
  totalItems: number;
  onPageChange: (page: number) => void;
}) {
  return (
    <div className="flex flex-wrap items-center justify-between gap-3 border-t border-slate-100 px-5 py-3 text-sm">
      <span className="text-slate-500">
        {totalItems}개 중 page {page}/{totalPages}
      </span>
      <div className="flex gap-2">
        <button
          onClick={() => onPageChange(Math.max(1, page - 1))}
          disabled={page <= 1}
          className="h-8 rounded-md border border-slate-200 px-3 text-xs font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          이전
        </button>
        <button
          onClick={() => onPageChange(Math.min(totalPages, page + 1))}
          disabled={page >= totalPages}
          className="h-8 rounded-md border border-slate-200 px-3 text-xs font-semibold text-slate-600 disabled:cursor-not-allowed disabled:opacity-40"
        >
          다음
        </button>
      </div>
    </div>
  );
}

function SidePanel({
  title,
  children,
  onClose,
}: {
  title: string;
  children: React.ReactNode;
  onClose: () => void;
}) {
  return (
    <div className="fixed inset-0 z-50 flex justify-end bg-slate-950/30">
      <div className="h-full w-full max-w-xl overflow-y-auto bg-white shadow-xl">
        <div className="sticky top-0 z-10 flex items-center justify-between border-b border-slate-200 bg-white px-5 py-4">
          <h2 className="text-base font-semibold text-slate-950">{title}</h2>
          <button
            onClick={onClose}
            className="rounded-md p-2 text-slate-500 hover:bg-slate-100"
            title="닫기"
          >
            <X className="h-4 w-4" />
          </button>
        </div>
        <div className="px-5 py-5">{children}</div>
      </div>
    </div>
  );
}

function ConfirmDialog({
  state,
  pending,
  onCancel,
  onConfirm,
}: {
  state: ConfirmState;
  pending: boolean;
  onCancel: () => void;
  onConfirm: () => void;
}) {
  const isDanger = state.tone === 'danger';
  return (
    <div className="fixed inset-0 z-[60] flex items-center justify-center bg-slate-950/40 px-4">
      <div className="w-full max-w-md rounded-lg bg-white p-5 shadow-xl">
        <h2 className="text-base font-semibold text-slate-950">
          {state.title}
        </h2>
        <p className="mt-2 text-sm leading-6 text-slate-600">
          {state.description}
        </p>
        {state.details && state.details.length > 0 && (
          <ul className="mt-3 space-y-1 rounded-md bg-slate-50 px-3 py-2 text-sm text-slate-600">
            {state.details.map((detail) => (
              <li key={detail}>{detail}</li>
            ))}
          </ul>
        )}
        <div className="mt-5 flex justify-end gap-2">
          <button
            onClick={onCancel}
            disabled={pending}
            className="h-9 rounded-md border border-slate-300 px-3 text-sm font-semibold text-slate-700 disabled:opacity-40"
          >
            취소
          </button>
          <button
            onClick={onConfirm}
            disabled={pending}
            className={`h-9 rounded-md px-3 text-sm font-semibold text-white disabled:opacity-40 ${
              isDanger
                ? 'bg-red-600 hover:bg-red-700'
                : 'bg-slate-950 hover:bg-slate-800'
            }`}
          >
            {state.confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

function LabelledField({
  label,
  children,
}: {
  label: string;
  children: React.ReactNode;
}) {
  return (
    <label className="block">
      <span className="mb-1.5 block text-sm font-semibold text-slate-800">
        {label}
      </span>
      {children}
    </label>
  );
}

function PanelActions({
  onCancel,
  onSubmit,
  submitLabel,
  disabled,
}: {
  onCancel: () => void;
  onSubmit: () => void;
  submitLabel: string;
  disabled?: boolean;
}) {
  return (
    <div className="flex justify-end gap-2 border-t border-slate-200 pt-4">
      <button
        onClick={onCancel}
        className="h-10 rounded-md border border-slate-300 px-4 text-sm font-semibold text-slate-700 hover:bg-slate-50"
      >
        취소
      </button>
      <button
        onClick={onSubmit}
        disabled={disabled}
        className="h-10 rounded-md bg-slate-950 px-4 text-sm font-semibold text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-40"
      >
        {submitLabel}
      </button>
    </div>
  );
}

function Placeholder({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="px-6 py-12 text-center">
      <p className="font-semibold text-slate-900">{title}</p>
      <p className="mx-auto mt-2 max-w-xl text-sm leading-6 text-slate-500">
        {description}
      </p>
    </div>
  );
}

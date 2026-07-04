export type AdminWorkflowUsageItem = {
  workflow_id: string;
  workflow_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
  total_cost: number;
};

export type AdminUsagePeriod = {
  startAt: string;
  endAt: string;
};

export type AdminWorkflowUsageResponse = {
  total: number;
  period: AdminUsagePeriod;
  items: AdminWorkflowUsageItem[];
};

// budget 블록은 예산 관리 feature(PRD FR-051) 확정 전까지 null이다.
export type AdminOrganizationSummary = {
  month: string;
  total_cost: number;
  budget: null;
};

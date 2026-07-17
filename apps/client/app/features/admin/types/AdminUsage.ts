import type { BudgetUsageStatus } from '../../budget/types';

export type AdminWorkflowBudgetUsage = {
  monthly_budget_usd: number;
  current_month_cost: number;
  usage_ratio: number;
  status: BudgetUsageStatus | string;
};

export type AdminWorkflowUsageItem = {
  workflow_id: string;
  workflow_name: string;
  prompt_tokens: number;
  completion_tokens: number;
  call_count: number;
  total_cost: number;
  workflow_execution_cost: number;
  agent_builder_cost: number;
  budget?: AdminWorkflowBudgetUsage | null;
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

export type AdminBudgetSummary = {
  budgeted_workflow_count: number;
  at_risk_count: number;
  exceeded_count: number;
  ratio: number;
};

export type AdminOrganizationSummary = {
  month: string;
  total_cost: number;
  workflow_execution_cost: number;
  agent_builder_cost: number;
  budget: AdminBudgetSummary | null;
};

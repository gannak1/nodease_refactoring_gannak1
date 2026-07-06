export type BudgetUsageStatus = 'normal' | 'at_risk' | 'exceeded';

export type BudgetStatusPayload = {
  usage_ratio: number;
  status: BudgetUsageStatus;
};

export type WorkflowBudget = {
  workflow_id: string;
  workflow_name?: string;
  monthly_budget_usd: number;
  is_enabled: boolean;
  current_month_cost?: number | null;
  usage_ratio?: number | null;
  status?: BudgetUsageStatus | null;
};

export type WorkflowBudgetUpsertPayload = {
  monthly_budget_usd: number;
  is_enabled: boolean;
};

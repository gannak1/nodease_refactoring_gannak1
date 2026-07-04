import { useEffect, useState } from 'react';
import { BarChart3 } from 'lucide-react';
import { workflowApi } from '../../api/workflowApi';
import type { WorkflowPermissionResponse } from '../../types/Api';

interface CostOptimizerEntryActionProps {
  workflowId: string;
  nodeId: string;
  workflowAccess?: WorkflowPermissionResponse | null;
}

const canUseCostOptimizer = (workflowAccess?: WorkflowPermissionResponse | null) =>
  workflowAccess?.can_write === true;

export const CostOptimizerEntryAction = ({
  workflowId,
  nodeId,
  workflowAccess,
}: CostOptimizerEntryActionProps) => {
  const hasBuilderPermission = canUseCostOptimizer(workflowAccess);
  const [isAvailable, setIsAvailable] = useState(true);

  useEffect(() => {
    let active = true;

    if (!workflowId || !nodeId || !hasBuilderPermission) {
      setIsAvailable(false);
      return () => {
        active = false;
      };
    }

    setIsAvailable(true);
    workflowApi
      .getCostOptimizerAvailability(workflowId, nodeId)
      .then((availability) => {
        if (!active) return;
        setIsAvailable(
          availability.available && availability.permission.can_compare,
        );
      })
      .catch(() => {
        if (!active) return;
        setIsAvailable(false);
      });

    return () => {
      active = false;
    };
  }, [hasBuilderPermission, nodeId, workflowId]);

  const canUse = hasBuilderPermission && isAvailable;

  return (
    <button
      type="button"
      disabled={!canUse}
      onClick={(event) => {
        event.stopPropagation();
        if (!canUse) return;
        window.dispatchEvent(
          new CustomEvent('openCostOptimizer', {
            detail: { nodeId },
          }),
        );
      }}
      className="nodrag inline-flex items-center gap-1.5 rounded-md border border-emerald-200 bg-emerald-50 px-2.5 py-1.5 text-xs font-semibold text-emerald-700 transition-colors hover:border-emerald-300 hover:bg-emerald-100 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-50 disabled:text-gray-400"
      title={
        canUse
          ? '이 LLM 노드의 비용을 비교합니다.'
          : '워크플로우 수정 권한이 필요합니다.'
      }
    >
      <BarChart3 className="h-3.5 w-3.5" />
      A/B 테스트하기
    </button>
  );
};

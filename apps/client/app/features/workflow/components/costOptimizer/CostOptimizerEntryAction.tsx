import { useEffect, useState } from 'react';
import { BarChart3 } from 'lucide-react';
import { workflowApi } from '../../api/workflowApi';
import type { WorkflowPermissionResponse } from '../../types/Api';

interface CostOptimizerEntryActionProps {
  workflowId: string;
  nodeId: string;
  workflowAccess?: WorkflowPermissionResponse | null;
  onOpen?: () => void;
}

const canUseCostOptimizer = (workflowAccess?: WorkflowPermissionResponse | null) =>
  workflowAccess?.can_write === true;

export const CostOptimizerEntryAction = ({
  workflowId,
  nodeId,
  workflowAccess,
  onOpen,
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
        onOpen?.();
      }}
      className="nodrag inline-flex items-center justify-center gap-1.5 rounded-md border border-emerald-600 bg-emerald-600 px-2.5 py-1.5 text-xs font-semibold text-white shadow-sm transition-colors hover:border-emerald-700 hover:bg-emerald-700 disabled:cursor-not-allowed disabled:border-gray-200 disabled:bg-gray-50 disabled:text-gray-400 disabled:shadow-none"
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

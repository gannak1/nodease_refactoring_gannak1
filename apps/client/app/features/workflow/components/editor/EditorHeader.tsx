'use client';

import { AlertCircle, CheckCircle, ChevronRight, Loader2, X } from 'lucide-react';
import { useParams, useRouter } from 'next/navigation';
import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { isMockWorkflowId } from '../../utils/mockMode';

export default function EditorHeader() {
  const router = useRouter();
  const params = useParams();
  const {
    projectApp,
    fullscreenNodeId,
    closeNodeFullscreen,
    openTestPanel,
    nodes,
    testExecutionStatus,
    testNodeResults,
    currentExecutingNodeId,
    isTestUploading,
  } = useWorkflowStore();
  const isMockMode = isMockWorkflowId(params.id as string);
  const showTestStatus = testExecutionStatus !== 'idle';
  const currentExecutingNode = nodes.find(
    (node) => node.id === currentExecutingNodeId,
  );
  const currentExecutingNodeTitle =
    currentExecutingNode?.data.title || currentExecutingNodeId || '';
  const testStatusLabel =
    testExecutionStatus === 'running'
      ? isTestUploading
        ? '파일 업로드 중'
        : currentExecutingNodeTitle
          ? `테스트 실행 중 · ${currentExecutingNodeTitle}`
          : '테스트 실행 중'
      : testExecutionStatus === 'success'
        ? '테스트 완료'
        : '테스트 실패';
  const testStatusClassName =
    testExecutionStatus === 'failure'
      ? 'border-red-200 bg-red-50 text-red-700'
      : testExecutionStatus === 'success'
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
        : 'border-blue-200 bg-blue-50 text-blue-700';

  return (
    <header
      className={
        fullscreenNodeId
          ? 'hidden'
          : 'relative z-50 flex h-12 min-h-[48px] items-center justify-between border-b border-slate-200 bg-white px-5'
      }
      aria-hidden={fullscreenNodeId ? true : undefined}
    >
      {/* 1. Left: Breadcrumb */}
      <nav className="ml-2 flex items-center gap-2 text-sm">
        <button
          onClick={() => router.push('/dashboard/mymodule')}
          className="font-semibold text-slate-500 transition-colors hover:text-slate-950"
        >
          내 모듈
        </button>
        <ChevronRight className="h-4 w-4 text-slate-400" />
        <span className="font-black text-slate-950">
          {projectApp?.name || '이름 없는 모듈'}
        </span>
        {isMockMode && (
          <span className="rounded-full border border-amber-200 bg-amber-50 px-2 py-0.5 text-[11px] font-semibold text-amber-700">
            Mock 모드 · 저장 안 됨
          </span>
        )}
      </nav>

      <div className="flex min-w-0 shrink-0 items-center gap-2">
        {showTestStatus && (
          <div
            className={`flex h-8 max-w-[420px] items-center gap-2 rounded-md border px-2.5 text-xs font-semibold shadow-sm ${testStatusClassName}`}
          >
            {testExecutionStatus === 'running' ? (
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
            ) : testExecutionStatus === 'success' ? (
              <CheckCircle className="h-3.5 w-3.5 shrink-0" />
            ) : (
              <AlertCircle className="h-3.5 w-3.5 shrink-0" />
            )}
            <span className="min-w-0 truncate">{testStatusLabel}</span>
            <span className="shrink-0 text-[11px] opacity-75">
              {testNodeResults.length}개 완료
            </span>
            <button
              type="button"
              onClick={openTestPanel}
              className="ml-1 shrink-0 rounded border border-current/20 bg-white/70 px-2 py-0.5 text-[11px] transition-colors hover:bg-white"
            >
              결과 보기
            </button>
          </div>
        )}

        <div
          id="workflow-editor-header-actions"
          className="flex min-w-0 items-center gap-2"
        />

        {fullscreenNodeId && (
          <button
            type="button"
            onClick={closeNodeFullscreen}
            className="flex h-8 w-8 shrink-0 items-center justify-center rounded-md border border-gray-200 bg-white text-gray-500 shadow-sm transition-colors hover:border-gray-300 hover:bg-gray-50 hover:text-gray-800"
            title="노드 상세 닫기 (Esc)"
            aria-label="노드 상세 닫기"
          >
            <X className="h-4 w-4" />
          </button>
        )}
      </div>
    </header>
  );
}

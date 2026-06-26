import { DragEvent, useCallback, useEffect, useMemo } from 'react';
import { HelpCircle, Plus, Trash2 } from 'lucide-react';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import { UnregisteredVariablesAlert } from '../../../ui/UnregisteredVariablesAlert';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import { SlackPostNodeData } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';

// 노드 실행 필수 요건 체크
// 1. Webhook 모드: URL이 필수
// 2. API 모드: 봇 토큰과 채널 ID가 필수
// 3. 메시지 본문이 비어있지 않아야 함

interface SlackPostNodePanelProps {
  nodeId: string;
  data: SlackPostNodeData;
}

export function SlackPostNodePanel({ nodeId, data }: SlackPostNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();
  const mode = data.slackMode || 'api';

  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const handleUpdateData = useCallback(
    (key: keyof SlackPostNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );

  // 기본값 보정 (method, mode)
  useEffect(() => {
    if (data.method !== 'POST') {
      updateNodeData(nodeId, { method: 'POST' });
    }
    if (!data.slackMode) {
      updateNodeData(nodeId, { slackMode: 'api' });
    }
  }, [data.method, data.slackMode, nodeId, updateNodeData]);

  const payloadInfo = useMemo(() => {
    const payload: Record<string, unknown> = {
      text: data.message || '',
    };
    const warnings: string[] = [];

    if (mode === 'api' && data.channel?.trim()) {
      payload.channel = data.channel.trim();
    }

    if (data.blocks?.trim()) {
      try {
        payload.blocks = JSON.parse(data.blocks);
      } catch {
        warnings.push('블록 JSON을 해석할 수 없어 제외했습니다.');
      }
    }

    return {
      preview: JSON.stringify(payload, null, 2),
      warnings,
    };
  }, [data.message, data.blocks, data.channel, mode]);

  const availableVariables = useMemo(
    () =>
      (data.referenced_variables || [])
        .map((v) => (v.name || '').trim())
        .filter(Boolean),
    [data.referenced_variables],
  );

  const missingVariables = useMemo(() => {
    const regex = /{{\s*([^}]+?)\s*}}/g;
    const combined = (data.message || '') + (data.blocks || '');
    const missing = new Set<string>();
    let match;
    while ((match = regex.exec(combined)) !== null) {
      const varName = match[1].trim();
      if (varName && !availableVariables.includes(varName)) {
        missing.add(varName);
      }
    }
    return Array.from(missing);
  }, [data.message, data.blocks, availableVariables]);

  const trimmedUrl = (data.url || '').trim();
  const isWebhookUrlValid = useMemo(() => {
    if (mode !== 'webhook') return true;
    return (
      trimmedUrl.startsWith('https://hooks.slack.com/') &&
      trimmedUrl.includes('/services/')
    );
  }, [mode, trimmedUrl]);

  // Slack 전용 필드로 구성된 payload를 HTTP body에 자동 반영
  useEffect(() => {
    if (payloadInfo.preview !== data.body) {
      updateNodeData(nodeId, { body: payloadInfo.preview });
    }
  }, [payloadInfo.preview, data.body, nodeId, updateNodeData]);

  // 헤더 핸들러
  const handleAddHeader = useCallback(() => {
    const newHeaders = [...(data.headers || []), { key: '', value: '' }];
    updateNodeData(nodeId, { headers: newHeaders });
  }, [data.headers, nodeId, updateNodeData]);

  const handleRemoveHeader = useCallback(
    (index: number) => {
      const newHeaders = [...(data.headers || [])];
      newHeaders.splice(index, 1);
      updateNodeData(nodeId, { headers: newHeaders });
    },
    [data.headers, nodeId, updateNodeData],
  );

  const handleUpdateHeader = useCallback(
    (index: number, key: 'key' | 'value', value: string) => {
      const newHeaders = [...(data.headers || [])];
      newHeaders[index] = { ...newHeaders[index], [key]: value };
      updateNodeData(nodeId, { headers: newHeaders });
    },
    [data.headers, nodeId, updateNodeData],
  );

  const handleTextDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      updateNodeData(nodeId, {
        referenced_variables: upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      });
      return referenceName;
    },
    [data.referenced_variables, nodeId, updateNodeData],
  );

  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

  const handleModeChange = useCallback(
    (nextMode: 'webhook' | 'api') => {
      if (nextMode === mode) return;
      if (nextMode === 'webhook') {
        updateNodeData(nodeId, {
          slackMode: 'webhook',
          url: '',
          authType: 'none',
          authConfig: {},
        });
      } else {
        updateNodeData(nodeId, {
          slackMode: 'api',
          url: 'https://slack.com/api/chat.postMessage',
          authType: 'bearer',
          authConfig: { token: data.authConfig?.token || '' },
        });
      }
    },
    [mode, updateNodeData, nodeId, data.authConfig],
  );

  const preventJsonVariableDrop = useCallback(
    (event: DragEvent<HTMLTextAreaElement>) => {
      event.stopPropagation();
    },
    [],
  );

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-col gap-2">
        <label className="text-xs font-medium text-gray-700">전송 방식</label>
        <div className="bg-gray-100 p-1 rounded-lg inline-flex w-full gap-1">
          <button
            className={`flex-1 px-3 py-2 text-sm rounded-md transition-colors ${
              mode === 'api'
                ? 'bg-white shadow-sm text-[#4A154B] font-semibold'
                : 'text-gray-700 hover:bg-white/70'
            }`}
            onClick={() => handleModeChange('api')}
            type="button"
          >
            Slack API
          </button>
          <button
            className={`flex-1 px-3 py-2 text-sm rounded-md transition-colors ${
              mode === 'webhook'
                ? 'bg-white shadow-sm text-[#4A154B] font-semibold'
                : 'text-gray-700 hover:bg-white/70'
            }`}
            onClick={() => handleModeChange('webhook')}
            type="button"
          >
            Web Hook
          </button>
        </div>
        <p className="text-[11px] text-gray-600">
          Web Hook 또는 API 모드를 고르고, URL/토큰을 붙여넣으면 요청이 자동
          구성됩니다.
        </p>
      </div>

      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-700">
          {mode === 'api' ? 'Slack API 엔드포인트' : 'Web Hook URL'}
        </label>
        <div className="flex gap-2 items-center">
          <span className="px-2 py-1 rounded-md bg-[#4A154B]/10 text-[#4A154B] text-[11px] font-bold">
            POST
          </span>
          <input
            className="h-9 flex-1 rounded-md border border-gray-300 px-3 py-1 text-sm shadow-sm focus:border-[#4A154B] focus:outline-none focus:ring-1 focus:ring-[#4A154B] font-mono"
            placeholder={
              mode === 'api'
                ? 'https://slack.com/api/chat.postMessage'
                : 'https://hooks.slack.com'
            }
            value={data.url || ''}
            onChange={(e) => handleUpdateData('url', e.target.value)}
          />
        </div>
        {mode === 'webhook' ? (
          <div className="space-y-1 text-[10px] text-gray-500">
            <p>
              Incoming Webhook URL만 붙여넣으면 됩니다. URL 자체가 시크릿입니다.
            </p>
            <a
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-white text-[#4A154B] border border-[#4A154B]/40 text-xs font-semibold hover:bg-[#4A154B]/10 transition-colors"
              href="https://api.slack.com/messaging/webhooks"
              target="_blank"
              rel="noreferrer"
            >
              🔗 Slack Webhook 발급 가이드
            </a>
            {mode === 'webhook' && !trimmedUrl && (
              <ValidationAlert message="⚠️ Web Hook URL이 필요합니다." />
            )}
            {mode === 'webhook' && trimmedUrl && !isWebhookUrlValid && (
              <ValidationAlert
                message="⚠️ Web Hook URL 형식이 올바르지 않습니다."
                type="warning"
              />
            )}
            <div className="mt-2 border-b border-gray-200" />
          </div>
        ) : (
          <p className="text-[10px] text-gray-500">
            chat.postMessage 기본값입니다. 필요하면 다른 Slack API로 변경하세요.
          </p>
        )}

        {mode === 'api' && !trimmedUrl && (
          <ValidationAlert message="⚠️ Slack API 엔드포인트가 필요합니다." />
        )}
      </div>

      {mode === 'api' && (
        <>
          <div className="border-b border-gray-200" />
          <CollapsibleSection title="Slack API 인증" defaultOpen showDivider>
            <div className="flex flex-col gap-2">
              <label className="text-xs font-medium text-gray-700">
                봇 토큰 (Bearer)
              </label>
              <input
                type="password"
                className="h-9 w-full rounded border border-gray-300 px-3 text-sm font-mono focus:outline-none focus:border-[#4A154B]"
                placeholder="xoxb-..."
                value={data.authConfig?.token || ''}
                onChange={(e) =>
                  updateNodeData(nodeId, {
                    authType: 'bearer',
                    authConfig: { ...data.authConfig, token: e.target.value },
                  })
                }
              />
              <a
                className="inline-flex items-center gap-1 px-2 py-1 rounded bg-white text-[#4A154B] border border-[#4A154B]/40 text-xs font-semibold hover:bg-[#4A154B]/10 transition-colors w-fit"
                href="https://api.slack.com/authentication/token-types#bot"
                target="_blank"
                rel="noreferrer"
              >
                🔗 Slack 봇 토큰 발급 가이드
              </a>
              {!data.authConfig?.token?.trim() && (
                <ValidationAlert message="⚠️ 봇 토큰이 필요합니다." />
              )}

              <label className="text-xs font-medium text-gray-700">
                채널 ID
              </label>
              <input
                className="h-9 w-full rounded border border-gray-300 px-3 text-sm font-mono focus:outline-none focus:border-[#4A154B]"
                placeholder="C0123456789 (채널 ID)"
                value={data.channel || ''}
                onChange={(e) => handleUpdateData('channel', e.target.value)}
              />
              <p className="text-[10px] text-gray-500">
                공개/비공개 채널 ID를 입력하세요. # 없이 ID 형태로 넣는 것이
                안전합니다.
              </p>
              {!data.channel?.trim() && (
                <ValidationAlert message="⚠️ 채널 ID가 필요합니다." />
              )}
            </div>
          </CollapsibleSection>
        </>
      )}

      <CollapsibleSection
        title="헤더 / 타임아웃"
        showDivider
        icon={(expand) => (
          <button
            onClick={(e) => {
              e.stopPropagation();
              expand();
              handleAddHeader();
            }}
            className="p-1 hover:bg-gray-200 rounded transition-colors"
            title="헤더 추가"
          >
            <Plus className="w-3.5 h-3.5 text-gray-600" />
          </button>
        )}
      >
        <div className="flex flex-col gap-4">
          {/* 헤더 설정 영역 */}
          <div className="flex flex-col gap-2">
            <div className="flex flex-col gap-2">
              {data.headers?.map((header, index) => (
                <div key={index} className="flex gap-2 items-center">
                  <input
                    className="h-8 w-1/3 rounded border border-gray-300 px-2 text-xs font-mono focus:outline-none focus:border-[#4A154B]"
                    placeholder="키"
                    value={header.key}
                    onChange={(e) =>
                      handleUpdateHeader(index, 'key', e.target.value)
                    }
                  />
                  <input
                    className="h-8 flex-1 rounded border border-gray-300 px-2 text-xs font-mono focus:outline-none focus:border-[#4A154B]"
                    placeholder="값"
                    value={header.value}
                    onChange={(e) =>
                      handleUpdateHeader(index, 'value', e.target.value)
                    }
                  />
                  <button
                    className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded"
                    onClick={() => handleRemoveHeader(index)}
                    title="삭제"
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              ))}
              {(!data.headers || data.headers.length === 0) && (
                <div className="text-center text-xs text-gray-400 py-3 border border-dashed border-gray-200 rounded bg-gray-50/50">
                  <span className="block mb-1">
                    등록된 추가 헤더가 없습니다.
                  </span>
                  <span className="text-[10px] text-gray-400 opacity-80">
                    기본 <code>Content-Type: application/json</code> 은 자동
                    적용됩니다.
                  </span>
                </div>
              )}
            </div>

            {data.headers && data.headers.length > 0 && (
              <p className="text-[10px] text-gray-500 px-1">
                기본 <code>Content-Type: application/json</code> 이 자동
                적용됩니다. 추가로 필요한 헤더만 입력하세요.
              </p>
            )}
          </div>

          {/* 구분선 */}
          <div className="h-px bg-gray-100" />

          {/* 타임아웃 설정 영역 */}
          <div className="flex flex-col gap-1">
            <div className="flex items-center justify-between">
              <div className="flex items-center gap-1">
                <label className="text-xs font-medium text-gray-700">
                  타임아웃 (ms)
                </label>
                <div className="group relative inline-block">
                  <HelpCircle className="h-3.5 w-3.5 text-gray-400 cursor-help" />
                  <div className="absolute z-50 hidden group-hover:block w-56 p-2 text-[11px] text-gray-600 bg-white border border-gray-200 rounded-lg shadow-lg left-0 top-5">
                    요청이 이 시간 내에 끝나지 않으면 자동으로 실패 처리됩니다.
                    <div className="absolute -top-1 left-2 w-2 h-2 bg-white border-l border-t border-gray-200 rotate-45" />
                  </div>
                </div>
              </div>
              <input
                type="number"
                className="w-24 h-8 px-2 text-sm text-right border border-gray-300 rounded focus:outline-none focus:border-[#4A154B]"
                placeholder="5000"
                value={data.timeout || 5000}
                onChange={(e) =>
                  handleUpdateData('timeout', parseInt(e.target.value) || 0)
                }
              />
            </div>
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="메시지" defaultOpen={true} showDivider>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <div className="relative">
              <VariableTokenEditor
                className="min-h-24 text-sm focus:border-[#4A154B]"
                placeholder="예) :tada: 새 알림이 도착했어요! {{ 변수명 }} 로 치환 가능"
                value={data.message || ''}
                onChange={(value) => handleUpdateData('message', value)}
                onDropOutput={handleTextDropOutput}
                tokenLabels={tokenLabels}
                ariaLabel="Slack 메시지"
              />
            </div>
            {missingVariables.length > 0 && (
              <UnregisteredVariablesAlert variables={missingVariables} />
            )}
          </div>
        </div>
      </CollapsibleSection>

      <CollapsibleSection title="블록 (선택)" defaultOpen={false} showDivider>
        <div className="flex flex-col gap-3">
          <div className="rounded border border-dashed border-[#4A154B]/30 bg-[#4A154B]/5 p-3 text-[11px] text-gray-700 space-y-2">
            <div className="font-semibold text-[#4A154B] flex items-center gap-2">
              <span aria-hidden>🎯</span>
              <span>Slack 고급 메시지 구성 (선택 사항)</span>
            </div>
            <p>
              Block Kit Builder에서 메시지를 설계한 뒤, 생성된 JSON을 아래에
              붙여넣어 주세요.
            </p>
            <a
              className="inline-flex items-center gap-1 px-2 py-1 rounded bg-white text-[#4A154B] border border-[#4A154B]/40 text-xs font-semibold hover:bg-[#4A154B]/10 transition-colors"
              href="https://app.slack.com/block-kit-builder"
              target="_blank"
              rel="noreferrer"
            >
              🔗 Block Kit Builder 열기
            </a>
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">
              블록(JSON)
            </label>
            <div className="relative">
              <textarea
                className="min-h-28 w-full resize-y rounded border border-gray-300 p-2 font-mono text-xs text-gray-800 shadow-sm focus:border-[#4A154B] focus:outline-none"
                placeholder='[ { "type": "section", "text": { "type": "mrkdwn", "text": "*Hello*" } } ]'
                value={data.blocks || ''}
                onChange={(event) => handleUpdateData('blocks', event.target.value)}
                onDragOver={preventJsonVariableDrop}
                onDrop={preventJsonVariableDrop}
                aria-label="Slack 블록 JSON"
                data-variable-drop-disabled="true"
              />
            </div>
          </div>
          <p className="text-[10px] text-gray-500">
            JSON이 유효하지 않으면 페이로드에서 제외되고 경고가 표시됩니다.
          </p>
        </div>
      </CollapsibleSection>

      <CollapsibleSection
        title="페이로드 미리보기 (HTTP 본문)"
        defaultOpen
        showDivider
      >
        <div className="flex flex-col gap-2">
          <textarea
            className="w-full h-32 rounded border border-gray-300 p-2 text-xs font-mono shadow-sm bg-gray-50"
            readOnly
            value={payloadInfo.preview}
            spellCheck={false}
          />
          {payloadInfo.warnings.length > 0 && (
            <div className="text-[10px] text-red-600 bg-red-50 border border-red-100 rounded p-2">
              {payloadInfo.warnings.map((warning, idx) => (
                <div key={idx}>• {warning}</div>
              ))}
            </div>
          )}
          <p className="text-[10px] text-gray-500">
            이 영역은 옵션이 아니라, 실제로 전송될 HTTP 본문을 미리 보여주는
            용도입니다.
          </p>
        </div>
      </CollapsibleSection>
    </div>
  );
}

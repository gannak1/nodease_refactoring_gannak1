import { useCallback, useEffect, useMemo, useState } from 'react';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  externalActionCredentialApi,
  ExternalActionCredentialOption,
} from '@/app/features/workflow/api/externalActionCredentialApi';
import { SlackPostNodeData } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import { RoundedSelect } from '../../../ui/RoundedSelect';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';
import { UnregisteredVariablesAlert } from '../../../ui/UnregisteredVariablesAlert';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import {
  collectSlackTemplateVariables,
  isNonEmptySlackJsonArrayTemplate,
  isValidSlackJsonArrayTemplate,
} from '../../../../utils/slackDelivery';

interface SlackPostNodePanelProps {
  nodeId: string;
  data: SlackPostNodeData;
}

export function SlackPostNodePanel({ nodeId, data }: SlackPostNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();
  const [credentials, setCredentials] = useState<ExternalActionCredentialOption[]>(
    [],
  );
  const [credentialsLoading, setCredentialsLoading] = useState(true);
  const [credentialsError, setCredentialsError] = useState(false);
  const mode = data.slackMode || 'api';
  const provider = mode === 'api' ? 'slack_api' : 'slack_webhook';
  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );
  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables || [], upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );

  useEffect(() => {
    let active = true;
    setCredentialsLoading(true);
    setCredentialsError(false);
    externalActionCredentialApi
      .listAvailable()
      .then((options) => {
        if (active) setCredentials(options);
      })
      .catch(() => {
        if (active) setCredentialsError(true);
      })
      .finally(() => {
        if (active) setCredentialsLoading(false);
      });
    return () => {
      active = false;
    };
  }, []);

  const update = useCallback(
    (next: Partial<SlackPostNodeData>) => updateNodeData(nodeId, next),
    [nodeId, updateNodeData],
  );
  const handleDrop = useCallback(
    (output: DraggedOutputVariable) => {
      const name = getDroppedOutputReferenceName(
        data.referenced_variables || [],
        output,
        'value_selector',
      );
      update({
        referenced_variables: upsertNamedSelector(
          data.referenced_variables || [],
          output,
          'value_selector',
        ),
      });
      return name;
    },
    [data.referenced_variables, update],
  );
  const missingVariables = useMemo(() => {
    const configured = new Set(
      (data.referenced_variables || [])
        .map((item) => item.name)
        .filter(Boolean),
    );
    return collectSlackTemplateVariables(
      data.message,
      data.blocks,
      data.attachments,
      mode === 'api' ? data.channel : undefined,
      data.thread_ts,
      data.username,
      data.icon_emoji,
    ).filter((name) => !configured.has(name));
  }, [
    data.attachments,
    data.blocks,
    data.channel,
    data.icon_emoji,
    data.message,
    data.referenced_variables,
    data.thread_ts,
    data.username,
    mode,
  ]);
  const hasLegacyHttpConfiguration =
    Boolean(data.authConfig && Object.keys(data.authConfig).length > 0) ||
    Boolean(data.url?.trim()) ||
    (data.method !== undefined && data.method !== 'POST') ||
    (data.headers?.length || 0) > 0 ||
    Boolean(data.body?.trim()) ||
    (data.timeout !== undefined && data.timeout !== 5000) ||
    (mode === 'api' && data.authType !== undefined && data.authType !== 'bearer') ||
    (mode === 'webhook' && data.authType !== undefined && data.authType !== 'none');
  const blocksInvalid =
    Boolean(data.blocks?.trim()) &&
    !isValidSlackJsonArrayTemplate(data.blocks || '');
  const attachmentsInvalid =
    Boolean(data.attachments?.trim()) &&
    !isValidSlackJsonArrayTemplate(data.attachments || '');
  const hasDeliveryPayload =
    Boolean(data.message?.trim()) ||
    isNonEmptySlackJsonArrayTemplate(data.blocks || '') ||
    isNonEmptySlackJsonArrayTemplate(data.attachments || '');
  const availableCredentials = credentials.filter(
    (credential) => credential.provider === provider,
  );
  const credentialUnavailable =
    Boolean(data.credential_id) &&
    !credentialsLoading &&
    !availableCredentials.some((credential) => credential.id === data.credential_id);

  return (
    <div className="flex flex-col gap-4 p-4 text-foreground">
      <div className="flex gap-2" role="group" aria-label="Slack 전달 방식">
        {(['api', 'webhook'] as const).map((candidate) => (
          <button
            key={candidate}
            type="button"
            className={`rounded border px-3 py-1.5 text-xs ${
              mode === candidate
                ? 'border-[#4A154B] bg-[#4A154B] text-white'
                : 'border-border bg-background text-foreground'
            }`}
            onClick={() =>
              update({
                slackMode: candidate,
                channel: candidate === 'api' ? data.channel || '' : '',
                credential_id: null,
                configuration_state: 'unresolved',
                url: undefined,
                authConfig: undefined,
                authType: candidate === 'webhook' ? 'none' : undefined,
              })
            }
          >
            {candidate === 'api' ? 'Slack API' : 'Incoming Webhook'}
          </button>
        ))}
      </div>

      {hasLegacyHttpConfiguration ? (
        <div className="rounded border border-amber-500/50 bg-amber-500/10 p-3 text-xs text-foreground">
          <p>기존 직접 인증 설정은 사용할 수 없습니다.</p>
          <button
            type="button"
            className="mt-2 rounded border border-amber-500 px-2 py-1 font-medium"
            onClick={() =>
              update({
                method: undefined,
                headers: undefined,
                body: undefined,
                timeout: undefined,
                authType: mode === 'webhook' ? 'none' : undefined,
                url: undefined,
                authConfig: undefined,
                configuration_state: data.credential_id ? 'resolved' : 'unresolved',
              })
            }
          >
            기존 직접 인증 설정 제거
          </button>
        </div>
      ) : null}

      <CollapsibleSection title="Slack Credential" defaultOpen showDivider>
        <RoundedSelect
          value={data.credential_id || ''}
          onChange={(value) =>
            update({
              credential_id: value || null,
              configuration_state: value ? 'resolved' : 'unresolved',
            })
          }
          options={availableCredentials.map((credential) => ({
            value: credential.id,
            label: credential.credential_name,
          }))}
          placeholder={
            credentialsLoading
              ? '불러오는 중'
              : mode === 'api'
                ? 'Slack API credential 선택'
                : 'Slack Webhook credential 선택'
          }
        />
        {!data.credential_id && !credentialsLoading ? (
          <ValidationAlert message="Slack credential을 선택해주세요." />
        ) : null}
        {credentialUnavailable ? (
          <ValidationAlert message="선택한 Slack credential을 사용할 수 없습니다." />
        ) : null}
        {credentialsError ? (
          <ValidationAlert message="Slack credential 목록을 불러오지 못했습니다." />
        ) : null}
      </CollapsibleSection>

      {mode === 'api' ? (
        <CollapsibleSection title="Slack API 설정" defaultOpen showDivider>
          <div className="flex flex-col gap-2">
            <label className="text-xs font-medium">채널 ID</label>
            <input
              className="h-9 rounded border border-border bg-background px-3 text-sm text-foreground"
              value={data.channel || ''}
              onChange={(event) => update({ channel: event.target.value })}
              placeholder="C0123456789"
            />
          </div>
        </CollapsibleSection>
      ) : null}

      <CollapsibleSection title="메시지" defaultOpen showDivider>
        <VariableTokenEditor
          className="min-h-24 text-sm"
          value={data.message || ''}
          onChange={(message) => update({ message })}
          onDropOutput={handleDrop}
          tokenLabels={tokenLabels}
          ariaLabel="Slack 메시지"
        />
        {missingVariables.length > 0 && (
          <UnregisteredVariablesAlert variables={missingVariables} />
        )}
      </CollapsibleSection>

      <CollapsibleSection title="블록 (선택)" showDivider>
        <textarea
          className="min-h-28 w-full rounded border border-border bg-background p-2 font-mono text-xs text-foreground"
          value={data.blocks || ''}
          onChange={(event) => update({ blocks: event.target.value })}
          placeholder='[ { "type": "section" } ]'
          aria-label="Slack 블록 JSON"
        />
        {blocksInvalid ? (
          <ValidationAlert message="블록은 유효한 JSON 배열이어야 합니다." />
        ) : null}
      </CollapsibleSection>

      <CollapsibleSection title="첨부 (선택)" showDivider>
        <textarea
          className="min-h-28 w-full rounded border border-border bg-background p-2 font-mono text-xs text-foreground"
          value={data.attachments || ''}
          onChange={(event) => update({ attachments: event.target.value })}
          placeholder='[ { "color": "#4A154B", "text": "알림" } ]'
          aria-label="Slack 첨부 JSON"
        />
        {attachmentsInvalid ? (
          <ValidationAlert message="첨부는 유효한 JSON 배열이어야 합니다." />
        ) : null}
      </CollapsibleSection>

      {!hasDeliveryPayload ? (
        <ValidationAlert message="메시지, 블록 또는 첨부 중 하나가 필요합니다." />
      ) : null}
      {(!data.credential_id || (mode === 'api' && !data.channel)) ? (
        <ValidationAlert message="Slack 전달 설정을 완료해야 실행할 수 있습니다." />
      ) : null}
    </div>
  );
}

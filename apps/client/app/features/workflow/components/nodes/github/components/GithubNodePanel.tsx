import { useCallback, useEffect, useMemo, useState } from 'react';

import { useWorkflowStore } from '@/app/features/workflow/store/useWorkflowStore';
import {
  externalActionCredentialApi,
  ExternalActionCredentialOption,
} from '@/app/features/workflow/api/externalActionCredentialApi';
import { GithubNodeData } from '../../../../types/Nodes';
import { getUpstreamNodes } from '../../../../utils/getUpstreamNodes';
import { CollapsibleSection } from '../../ui/CollapsibleSection';
import { RoundedSelect } from '../../../ui/RoundedSelect';
import { ValidationAlert } from '../../../ui/ValidationAlert';
import {
  DraggedOutputVariable,
  getDroppedOutputReferenceName,
  getTokenLabelMap,
  upsertNamedSelector,
} from '@/app/features/workflow/utils/nodeVariablePorts';
import { VariableTokenEditor } from '../../ui/VariableTokenEditor';

interface GithubNodePanelProps {
  nodeId: string;
  data: GithubNodeData;
}

export function GithubNodePanel({ nodeId, data }: GithubNodePanelProps) {
  const { updateNodeData, nodes, edges } = useWorkflowStore();
  const [credentials, setCredentials] = useState<ExternalActionCredentialOption[]>(
    [],
  );
  const [credentialsLoading, setCredentialsLoading] = useState(true);
  const [credentialsError, setCredentialsError] = useState(false);

  useEffect(() => {
    let active = true;
    setCredentialsLoading(true);
    setCredentialsError(false);
    externalActionCredentialApi
      .listAvailable()
      .then((options) => {
        if (active) {
          setCredentials(options.filter((option) => option.provider === 'github'));
        }
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

  const upstreamNodes = useMemo(
    () => getUpstreamNodes(nodeId, nodes, edges),
    [nodeId, nodes, edges],
  );

  const handleUpdateData = useCallback(
    (key: keyof GithubNodeData, value: unknown) => {
      updateNodeData(nodeId, { [key]: value });
    },
    [nodeId, updateNodeData],
  );

  const handleTextDropOutput = useCallback(
    (output: DraggedOutputVariable) => {
      const referenceName = getDroppedOutputReferenceName(
        data.referenced_variables,
        output,
        'value_selector',
      );
      handleUpdateData(
        'referenced_variables',
        upsertNamedSelector(
          data.referenced_variables,
          output,
          'value_selector',
        ),
      );
      return referenceName;
    },
    [data.referenced_variables, handleUpdateData],
  );

  const tokenLabels = useMemo(
    () => getTokenLabelMap(data.referenced_variables, upstreamNodes),
    [data.referenced_variables, upstreamNodes],
  );
  const credentialMissing = !data.credential_id;
  const credentialUnavailable =
    Boolean(data.credential_id) &&
    !credentialsLoading &&
    !credentials.some((credential) => credential.id === data.credential_id);
  const ownerMissing = !data.repo_owner?.trim();
  const repoMissing = !data.repo_name?.trim();
  const prMissing = !data.pr_number;
  const hasLegacyCredentialConfiguration =
    data.api_token !== undefined ||
    data.token !== undefined ||
    data.authConfig !== undefined;

  return (
    <div className="flex flex-col gap-2">
      <div className="flex flex-col gap-1">
        <label className="text-xs font-medium text-gray-700">작업</label>
        <RoundedSelect
          value={data.action || 'get_pr'}
          onChange={(value) => {
            const action = value as GithubNodeData['action'];
            handleUpdateData('action', action);
            handleUpdateData(
              'title',
              action === 'comment_pr' ? 'Comment on PR' : 'Get PR Diff',
            );
          }}
          options={[
            { label: 'Get PR Diff', value: 'get_pr' },
            { label: 'Comment on PR', value: 'comment_pr' },
          ]}
        />
      </div>
      <div className="border-b border-gray-200" />

      <CollapsibleSection title="GitHub Credential" defaultOpen showDivider>
        <RoundedSelect
          value={data.credential_id || ''}
          onChange={(value) =>
            updateNodeData(nodeId, {
              credential_id: value || null,
              configuration_state: value ? 'resolved' : 'unresolved',
              api_token: undefined,
              token: undefined,
              authConfig: undefined,
            })
          }
          options={credentials.map((credential) => ({
            label: credential.credential_name,
            value: credential.id,
          }))}
          placeholder={
            credentialsLoading ? '불러오는 중' : 'GitHub credential 선택'
          }
        />
        {credentialMissing && !credentialsLoading ? (
          <ValidationAlert message="GitHub credential을 선택해주세요." />
        ) : null}
        {credentialUnavailable ? (
          <ValidationAlert message="선택한 GitHub credential을 사용할 수 없습니다." />
        ) : null}
        {credentialsError ? (
          <ValidationAlert message="GitHub credential 목록을 불러오지 못했습니다." />
        ) : null}
        {hasLegacyCredentialConfiguration ? (
          <div className="mt-2 rounded border border-amber-500/50 bg-amber-500/10 p-2 text-xs text-foreground">
            <p>기존 직접 인증 설정은 사용할 수 없습니다.</p>
            <button
              type="button"
              className="mt-2 rounded border border-amber-500 px-2 py-1 font-medium"
              onClick={() =>
                updateNodeData(nodeId, {
                  api_token: undefined,
                  token: undefined,
                  authConfig: undefined,
                  configuration_state: data.credential_id
                    ? 'resolved'
                    : 'unresolved',
                })
              }
            >
              기존 직접 인증 설정 제거
            </button>
          </div>
        ) : null}
      </CollapsibleSection>

      <CollapsibleSection title="저장소 정보" defaultOpen showDivider>
        <div className="flex flex-col gap-3">
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">소유자</label>
            <input
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
              placeholder="예) facebook"
              value={data.repo_owner || ''}
              onChange={(event) => handleUpdateData('repo_owner', event.target.value)}
            />
            {ownerMissing ? (
              <ValidationAlert message="소유자를 입력해주세요." />
            ) : null}
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">저장소</label>
            <input
              className="h-8 w-full rounded border border-gray-300 px-2 text-sm font-mono focus:border-blue-500 focus:outline-none"
              placeholder="예) react"
              value={data.repo_name || ''}
              onChange={(event) => handleUpdateData('repo_name', event.target.value)}
            />
            {repoMissing ? (
              <ValidationAlert message="저장소 이름을 입력해주세요." />
            ) : null}
          </div>
          <div className="flex flex-col gap-1">
            <label className="text-xs font-medium text-gray-700">PR 번호</label>
            <VariableTokenEditor
              className="min-h-9 font-mono text-xs"
              placeholder="예) 123"
              value={data.pr_number || ''}
              onChange={(value) => handleUpdateData('pr_number', value)}
              onDropOutput={handleTextDropOutput}
              tokenLabels={tokenLabels}
              ariaLabel="GitHub PR 번호"
            />
            {prMissing ? (
              <ValidationAlert message="PR 번호를 입력해주세요." />
            ) : null}
          </div>
        </div>
      </CollapsibleSection>

      {data.action === 'comment_pr' ? (
        <CollapsibleSection title="코멘트 내용" defaultOpen showDivider>
          <div className="flex flex-col gap-2">
            <VariableTokenEditor
              className="min-h-32 font-mono text-xs"
              placeholder="코멘트 내용을 입력하세요..."
              value={data.comment_body || ''}
              onChange={(value) => handleUpdateData('comment_body', value)}
              onDropOutput={handleTextDropOutput}
              tokenLabels={tokenLabels}
              ariaLabel="GitHub 코멘트"
            />
          </div>
        </CollapsibleSection>
      ) : null}
    </div>
  );
}

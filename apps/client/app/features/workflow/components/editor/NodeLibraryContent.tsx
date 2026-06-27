'use client';

import { useState } from 'react';
import { Search } from 'lucide-react';
import { nodeRegistry, NodeDefinition } from '../../config/nodeRegistry';
import { useWorkflowStore } from '../../store/useWorkflowStore';

interface NodeLibraryContentProps {
  onDragStart?: (
    event: React.DragEvent,
    nodeType: string,
    nodeDef: NodeDefinition,
  ) => void;
  onSelect?: (nodeType: string, nodeDef: NodeDefinition) => void;
  hoveredNode?: string | null;
  onHoverNode?: (
    nodeId: string | null,
    node: any,
    event: React.MouseEvent,
  ) => void;
  disabledNodeTypes?: string[];
}

// 탭 정의 (이미지와 유사하게 구성)
const TABS = [
  { id: 'nodes', label: '노드' },
  { id: 'tools', label: '도구' },
  { id: 'start', label: '시작' },
] as const;

export const NodeLibraryContent = ({
  onDragStart,
  onSelect,
  hoveredNode,
  onHoverNode,
  disabledNodeTypes = [],
}: NodeLibraryContentProps) => {
  // 노드 개수 확인하여 초기 탭 결정
  // 처음 생성 시: 시작 노드 1개만 존재 -> 'start' 탭
  // 이후: 노드가 2개 이상이거나 시작 노드가 아닌 경우 -> 'nodes' 탭
  const nodes = useWorkflowStore((state) => state.nodes);
  const isInitialState =
    nodes.length === 1 &&
    (nodes[0].type === 'startNode' ||
      nodes[0].type === 'webhookTrigger' ||
      nodes[0].type === 'scheduleTrigger');
  const initialTab = isInitialState ? 'start' : 'nodes';

  const [activeTab, setActiveTab] =
    useState<(typeof TABS)[number]['id']>(initialTab);
  const [searchQuery, setSearchQuery] = useState('');

  // 탭에 따른 카테고리 필터링
  const getFilteredCategories = () => {
    switch (activeTab) {
      case 'start':
        return ['trigger'];
      case 'tools':
        return ['plugin', 'workflow'];
      case 'nodes':
      default:
        return ['llm', 'logic', 'data', 'database'];
    }
  };

  // 노드 필터링 로직
  const filteredNodes = nodeRegistry.filter((node) => {
    const matchesSearch =
      node.name.toLowerCase().includes(searchQuery.toLowerCase()) ||
      node.description?.toLowerCase().includes(searchQuery.toLowerCase()) ||
      false;

    const matchesTab = getFilteredCategories().includes(node.category);

    return matchesSearch && matchesTab && node.implemented;
  });

  // 노드 비활성화 체크
  const isNodeDisabled = (nodeType: string) => {
    return disabledNodeTypes.includes(nodeType);
  };

  return (
    <div className="flex h-full w-full select-none flex-col bg-white">
      {/* 1. Tabs */}
      <div className="flex items-center border-b border-slate-100 px-4 pb-2 pt-4">
        <div className="w-full grid grid-cols-3 gap-1">
          {TABS.map((tab) => (
            <button
              key={tab.id}
              onClick={() => setActiveTab(tab.id)}
              className={`relative flex w-full justify-center pb-2 text-sm font-semibold transition-colors ${
                activeTab === tab.id
                  ? 'text-slate-950'
                  : 'text-slate-500 hover:text-slate-800'
              }`}
            >
              {tab.label}
              {activeTab === tab.id && (
                <div className="absolute bottom-0 left-0 h-0.5 w-full rounded-t-full bg-slate-950" />
              )}
            </button>
          ))}
        </div>
      </div>

      {/* 2. Search */}
      <div className="px-4 py-3">
        <div className="relative">
          <Search className="absolute left-2.5 top-1/2 h-4 w-4 -translate-y-1/2 text-slate-400" />
          <input
            type="text"
            placeholder="검색 노드"
            value={searchQuery}
            onChange={(e) => setSearchQuery(e.target.value)}
            className="h-8 w-full rounded-md border border-slate-200 bg-slate-50 pl-9 pr-3 text-sm font-semibold text-slate-900 transition-all placeholder:text-slate-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-blue-100"
          />
        </div>
      </div>

      {/* 3. Node List */}
      <div className="flex-1 overflow-y-auto px-2 pb-4 scrollbar-hide">
        {filteredNodes.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-8 text-slate-400">
            <p className="text-sm font-semibold">검색 결과가 없습니다</p>
          </div>
        ) : (
          <div className="space-y-4">
            {filteredNodes.map((node) => (
              <div
                key={node.id}
                draggable={
                  !!onDragStart &&
                  !isNodeDisabled(node.type) &&
                  node.category !== 'workflow'
                }
                onDragStart={(e) => {
                  if (
                    !isNodeDisabled(node.type) &&
                    node.category !== 'workflow'
                  ) {
                    onDragStart?.(e, node.type, node);
                  }
                }}
                onClick={() => {
                  if (!isNodeDisabled(node.type)) {
                    onSelect?.(node.type, node);
                  }
                }}
                onMouseEnter={(e) => onHoverNode?.(node.id, node, e)}
                onMouseLeave={(e) => onHoverNode?.(null, null, e)}
                className={`group flex items-center gap-3 rounded-lg p-2 transition-all ${
                  isNodeDisabled(node.type)
                    ? 'opacity-50 cursor-not-allowed'
                    : 'cursor-pointer hover:bg-slate-100 active:scale-[0.98]'
                } ${
                  hoveredNode === node.id && !isNodeDisabled(node.type)
                    ? 'bg-slate-100'
                    : ''
                }`}
              >
                <div
                  className="w-8 h-8 rounded-lg flex items-center justify-center shadow-sm text-white transition-transform group-hover:scale-105"
                  style={{ backgroundColor: node.color }}
                >
                  {node.icon}
                </div>
                <div className="flex-1 min-w-0">
                  <div className="truncate text-sm font-semibold text-slate-950">
                    {node.name}
                  </div>
                  {/* Description is hidden in list, shown in hover card usually */}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
};

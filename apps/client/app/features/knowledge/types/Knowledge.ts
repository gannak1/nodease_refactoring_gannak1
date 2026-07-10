export type SourceType = 'FILE' | 'API' | 'DB';

export interface IngestionResponse {
  knowledge_base_id: string;
  document_id: string;
  status: string;
  message: string;
}

export interface KnowledgeBaseCreate {
  name: string;
  description?: string;
  embedding_model: string;
}

export interface KnowledgeCreateRequest {
  sourceType?: SourceType;
  file?: File;

  // [NEW] S3 Direct Upload Fields
  s3FileUrl?: string;
  s3FileKey?: string;

  apiUrl?: string;
  apiMethod?: string;
  apiHeaders?: string;
  apiBody?: string;
  connectionId?: string;

  name?: string;
  description?: string;
  embeddingModel: string;
  topK: number;
  similarity: number;
  chunkSize: number;
  chunkOverlap: number;
  knowledgeBaseId?: string;
}

export interface KnowledgeBaseResponse {
  id: string;
  organization_id?: string;
  name: string;
  description?: string;
  safe_metadata?: Record<string, unknown>;
  document_count: number;
  created_at: string;
  updated_at?: string;
  source_types?: SourceType[];
  embedding_model: string;
}

export interface DocumentResponse {
  updated_at: string;
  id: string;
  filename: string;
  status:
    | 'pending'
    | 'indexing'
    | 'processing'
    | 'completed'
    | 'failed'
    | 'waiting_for_approval';
  created_at: string;
  error_message?: string;
  chunk_count: number;
  token_count: number;
  chunk_size?: number;

  chunk_overlap?: number;
  parsing_strategy?: 'general' | 'llamaparse';
  source_type?: SourceType;
  meta_info?: {
    cost_estimate?: {
      pages: number;
      credits: number;
      cost_usd: number;
    };
    strategy?: string;
    segment_identifier?: string;
    remove_urls_emails?: boolean;
    remove_whitespace?: boolean;
    [key: string]: any; // Allow other properties
  };
}

export interface KnowledgeBaseDetailResponse extends KnowledgeBaseResponse {
  documents: DocumentResponse[];
}

export type KnowledgeCollectionAction = 'read' | 'route' | 'manage' | 'sync';
export type KnowledgeCollectionVisibility = 'private' | 'public';

export interface KnowledgeCollectionResponse {
  id: string;
  organization_id: string;
  name: string;
  description?: string | null;
  is_system_managed: boolean;
  sync_state: string;
  lifecycle_state: 'active' | 'archived' | 'deleted';
  visibility: KnowledgeCollectionVisibility;
  linked_kb_count_bucket: string;
  active_kb_count_bucket: string;
  can_read: boolean;
  can_route: boolean;
  can_manage: boolean;
  can_sync: boolean;
  safe_metadata: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

export interface KnowledgeCollectionListResponse {
  collections: KnowledgeCollectionResponse[];
  can_create_collection: boolean;
  can_change_public_visibility: boolean;
}

export interface KnowledgeCollectionItemResponse {
  item_id: string;
  knowledge_base_id: string;
  safe_label?: string | null;
  lifecycle_state: string;
  sync_state: string;
  rank: number;
  can_manage_kb: boolean;
  can_use_kb: boolean;
}

export interface KnowledgeCollectionItemsResponse {
  items: KnowledgeCollectionItemResponse[];
}

export interface KnowledgeCollectionLinkCandidate {
  knowledge_base_id: string;
  safe_label?: string | null;
  disabled: boolean;
  safe_reason_code?: string | null;
}

export interface KnowledgeCollectionLinkCandidatesResponse {
  candidates: KnowledgeCollectionLinkCandidate[];
}

export interface KnowledgeCollectionPermissionResponse {
  permission_id: string;
  subject_type: 'team' | 'user';
  subject_id: string;
  subject_safe_label?: string | null;
  permission_action: KnowledgeCollectionAction;
}

export interface KnowledgeCollectionPermissionsResponse {
  permissions: KnowledgeCollectionPermissionResponse[];
}

export interface KnowledgeCollectionVisibilityResponse {
  collection: KnowledgeCollectionResponse;
  public_runtime_effect: string;
  linked_kb_count_bucket: string;
  active_kb_count_bucket: string;
  sensitive_content_warning: string;
}

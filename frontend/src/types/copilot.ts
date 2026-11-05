// Types. They mirror the backend schemas in app/schemas/copilot.py.

export type RecordType =
  | 'investigation' | 'investigation_note' | 'event' | 'observation' | 'assessment'
  | 'assessment_review' | 'evidence' | 'data_source' | 'media_asset' | 'scenario'

export const RECORD_TYPES: RecordType[] = [
  'investigation', 'investigation_note', 'event', 'observation', 'assessment',
  'assessment_review', 'evidence', 'data_source', 'media_asset', 'scenario',
]

export interface SearchHit {
  record_type: RecordType
  record_id: string
  document_id: string
  chunk_id: string
  chunk_position: number
  document_version: number
  title: string | null
  section: string | null
  excerpt: string
  score: number
  matched_terms: string[]
  matching_chunks: number
  source_time: string | null
  source_id: string | null
  review_status: string | null
  investigation_id: string | null
  source_ref: string
  extraction_method: string
  content_available: boolean
  stale: boolean
  link: string | null
}

export interface SearchResponse {
  items: SearchHit[]
  total: number
  page: number
  page_size: number
  query_terms: string[]
  candidates_truncated: boolean
  notice: string | null
  filters_applied: Record<string, unknown>
  method: { lexical: string; semantic: boolean; semantic_note: string; ranking_note: string }
}

export interface SearchParams {
  q: string
  recordTypes?: string[]
  investigationId?: string
  sourceId?: string
  reviewStatus?: string
  timeFrom?: string
  timeTo?: string
  documentVersion?: number
  page?: number
  pageSize?: number
}

export type ClaimKind = 'source_statement' | 'record_summary' | 'generated_summary' | 'system_note'

export interface Claim {
  id: string
  text: string
  kind: ClaimKind
  citation_ids: string[]
  support: string | null
  support_ratio: number | null
  withheld?: boolean | null
  source_changed?: boolean | null
}

export type CitationStatus = 'verified' | 'source_changed' | 'unavailable' | 'access_revoked' | 'unverified'

export interface Citation {
  id?: string | null
  record_type: string
  record_id: string
  document_version: number | null
  chunk_position: number | null
  title: string | null
  section: string | null
  quote: string | null
  source_time: string | null
  link: string | null
  status: CitationStatus
  status_note: string | null
}

export interface Conflict {
  description: string
  left_citation_ids: string[]
  right_citation_ids: string[]
  basis: string
  resolved: boolean
  withheld?: boolean
}

export interface SideBySideItem {
  citation_id: string
  record_type: string
  record_id: string
  title: string | null
  source_time: string | null
  source_id: string | null
  review_status: string | null
  text: string
  link: string | null
}

export interface Answer {
  task: string
  mode: 'extractive' | 'generative' | 'deterministic'
  status: string
  generation: { available: boolean; provider: string; reason: string | null; notice: string | null }
  claims: Claim[]
  citations: Citation[]
  uncertainty: string[]
  missing_information: string[]
  conflicts: Conflict[]
  followups: string[]
  records_used: { record_type: string; record_id: string; title: string | null; link: string | null }[]
  retrieval: { weak_matches?: { record_type: string; record_id: string; title: string | null; matched_terms: string[]; link: string | null }[]; [k: string]: unknown }
  generated_at: string
  side_by_side?: SideBySideItem[]
  differences?: string[]
  shared_terms?: string[]
  draft_markdown?: string
  draft_title?: string
  draft_withheld?: boolean
  truncated?: boolean
  reverified_at?: string
}

export interface AskResponse {
  answer: Answer
  conversation_id: string | null
  message_id: string | null
}

export interface AskRequest {
  task: 'question' | 'summarize_investigation' | 'chronology' | 'compare' | 'report_draft' | 'related'
  question?: string
  investigation_id?: string
  record_types?: string[]
  record_refs?: { record_type: string; record_id: string }[]
  conversation_id?: string
  save?: boolean
  report_title?: string
}

export interface ConversationSummary {
  id: string
  title: string | null
  investigation_id: string | null
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationMessage {
  id: string
  role: 'user' | 'assistant'
  content: string | null
  task: string | null
  created_at: string
  answer_mode: string | null
  answer: Answer | null
}

export interface ConversationDetail {
  id: string
  title: string | null
  investigation_id: string | null
  created_at: string
  updated_at: string
  messages: ConversationMessage[]
  notice: string
}

export interface Capabilities {
  keyword_search: { available: boolean; method: string }
  semantic_search: { available: boolean; provider: string; reason: string }
  generation: { available: boolean; provider: string; reason: string | null; external: boolean }
  record_types: RecordType[]
  limits: { max_query_chars: number; max_results: number; max_question_chars: number; rate_limit_per_minute: number }
  can_index: boolean
  can_evaluate: boolean
}

export interface IndexStatus {
  documents_by_status: Record<string, number>
  documents_by_type: Record<string, number>
  chunk_count: number
  stale_documents: number
  last_run: { id: string; scope: string; status: string; counts: Record<string, number>; started_at: string; finished_at: string | null } | null
  errors: { record_type: string; record_id: string; error: string }[]
  semantic_search_available: boolean
}

export interface IndexRunResult {
  run_id: string
  scope: string
  status: string
  counts: Record<string, number>
  errors: { record_type: string; record_id: string; error: string }[]
  started_at: string
  finished_at: string | null
}

export interface EvalResult {
  dataset: string
  disclaimer: string
  documents: number
  queries: number
  retrieval: { ks: number[]; mean: Record<string, number | null>; mrr: number | null }
  answer_checks: Record<string, boolean | { passed: number; total: number }>
}

export const hitKey = (h: Pick<SearchHit, 'record_type' | 'record_id'>) => `${h.record_type}:${h.record_id}`

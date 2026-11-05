// Investigation workspace types (mirror backend/app/schemas/investigation_workspace.py).
export interface WorkspaceInvestigation {
  id: string
  organization_id: string
  title: string
  description: string | null
  status: string
  priority: string
  assigned_user_id: string | null
  linked_event_ids: string[]
  evidence_refs: string[]
  review_status: string
  resolution_notes: string | null
  purpose: string | null
  scope: string | null
  collaborator_user_ids: string[]
  tags: string[]
  closure_reason: string | null
  closed_at: string | null
  archived_at: string | null
  is_restricted: boolean
  created_at: string
  updated_at: string
}

export interface InvestigationMember { id: string; user_id: string; role: string; created_at: string }
export interface StatusHistoryEntry { id: string; from_status: string | null; to_status: string; reason: string | null; changed_by_user_id: string | null; created_at: string }

export interface RecordSummary {
  record_type: string
  record_id: string
  title: string | null
  summary: string | null
  source_id: string | null
  review_status: string | null
  data_quality: string
  primary_time: string | null
  primary_time_kind: string | null
  origin?: string
  tags?: string[]
  evidence_status?: string
  superseded?: boolean
}
export interface InvestigationLink {
  id: string
  record_type: string
  record_id: string
  note: string | null
  created_at: string
  linked_by_user_id: string | null
  summary: RecordSummary | null
  resolvable: boolean
}

export interface EvidenceDetail {
  id: string
  evidence_type: string
  title: string
  summary: string | null
  event_id: string | null
  observation_id: string | null
  raw_record_id: string | null
  media_asset_id: string | null
  detection_result_id: string | null
  source_id: string | null
  external_reference_uri: string | null
  content: string | null
  integrity_hash: string | null
  integrity_hash_algorithm: string | null
  hash_recorded_at: string | null
  access_classification: string
  review_status: string
  captured_at: string | null
  processing_version: string | null
  supersedes_evidence_id: string | null
  superseded_by_evidence_id: string | null
  created_by_user_id: string | null
  created_at: string
}
export interface RegisterEvidenceResult { evidence: EvidenceDetail; reused_existing: boolean; link_id: string }
export interface RegisterEvidencePayload {
  evidence_type: string
  title: string
  summary?: string
  record_id?: string
  event_id?: string
  observation_id?: string
  content?: string
  external_reference_uri?: string
  claimed_hash?: string
  access_classification?: string
}

export interface ProvenanceNode {
  role: string
  record_type: string
  record_id: string | null
  label: string
  available: boolean
  [extra: string]: unknown
}
export interface Provenance {
  evidence_id: string
  evidence_type: string
  source_reference: string | null
  times: { registered_at: string | null; captured_at: string | null; hash_recorded_at: string | null }
  processing_version: string | null
  integrity_hash: string | null
  integrity_hash_algorithm: string | null
  access_classification: string
  review_status: string
  chain: ProvenanceNode[]
  limitations: string[]
}
export interface IntegrityCheck {
  id: string
  evidence_id: string
  result: 'match' | 'mismatch' | 'original_unavailable' | 'no_recorded_hash' | 'not_file_backed'
  algorithm: string | null
  recorded_hash: string | null
  computed_hash: string | null
  detail: string | null
  checked_by_user_id: string | null
  created_at: string
  disclaimer?: string | null
}

export interface TimelineEntry {
  entry_id: string
  record_type: string
  record_id: string
  time_kind: string
  timestamp: string | null
  time_known: boolean
  assumed_utc: boolean
  original_timezone: string | null
  missing_time_note: string | null
  title: string
  source_id: string | null
  details: Record<string, unknown>
}
export interface TimelinePage {
  items: TimelineEntry[]
  total: number
  page: number
  page_size: number
  truncated: boolean
  unknown_time_entries: number
  notice: string
  timestamp_semantics: string
}
export interface TimelineQuery {
  start?: string
  end?: string
  record_type?: string[]
  time_kind?: string[]
  page?: number
  page_size?: number
}

export interface InvestigationNote {
  id: string
  investigation_id: string
  evidence_id: string | null
  parent_note_id: string | null
  note_kind: 'observed_fact' | 'analyst_interpretation' | 'hypothesis' | 'review_question'
  body: string
  tags: string[]
  category: string | null
  author_user_id: string | null
  assignee_user_id: string | null
  resolution_status: string | null
  resolved_by_user_id: string | null
  resolved_at: string | null
  version: number
  created_at: string
  updated_at: string
}
export interface NoteRevision { version: number; note_kind: string; body: string; tags: string[]; changed_by_user_id: string | null; change_summary: string | null; created_at: string }
export interface NoteKindInfo { kind: string; description: string }

export interface SearchPage { items: RecordSummary[]; total: number; page: number; page_size: number; note: string }
export interface SearchQuery { q?: string; record_type?: string[]; data_quality?: string; evidence_status?: string; tag?: string; start?: string; end?: string; page?: number }
export interface RelationshipView {
  relationship_id: string
  relationship_type: string
  source: { record_type: string; record_id: string }
  target: { record_type: string; record_id: string }
  origin: string
  origin_label: string
  review_status: string
  is_confirmed: boolean
  explanation: string
}
export interface RelationshipsResult { items: RelationshipView[]; total: number; notice: string }

export interface WorkspaceDashboardSummary {
  by_status: Record<string, number>
  open_by_priority: Record<string, number>
  total: number
  open_review_questions: number
  review_questions_assigned_to_me: number
  recent_activity: { id: string; title: string; status: string; priority: string; updated_at: string }[]
}
export interface InvestigationAuditEntry { id: string; action: string; actor_user_id: string | null; outcome: string; created_at: string; details: Record<string, unknown> }

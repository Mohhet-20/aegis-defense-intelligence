// Phase 14 governance types -- mirror backend/app/schemas/{audit,lifecycle}.py and
// app/core/security_config.py. Nothing here is computed client-side.
export interface RoleInfo { role: string; permissions: string[]; permission_count: number }
export interface RoleMatrix { roles: RoleInfo[]; all_permissions: string[] }

export interface AuditFilters {
  action?: string; action_prefix?: string; outcome?: '' | 'success' | 'failure' | 'denied'
  actor_user_id?: string; target_type?: string; target_id?: string; request_id?: string
  created_from?: string; created_to?: string
}

export interface LifecyclePolicyItem {
  resource_type: string; label: string; classification: string; actions: string[]
  retention_days: number | null; retention_setting: string | null; semantics: string; managed: boolean
}
export interface LifecyclePolicies {
  items: LifecyclePolicyItem[]; audit_retention_days: number | null; audit_note: string; require_separate_approver: boolean
}
export interface LifecycleImpact { action: string; blockers: string[]; affected: Record<string, unknown>; executable: boolean; label?: string }
export interface LifecyclePreview {
  resource_type: string; retention_days: number | null; cutoff: string | null; action?: string
  items: { resource_id: string; created_at: string; label: string; impact: LifecycleImpact }[]
  total_eligible: number; truncated?: boolean; note?: string
}
export type LifecycleStatus = 'pending' | 'approved' | 'rejected' | 'executed' | 'cleanup_pending' | 'failed' | 'cancelled'
export interface LifecycleRequest {
  id: string; resource_type: string; resource_id: string; action: 'archive' | 'delete'; status: LifecycleStatus
  reason: string; requested_by_user_id: string; reviewed_by_user_id: string | null; reviewed_at: string | null
  review_note: string | null; executed_by_user_id: string | null; executed_at: string | null
  impact: LifecycleImpact; result: Record<string, unknown> | null; failure_reason: string | null; created_at: string
}
export interface AuditRetentionReport { retention_days: number | null; total: number; eligible_for_external_archival: number; cutoff?: string; note: string }

export interface SecurityFinding { id: string; severity: 'critical' | 'high' | 'medium' | 'low' | 'info'; title: string; detail: string; recommendation: string }
export interface SecurityConfigReport {
  environment: string; findings: SecurityFinding[]; settings: Record<string, string | number | boolean | null>
  secrets_configured: Record<string, boolean>; not_implemented: string[]
}

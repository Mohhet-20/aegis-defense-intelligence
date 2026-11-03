import { request } from './client'
import type { AuditRecord, Page, User } from '../types/api'
import type {
  AuditFilters, AuditRetentionReport, LifecyclePolicies, LifecyclePreview, LifecycleRequest, RoleMatrix, SecurityConfigReport,
} from '../types/governance'

const json = (body: unknown) => JSON.stringify(body)

/** Phase 14 governance API. Every call hits a real backend route; permissions are enforced server-side. */
export const governanceApi = {
  audit: (filters: AuditFilters, page = 1, pageSize = 25) => {
    const s = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
    Object.entries(filters).forEach(([k, v]) => { if (v) s.set(k, String(v)) })
    return request<Page<AuditRecord>>(`/audit?${s.toString()}`)
  },
  auditActions: () => request<string[]>('/audit/actions'),
  users: () => request<User[]>('/users'),
  updateUser: (id: string, body: { role?: string; is_active?: boolean; display_name?: string }) =>
    request<User>(`/users/${id}`, { method: 'PATCH', body: json(body) }),
  revokeUserSessions: (id: string) => request<void>(`/users/${id}/revoke-sessions`, { method: 'POST' }),
  resetPassword: (id: string, new_password: string) => request<void>(`/users/${id}/reset-password`, { method: 'POST', body: json({ new_password }) }),
  accessHistory: (id: string) => request<AuditRecord[]>(`/users/${id}/access-history`),
  roles: () => request<RoleMatrix>('/security/roles'),
  securityConfig: () => request<SecurityConfigReport>('/security/config'),
  lifecyclePolicies: () => request<LifecyclePolicies>('/lifecycle/policies'),
  lifecyclePreview: (resource_type: string, older_than_days?: number) =>
    request<LifecyclePreview>(`/lifecycle/preview?resource_type=${resource_type}${older_than_days ? `&older_than_days=${older_than_days}` : ''}`),
  auditRetention: () => request<AuditRetentionReport>('/lifecycle/audit-retention'),
  lifecycleRequests: (page = 1, status = '') =>
    request<Page<LifecycleRequest>>(`/lifecycle/requests?page=${page}&page_size=20${status ? `&status=${status}` : ''}`),
  createLifecycleRequest: (body: { resource_type: string; resource_id: string; action: 'archive' | 'delete'; reason: string }) =>
    request<LifecycleRequest>('/lifecycle/requests', { method: 'POST', body: json(body) }),
  approve: (id: string, note?: string) => request<LifecycleRequest>(`/lifecycle/requests/${id}/approve`, { method: 'POST', body: json({ note }) }),
  reject: (id: string, note?: string) => request<LifecycleRequest>(`/lifecycle/requests/${id}/reject`, { method: 'POST', body: json({ note }) }),
  cancel: (id: string) => request<LifecycleRequest>(`/lifecycle/requests/${id}/cancel`, { method: 'POST' }),
  execute: (id: string) => request<LifecycleRequest>(`/lifecycle/requests/${id}/execute`, { method: 'POST' }),
}

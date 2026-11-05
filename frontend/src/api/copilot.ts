import { request } from './client'
import type {
  AskRequest, AskResponse, Capabilities, Citation, ConversationDetail, ConversationSummary, EvalResult,
  IndexRunResult, IndexStatus, SearchParams, SearchResponse,
} from '../types/copilot'

interface ConversationPage {
  items: ConversationSummary[]
  total: number
  page: number
  page_size: number
}

/** Retrieval + copilot API. Every call goes to the real backend. */
export const copilotApi = {
  capabilities: () => request<Capabilities>('/retrieval/capabilities'),
  search: (p: SearchParams) => {
    const s = new URLSearchParams({ q: p.q, page: String(p.page ?? 1), page_size: String(p.pageSize ?? 10) })
    for (const t of p.recordTypes ?? []) s.append('record_type', t)
    if (p.investigationId) s.set('investigation_id', p.investigationId)
    if (p.sourceId) s.set('source_id', p.sourceId)
    if (p.reviewStatus) s.set('review_status', p.reviewStatus)
    if (p.timeFrom) s.set('time_from', new Date(p.timeFrom).toISOString())
    if (p.timeTo) s.set('time_to', new Date(p.timeTo).toISOString())
    if (p.documentVersion) s.set('document_version', String(p.documentVersion))
    return request<SearchResponse>(`/retrieval/search?${s.toString()}`)
  },
  ask: (body: AskRequest) => request<AskResponse>('/copilot/ask', { method: 'POST', body: JSON.stringify(body) }),
  verifyCitations: (citations: Pick<Citation, 'record_type' | 'record_id' | 'quote' | 'document_version'>[]) =>
    request<{ citations: Citation[] }>('/copilot/citations/verify', { method: 'POST', body: JSON.stringify({ citations }) }),
  conversations: (page = 1) => request<ConversationPage>(`/copilot/conversations?page=${page}&page_size=20`),
  conversation: (id: string) => request<ConversationDetail>(`/copilot/conversations/${id}`),
  deleteConversation: (id: string) => request<void>(`/copilot/conversations/${id}`, { method: 'DELETE' }),
  indexStatus: () => request<IndexStatus>('/retrieval/index/status'),
  runIndex: (record_types?: string[], investigation_id?: string) =>
    request<IndexRunResult>('/retrieval/index', { method: 'POST', body: JSON.stringify({ record_types, investigation_id }) }),
  purge: () => request<{ tombstones_removed: number; conversations_removed: number }>('/retrieval/index/purge', { method: 'POST' }),
  evaluate: () => request<EvalResult>('/retrieval/evaluate', { method: 'POST' }),
}

// Thin typed fetch wrapper around the real /api/v1 backend. Every
// call here hits a real route in backend/app/api/routes/*.py -- there
// is no fabricated or mocked response anywhere in this file (Rule 3).
import type {
  EvidenceDetail,
  IntegrityCheck,
  InvestigationAuditEntry,
  InvestigationLink,
  InvestigationMember,
  InvestigationNote,
  NoteKindInfo,
  NoteRevision,
  Provenance,
  RegisterEvidencePayload,
  RegisterEvidenceResult,
  RelationshipsResult,
  SearchPage,
  SearchQuery,
  StatusHistoryEntry,
  TimelinePage,
  TimelineQuery,
  WorkspaceDashboardSummary,
  WorkspaceInvestigation,
} from '../types/workspace'
import type {
  AegisEvent,
  AssessmentReviewRecord,
  AssessmentScoreSnapshot,
  ClassificationEvaluation,
  ClassificationEvaluationRequest,
  EvaluationOverviewRow,
  Explanation,
  ModelOutput,
  ModelOutputPage,
  ModelOutputType,
  ReviewSummary,
  ScoringRules,
  ReviewDecision,
  AnomalyRunResult,
  Assessment,
  AssessmentEvidenceLink,
  AssessmentRevision,
  Asset,
  AuditRecord,
  ConfigValidationResult,
  ConnectivityCheckResult,
  Conflict,
  CrossSourceComparison,
  CurrentUser,
  CVModel,
  EvaluationDataset,
  DashboardSummary,
  DataQualitySummary,
  DataSource,
  DescriptiveStatistics,
  DetectConflictsResult,
  DetectionResult,
  Device,
  DeviceAdministrativeStatus,
  DeviceCapability,
  DeviceConfigBaseline,
  DeviceConfigState,
  DeviceConnectivityState,
  DeviceHealthReport,
  DeviceRegistrationResult,
  Evidence,
  FleetCapabilitySummaryEntry,
  FleetOverview,
  FleetSite,
  FleetSiteSummary,
  InfraAlertSeverity,
  InfraAlertStatus,
  InfrastructureAlert,
  LifecyclePreview,
  EvidenceRelationship,
  EventCorrelation,
  FusionJob,
  GeoRecordType,
  GeospatialOverview,
  GeospatialQueryResult,
  GraphResponse,
  InferenceJob,
  IngestionJob,
  Investigation,
  JobsSummary,
  LocationQualityRecord,
  LocationQualitySummary,
  MediaAsset,
  ModelEvaluationRun,
  Observation,
  ObservationAnomaly,
  Page,
  RawRecord,
  ReadinessResponse,
  RecomputeCorrelationsResult,
  ReviewHistoryEntry,
  RiskAssessment,
  Sensor,
  SensorHealth,
  SensorRawRecord,
  SpatialGridResult,
  SpatialRelationshipCandidate,
  SpatialRelationshipRunResult,
  SyncConflict,
  SyncConflictResolutionStrategy,
  SyncRecord,
  SyncRecordStatus,
  SyncQueueSummary,
  TemporalGapsResult,
  TimeBucketCountsResult,
  TimeSeriesResponse,
  Track,
  TrackAnnotation,
  TrackerConfigDefaults,
  TrackingEvaluationRun,
  TrackingJob,
  TrackingJobSummary,
  TrackMotion,
  TrackObservation,
  User,
} from '../types/api'

const API_BASE = '/api/v1'
export const SESSION_EXPIRED_EVENT = 'aegis:session-expired'

// Browser session model ("cookie mode"): the short-lived access token is kept in
// memory only, and the refresh token lives in an HttpOnly, SameSite=Strict cookie the
// backend sets on /api/v1/auth -- page scripts never see it, so nothing long-lived is
// stored in localStorage. A reload restores the session through /auth/refresh.
export const SESSION_MODE_HEADERS = { 'X-Session-Mode': 'cookie' }

let accessToken: string | null = null

// Tokens stored by earlier versions of this app; removed on load, never read.
try {
  localStorage.removeItem('aegis_access_token')
  localStorage.removeItem('aegis_refresh_token')
} catch {
  // storage unavailable (private mode / blocked) -- nothing to clean up
}

export function setAccessToken(access: string) {
  accessToken = access
}

export function clearTokens() {
  accessToken = null
}

export function getAccessToken() {
  return accessToken
}

export class ApiError extends Error {
  status: number
  requestId: string | null
  constructor(status: number, message: string, requestId: string | null) {
    super(message)
    this.status = status
    this.requestId = requestId
  }
}

export async function request<T>(
  path: string,
  options: RequestInit = {},
  { retry = true }: { retry?: boolean } = {},
): Promise<T> {
  const headers = new Headers(options.headers)
  if (accessToken) {
    headers.set('Authorization', `Bearer ${accessToken}`)
  }
  if (options.body && !(options.body instanceof FormData) && !headers.has('Content-Type')) {
    headers.set('Content-Type', 'application/json')
  }

  const response = await fetch(`${API_BASE}${path}`, { ...options, headers })

  if (response.status === 401 && retry && !path.startsWith('/auth/')) {
    const refreshed = await tryRefresh()
    if (refreshed) {
      return request<T>(path, options, { retry: false })
    }
  }

  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    let requestId: string | null = null
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      else if (Array.isArray(body.detail)) {
        detail = body.detail.map((d: { loc?: string[]; msg?: string }) => `${d.loc?.join('.')}: ${d.msg}`).join('; ')
      }
      requestId = body.request_id ?? null
    } catch {
      // response had no JSON body -- keep the generic message
    }
    throw new ApiError(response.status, detail, requestId)
  }

  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

/** Authenticated text download (exports). Returns the body and the server-chosen filename. */
export async function requestText(path: string, retry = true): Promise<{ text: string; filename: string }> {
  const headers = new Headers()
  if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
  const response = await fetch(`${API_BASE}${path}`, { headers })
  if (response.status === 401 && retry && (await tryRefresh())) return requestText(path, false)
  if (!response.ok) {
    let detail = `Request failed with status ${response.status}`
    let requestId: string | null = null
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
      requestId = body.request_id ?? null
    } catch {
      // keep generic message
    }
    throw new ApiError(response.status, detail, requestId)
  }
  const m = /filename="([^"]+)"/.exec(response.headers.get('content-disposition') ?? '')
  return { text: await response.text(), filename: m ? m[1] : 'scenario-export.txt' }
}

let refreshInFlight: Promise<boolean> | null = null

/** Get a new access token using the HttpOnly refresh cookie. Concurrent callers share
 *  one request. On failure the session is over: memory is cleared and the auth context
 *  is told, so the app returns to the login page instead of failing page by page. */
export function tryRefresh(): Promise<boolean> {
  if (!refreshInFlight) {
    refreshInFlight = (async () => {
      try {
        const response = await fetch(`${API_BASE}/auth/refresh`, { method: 'POST', headers: SESSION_MODE_HEADERS, credentials: 'same-origin' })
        if (!response.ok) {
          // Release the unread body; otherwise the request stays open in the browser.
          await response.body?.cancel().catch(() => undefined)
          // Only "the session is invalid" ends it. A rate limit or a server error is
          // transient and must not sign the user out.
          if (response.status === 401 || response.status === 403) {
            const hadSession = accessToken !== null
            clearTokens()
            if (hadSession) window.dispatchEvent(new Event(SESSION_EXPIRED_EVENT))
          }
          return false
        }
        const body = await response.json()
        setAccessToken(body.access_token)
        return true
      } catch {
        return false
      } finally {
        refreshInFlight = null
      }
    })()
  }
  return refreshInFlight
}

export interface DemoInfo {
  enabled: boolean
  password?: string
  accounts?: { username: string; role: string }[]
  reset_hours?: number | null
}

export const api = {
  auth: {
    login: (username_or_email: string, password: string) =>
      request<{ access_token: string; refresh_token: string | null; token_type: string }>('/auth/login', {
        method: 'POST',
        headers: SESSION_MODE_HEADERS,
        body: JSON.stringify({ username_or_email, password }),
      }),
    /** Clears the refresh cookie on the server. */
    logout: () => fetch(`${API_BASE}/auth/logout`, { method: 'POST', credentials: 'same-origin' }).then(() => undefined),
    me: () => request<CurrentUser>('/auth/me'),
    /** Public: whether this deployment is a public demo, and which shared accounts it offers. */
    demo: () => request<DemoInfo>('/demo'),
  },
  health: {
    ready: () => request<ReadinessResponse>('/health/ready'),
    live: () => request<{ status: string }>('/health/live'),
  },
  dashboard: {
    summary: () => request<DashboardSummary>('/dashboard/summary'),
  },
  sources: {
    list: (page = 1, pageSize = 50) => request<Page<DataSource>>(`/sources?page=${page}&page_size=${pageSize}`),
    create: (payload: {
      name: string
      source_type: string
      description?: string
      owner_team?: string
      connection_mode?: string
      config_metadata?: Record<string, unknown>
    }) => request<DataSource>('/sources', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<{ status: string; description: string; owner_team: string; connection_mode: string; config_metadata: Record<string, unknown> }>) =>
      request<DataSource>(`/sources/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    enable: (id: string) => request<DataSource>(`/sources/${id}/enable`, { method: 'POST' }),
    disable: (id: string) => request<DataSource>(`/sources/${id}/disable`, { method: 'POST' }),
    setReliability: (id: string, weight: number, reason: string) =>
      request<DataSource>(`/sources/${id}/reliability`, { method: 'PUT', body: JSON.stringify({ weight, reason }) }),
    validateConfig: (id: string) => request<ConfigValidationResult>(`/sources/${id}/validate-config`, { method: 'POST' }),
    checkConnectivity: (id: string) => request<ConnectivityCheckResult>(`/sources/${id}/check-connectivity`, { method: 'POST' }),
    run: (id: string) => request<IngestionJob>(`/sources/${id}/run`, { method: 'POST' }),
  },
  assets: {
    list: (page = 1, pageSize = 50) => request<Page<Asset>>(`/assets?page=${page}&page_size=${pageSize}`),
    create: (payload: Record<string, unknown>) =>
      request<Asset>('/assets', { method: 'POST', body: JSON.stringify(payload) }),
  },
  sensors: {
    list: (
      params: { page?: number; page_size?: number; category?: string; lifecycle_status?: string; sensor_type?: string; measurement_type?: string; search?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 50))
      if (params.category) search.set('category', params.category)
      if (params.lifecycle_status) search.set('lifecycle_status', params.lifecycle_status)
      if (params.sensor_type) search.set('sensor_type', params.sensor_type)
      if (params.measurement_type) search.set('measurement_type', params.measurement_type)
      if (params.search) search.set('search', params.search)
      return request<Page<Sensor>>(`/sensors?${search.toString()}`)
    },
    get: (id: string) => request<Sensor>(`/sensors/${id}`),
    create: (payload: Record<string, unknown>) =>
      request<Sensor>('/sensors', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Record<string, unknown>) =>
      request<Sensor>(`/sensors/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    statusHistory: (id: string) => request<AuditRecord[]>(`/sensors/${id}/status-history`),
    transitionLifecycle: (id: string, new_status: string, note?: string) =>
      request<Sensor>(`/sensors/${id}/lifecycle`, { method: 'POST', body: JSON.stringify({ new_status, note }) }),
    retire: (id: string) => request<Sensor>(`/sensors/${id}/retire`, { method: 'POST' }),
  },
  events: {
    list: (params: { page?: number; page_size?: number; event_type?: string; priority?: string; source_id?: string; data_origin?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.event_type) search.set('event_type', params.event_type)
      if (params.priority) search.set('priority', params.priority)
      if (params.source_id) search.set('source_id', params.source_id)
      if (params.data_origin) search.set('data_origin', params.data_origin)
      return request<Page<AegisEvent>>(`/events?${search.toString()}`)
    },
    get: (id: string) => request<AegisEvent>(`/events/${id}`),
    rawRecord: (id: string) => request<RawRecord>(`/events/${id}/raw-record`),
    correlations: (id: string) => request<EventCorrelation[]>(`/events/${id}/correlations`),
    // A bearer-token-protected download -- a plain <a href> can't carry
    // the Authorization header, so this fetches the bytes itself and
    // hands the browser a local blob URL to save.
    exportDownload: async (params: { event_type?: string; source_id?: string; priority?: string; data_origin?: string; format?: 'csv' | 'json' } = {}) => {
      const search = new URLSearchParams()
      search.set('format', params.format ?? 'csv')
      if (params.event_type) search.set('event_type', params.event_type)
      if (params.source_id) search.set('source_id', params.source_id)
      if (params.priority) search.set('priority', params.priority)
      if (params.data_origin) search.set('data_origin', params.data_origin)

      const headers = new Headers()
      if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
      const response = await fetch(`${API_BASE}/events/export?${search.toString()}`, { headers })
      if (!response.ok) {
        let detail = `Export failed with status ${response.status}`
        try {
          const body = await response.json()
          if (typeof body.detail === 'string') detail = body.detail
        } catch {
          // no JSON body -- keep the generic message
        }
        throw new ApiError(response.status, detail, null)
      }
      const blob = await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = params.format === 'json' ? 'events_export.json' : 'events_export.csv'
      document.body.appendChild(link)
      link.click()
      document.body.removeChild(link)
      URL.revokeObjectURL(url)
    },
  },
  observations: {
    list: (
      params: { page?: number; page_size?: number; sensor_id?: string; measurement_type?: string; validation_status?: string; since?: string; until?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.sensor_id) search.set('sensor_id', params.sensor_id)
      if (params.measurement_type) search.set('measurement_type', params.measurement_type)
      if (params.validation_status) search.set('validation_status', params.validation_status)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      return request<Page<Observation>>(`/observations?${search.toString()}`)
    },
    get: (id: string) => request<Observation>(`/observations/${id}`),
  },
  // --- Phase 6: multi-sensor data platform ---------------------------
  sensorIngestion: {
    submitSynthetic: (payload: {
      source_id: string
      sensor_id: string
      measurement_type: string
      unit?: string
      count?: number
      seed?: number
      base_value?: number
      noise_amplitude?: number
      interval_seconds?: number
      start_at?: string
      value_overrides?: Record<string, number>
      skip_indices?: number[]
    }) => request<IngestionJob>('/sensor-ingestion/synthetic-batches', { method: 'POST', body: JSON.stringify(payload) }),
    submitFile: (sourceId: string, format: 'json' | 'csv', file: File) => {
      const form = new FormData()
      form.set('source_id', sourceId)
      form.set('format', format)
      form.set('file', file)
      return request<IngestionJob>('/sensor-ingestion/batches', { method: 'POST', body: form })
    },
    list: (params: { page?: number; page_size?: number; source_id?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.source_id) search.set('source_id', params.source_id)
      return request<Page<IngestionJob>>(`/sensor-ingestion/batches?${search.toString()}`)
    },
    get: (id: string) => request<IngestionJob>(`/sensor-ingestion/batches/${id}`),
    records: (id: string, params: { page?: number; page_size?: number; validation_status?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.validation_status) search.set('validation_status', params.validation_status)
      return request<Page<SensorRawRecord>>(`/sensor-ingestion/batches/${id}/records?${search.toString()}`)
    },
    retry: (id: string) => request<IngestionJob>(`/sensor-ingestion/batches/${id}/retry`, { method: 'POST' }),
  },
  sensorAnalytics: {
    timeseries: (sensorId: string, params: { measurement_type: string; since?: string; until?: string; max_points?: number }) => {
      const search = new URLSearchParams()
      search.set('measurement_type', params.measurement_type)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      if (params.max_points) search.set('max_points', String(params.max_points))
      return request<TimeSeriesResponse>(`/sensor-analytics/sensors/${sensorId}/timeseries?${search.toString()}`)
    },
    statistics: (sensorId: string, params: { measurement_type: string; since?: string; until?: string }) => {
      const search = new URLSearchParams()
      search.set('measurement_type', params.measurement_type)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      return request<DescriptiveStatistics>(`/sensor-analytics/sensors/${sensorId}/statistics?${search.toString()}`)
    },
    health: (sensorId: string) => request<SensorHealth>(`/sensor-analytics/sensors/${sensorId}/health`),
    recomputeHealth: (sensorId: string) => request<SensorHealth>(`/sensor-analytics/sensors/${sensorId}/health/recompute`, { method: 'POST' }),
    runAnomalyChecks: (sensor_id: string, measurement_type: string) =>
      request<AnomalyRunResult>('/sensor-analytics/anomalies/run', { method: 'POST', body: JSON.stringify({ sensor_id, measurement_type }) }),
    listAnomalies: (
      params: { page?: number; page_size?: number; sensor_id?: string; measurement_type?: string; review_status?: string; category?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.sensor_id) search.set('sensor_id', params.sensor_id)
      if (params.measurement_type) search.set('measurement_type', params.measurement_type)
      if (params.review_status) search.set('review_status', params.review_status)
      if (params.category) search.set('category', params.category)
      return request<Page<ObservationAnomaly>>(`/sensor-analytics/anomalies?${search.toString()}`)
    },
    getAnomaly: (id: string) => request<ObservationAnomaly>(`/sensor-analytics/anomalies/${id}`),
    reviewAnomaly: (id: string, review_status: string, review_note?: string) =>
      request<ObservationAnomaly>(`/sensor-analytics/anomalies/${id}/review`, { method: 'POST', body: JSON.stringify({ review_status, review_note }) }),
  },
  crossSourceComparison: {
    compare: (observation_a_id: string, observation_b_id: string, tolerance?: number) =>
      request<CrossSourceComparison>('/cross-source-comparison/compare', { method: 'POST', body: JSON.stringify({ observation_a_id, observation_b_id, tolerance }) }),
    createLink: (observation_a_id: string, observation_b_id: string, tolerance?: number) =>
      request<EvidenceRelationship>('/cross-source-comparison/links', { method: 'POST', body: JSON.stringify({ observation_a_id, observation_b_id, tolerance }) }),
  },
  investigations: {
    list: (page = 1, pageSize = 20, status?: string) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (status) search.set('status', status)
      return request<Page<Investigation>>(`/investigations?${search.toString()}`)
    },
    get: (id: string) => request<Investigation>(`/investigations/${id}`),
    create: (payload: { title: string; description?: string; priority?: string }) =>
      request<Investigation>('/investigations', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Record<string, unknown>) =>
      request<Investigation>(`/investigations/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  },
  workspace: {
    list: (params: { page?: number; pageSize?: number; status?: string; priority?: string; q?: string; tag?: string; sortBy?: string; sortDir?: string; includeArchived?: boolean }) => {
      const search = new URLSearchParams({ page: String(params.page ?? 1), page_size: String(params.pageSize ?? 20) })
      if (params.status) search.set('status', params.status)
      if (params.priority) search.set('priority', params.priority)
      if (params.q) search.set('q', params.q)
      if (params.tag) search.set('tag', params.tag)
      if (params.sortBy) search.set('sort_by', params.sortBy)
      if (params.sortDir) search.set('sort_dir', params.sortDir)
      if (params.includeArchived) search.set('include_archived', 'true')
      return request<Page<WorkspaceInvestigation>>(`/investigations?${search.toString()}`)
    },
    get: (id: string) => request<WorkspaceInvestigation>(`/investigations/${id}`),
    create: (payload: { title: string; description?: string; priority?: string; purpose?: string; tags?: string[]; is_restricted?: boolean; initial_status?: string }) =>
      request<WorkspaceInvestigation>('/investigations', { method: 'POST', body: JSON.stringify(payload) }),
    dashboard: () => request<WorkspaceDashboardSummary>('/investigation-dashboard/summary'),
    transition: (id: string, to_status: string, reason?: string) =>
      request<WorkspaceInvestigation>(`/investigations/${id}/transition`, { method: 'POST', body: JSON.stringify({ to_status, reason }) }),
    statusHistory: (id: string) => request<StatusHistoryEntry[]>(`/investigations/${id}/status-history`),
    members: (id: string) => request<InvestigationMember[]>(`/investigations/${id}/members`),
    addMember: (id: string, user_id: string, role: string) =>
      request<InvestigationMember>(`/investigations/${id}/members`, { method: 'POST', body: JSON.stringify({ user_id, role }) }),
    removeMember: (id: string, userId: string) => request<void>(`/investigations/${id}/members/${userId}`, { method: 'DELETE' }),
    links: (id: string) => request<InvestigationLink[]>(`/investigations/${id}/links`),
    addLink: (id: string, record_type: string, record_id: string, note?: string) =>
      request<InvestigationLink>(`/investigations/${id}/links`, { method: 'POST', body: JSON.stringify({ record_type, record_id, note }) }),
    removeLink: (id: string, linkId: string) => request<void>(`/investigations/${id}/links/${linkId}`, { method: 'DELETE' }),
    evidence: (id: string) => request<EvidenceDetail[]>(`/investigations/${id}/evidence`),
    registerEvidence: (id: string, payload: RegisterEvidencePayload) =>
      request<RegisterEvidenceResult>(`/investigations/${id}/evidence`, { method: 'POST', body: JSON.stringify(payload) }),
    provenance: (evidenceId: string) => request<Provenance>(`/evidence/${evidenceId}/provenance`),
    integrityChecks: (evidenceId: string) => request<IntegrityCheck[]>(`/evidence/${evidenceId}/integrity-checks`),
    verifyIntegrity: (evidenceId: string) => request<IntegrityCheck>(`/evidence/${evidenceId}/verify-integrity`, { method: 'POST' }),
    setEvidenceReview: (evidenceId: string, review_status: string, note?: string) =>
      request<EvidenceDetail>(`/evidence/${evidenceId}/review-status`, { method: 'POST', body: JSON.stringify({ review_status, note }) }),
    timeline: (id: string, q: TimelineQuery) => {
      const search = new URLSearchParams({ page: String(q.page ?? 1), page_size: String(q.page_size ?? 50) })
      if (q.start) search.set('start', q.start)
      if (q.end) search.set('end', q.end)
      q.record_type?.forEach((t) => search.append('record_type', t))
      q.time_kind?.forEach((t) => search.append('time_kind', t))
      return request<TimelinePage>(`/investigations/${id}/timeline?${search.toString()}`)
    },
    search: (id: string, q: SearchQuery) => {
      const search = new URLSearchParams({ page: String(q.page ?? 1) })
      if (q.q) search.set('q', q.q)
      if (q.data_quality) search.set('data_quality', q.data_quality)
      if (q.evidence_status) search.set('evidence_status', q.evidence_status)
      if (q.tag) search.set('tag', q.tag)
      if (q.start) search.set('start', q.start)
      if (q.end) search.set('end', q.end)
      q.record_type?.forEach((t) => search.append('record_type', t))
      return request<SearchPage>(`/investigations/${id}/search?${search.toString()}`)
    },
    relationships: (id: string) => request<RelationshipsResult>(`/investigations/${id}/relationships`),
    notes: (id: string, evidenceId?: string) =>
      request<InvestigationNote[]>(`/investigations/${id}/notes${evidenceId ? `?evidence_id=${encodeURIComponent(evidenceId)}` : ''}`),
    noteKinds: (id: string) => request<NoteKindInfo[]>(`/investigations/${id}/note-kinds`),
    createNote: (id: string, payload: { body: string; note_kind: string; tags?: string[]; evidence_id?: string; parent_note_id?: string; assignee_user_id?: string }) =>
      request<InvestigationNote>(`/investigations/${id}/notes`, { method: 'POST', body: JSON.stringify(payload) }),
    updateNote: (id: string, noteId: string, payload: { expected_version: number; body?: string; resolution_status?: string; change_summary?: string }) =>
      request<InvestigationNote>(`/investigations/${id}/notes/${noteId}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    noteRevisions: (id: string, noteId: string) => request<NoteRevision[]>(`/investigations/${id}/notes/${noteId}/revisions`),
    audit: (id: string) => request<InvestigationAuditEntry[]>(`/investigations/${id}/audit`),
    // Bearer-token-protected download (same blob pattern as the events export).
    exportReport: async (id: string, format: 'json' | 'zip', includeMedia: boolean): Promise<void> => {
      const headers = new Headers()
      if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
      const response = await fetch(`${API_BASE}/investigations/${id}/export?format=${format}&include_media=${includeMedia}`, { method: 'POST', headers })
      if (!response.ok) {
        let detail = `Export failed with status ${response.status}`
        try {
          detail = ((await response.json()) as { detail?: string }).detail ?? detail
        } catch {
          // keep the generic message
        }
        throw new ApiError(response.status, detail, null)
      }
      const blob = format === 'json' ? new Blob([JSON.stringify(await response.json(), null, 2)], { type: 'application/json' }) : await response.blob()
      const url = URL.createObjectURL(blob)
      const link = document.createElement('a')
      link.href = url
      link.download = `investigation-${id}.${format}`
      link.click()
      URL.revokeObjectURL(url)
    },
  },
  riskAssessments: {
    list: (page = 1, pageSize = 20, reviewStatus?: string) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (reviewStatus) search.set('human_review_status', reviewStatus)
      return request<Page<RiskAssessment>>(`/risk-assessments?${search.toString()}`)
    },
    review: (id: string, human_review_status: string, reviewer_notes?: string) =>
      request<RiskAssessment>(`/risk-assessments/${id}/review`, {
        method: 'POST',
        body: JSON.stringify({ human_review_status, reviewer_notes }),
      }),
  },
  ingestion: {
    list: (page = 1, pageSize = 20, sourceId?: string) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (sourceId) search.set('source_id', sourceId)
      return request<Page<IngestionJob>>(`/ingestion/jobs?${search.toString()}`)
    },
    get: (id: string) => request<IngestionJob>(`/ingestion/jobs/${id}`),
    upload: (sourceId: string, file: File) => {
      const form = new FormData()
      form.set('source_id', sourceId)
      form.set('file', file)
      return request<IngestionJob>('/ingestion/jobs', { method: 'POST', body: form })
    },
    rawRecords: (jobId: string, page = 1, pageSize = 20) =>
      request<Page<RawRecord>>(`/ingestion/jobs/${jobId}/raw-records?page=${page}&page_size=${pageSize}`),
    retry: (jobId: string) => request<IngestionJob>(`/ingestion/jobs/${jobId}/retry`, { method: 'POST' }),
  },
  dataQuality: {
    summary: (params: { source_id?: string; since?: string; until?: string } = {}) => {
      const search = new URLSearchParams()
      if (params.source_id) search.set('source_id', params.source_id)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      return request<DataQualitySummary>(`/data-quality/summary?${search.toString()}`)
    },
    jobsSummary: (params: { source_id?: string; since?: string; until?: string } = {}) => {
      const search = new URLSearchParams()
      if (params.source_id) search.set('source_id', params.source_id)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      return request<JobsSummary>(`/data-quality/jobs-summary?${search.toString()}`)
    },
  },
  correlation: {
    list: (page = 1, pageSize = 20) => request<Page<EventCorrelation>>(`/correlation?page=${page}&page_size=${pageSize}`),
    get: (id: string) => request<EventCorrelation>(`/correlation/${id}`),
    recompute: (payload: { time_window_seconds?: number; spatial_threshold_meters?: number } = {}) =>
      request<RecomputeCorrelationsResult>('/correlation/recompute', { method: 'POST', body: JSON.stringify(payload) }),
    review: (id: string, review_status: 'confirmed' | 'rejected') =>
      request<EventCorrelation>(`/correlation/${id}/review`, { method: 'POST', body: JSON.stringify({ review_status }) }),
  },
  audit: {
    list: (page = 1, pageSize = 20) => request<Page<AuditRecord>>(`/audit?page=${page}&page_size=${pageSize}`),
  },
  users: {
    list: () => request<User[]>('/users'),
  },
  evidence: {
    list: (params: { page?: number; page_size?: number; evidence_type?: string; event_id?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.evidence_type) search.set('evidence_type', params.evidence_type)
      if (params.event_id) search.set('event_id', params.event_id)
      return request<Page<Evidence>>(`/evidence?${search.toString()}`)
    },
    get: (id: string) => request<Evidence>(`/evidence/${id}`),
    create: (payload: {
      evidence_type: string
      title: string
      summary?: string
      event_id?: string
      raw_record_id?: string
      observation_id?: string
      content?: string
      external_reference_uri?: string
      integrity_hash?: string
    }) => request<Evidence>('/evidence', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Partial<{ title: string; summary: string; content: string }>) =>
      request<Evidence>(`/evidence/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
  },
  relationships: {
    list: (
      params: { page?: number; page_size?: number; relationship_type?: string; origin?: string; review_status?: string; ref_type?: string; ref_id?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.relationship_type) search.set('relationship_type', params.relationship_type)
      if (params.origin) search.set('origin', params.origin)
      if (params.review_status) search.set('review_status', params.review_status)
      if (params.ref_type) search.set('ref_type', params.ref_type)
      if (params.ref_id) search.set('ref_id', params.ref_id)
      return request<Page<EvidenceRelationship>>(`/relationships?${search.toString()}`)
    },
    get: (id: string) => request<EvidenceRelationship>(`/relationships/${id}`),
    history: (id: string) => request<ReviewHistoryEntry[]>(`/relationships/${id}/history`),
    create: (payload: {
      source_ref_type: string
      source_ref_id: string
      target_ref_type: string
      target_ref_id: string
      relationship_type: string
      explanation: string
      supporting_metadata?: Record<string, unknown>
    }) => request<EvidenceRelationship>('/relationships', { method: 'POST', body: JSON.stringify(payload) }),
    review: (id: string, review_status: 'confirmed' | 'rejected' | 'uncertain', review_note?: string) =>
      request<EvidenceRelationship>(`/relationships/${id}/review`, { method: 'POST', body: JSON.stringify({ review_status, review_note }) }),
    reverse: (id: string, note?: string) =>
      request<EvidenceRelationship>(`/relationships/${id}/reverse`, { method: 'POST', body: JSON.stringify({ note }) }),
  },
  conflicts: {
    list: (params: { page?: number; page_size?: number; review_status?: string; event_id?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.review_status) search.set('review_status', params.review_status)
      if (params.event_id) search.set('event_id', params.event_id)
      return request<Page<Conflict>>(`/conflicts?${search.toString()}`)
    },
    get: (id: string) => request<Conflict>(`/conflicts/${id}`),
    history: (id: string) => request<ReviewHistoryEntry[]>(`/conflicts/${id}/history`),
    detect: (payload: { correlation_batch_id?: string; spatial_conflict_threshold_meters?: number } = {}) =>
      request<DetectConflictsResult>('/conflicts/detect', { method: 'POST', body: JSON.stringify(payload) }),
    resolve: (id: string, review_status: string, resolution_note?: string) =>
      request<Conflict>(`/conflicts/${id}/resolve`, { method: 'POST', body: JSON.stringify({ review_status, resolution_note }) }),
  },
  assessments: {
    list: (params: { page?: number; page_size?: number; status?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.status) search.set('status', params.status)
      return request<Page<Assessment>>(`/assessments?${search.toString()}`)
    },
    get: (id: string) => request<Assessment>(`/assessments/${id}`),
    create: (payload: {
      title: string
      question: string
      scope_description?: string
      scope_start?: string
      scope_end?: string
      summary?: string
      assumptions?: string[]
      information_gaps?: string[]
      confidence_level?: string
      confidence_rationale?: string
    }) => request<Assessment>('/assessments', { method: 'POST', body: JSON.stringify(payload) }),
    update: (id: string, payload: Record<string, unknown>) =>
      request<Assessment>(`/assessments/${id}`, { method: 'PATCH', body: JSON.stringify(payload) }),
    revisions: (id: string) => request<AssessmentRevision[]>(`/assessments/${id}/revisions`),
    linkEvidence: (id: string, payload: { role: string; event_id?: string; evidence_id?: string; note?: string }) =>
      request<AssessmentEvidenceLink>(`/assessments/${id}/evidence`, { method: 'POST', body: JSON.stringify(payload) }),
    listEvidenceLinks: (id: string) => request<AssessmentEvidenceLink[]>(`/assessments/${id}/evidence`),
  },
  fusion: {
    run: (payload: { time_window_seconds?: number; spatial_threshold_meters?: number; spatial_conflict_threshold_meters?: number } = {}) =>
      request<FusionJob>('/fusion/run', { method: 'POST', body: JSON.stringify(payload) }),
    jobs: (page = 1, pageSize = 10) => request<Page<FusionJob>>(`/fusion/jobs?page=${page}&page_size=${pageSize}`),
    job: (id: string) => request<FusionJob>(`/fusion/jobs/${id}`),
    graph: (params: {
      seed_type: string
      seed_id: string
      max_depth?: number
      max_nodes?: number
      relationship_type?: string[]
      review_status?: string
      source_id?: string
      since?: string
      until?: string
    }) => {
      const search = new URLSearchParams()
      search.set('seed_type', params.seed_type)
      search.set('seed_id', params.seed_id)
      if (params.max_depth) search.set('max_depth', String(params.max_depth))
      if (params.max_nodes) search.set('max_nodes', String(params.max_nodes))
      if (params.relationship_type) params.relationship_type.forEach((t) => search.append('relationship_type', t))
      if (params.review_status) search.set('review_status', params.review_status)
      if (params.source_id) search.set('source_id', params.source_id)
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      return request<GraphResponse>(`/fusion/graph?${search.toString()}`)
    },
  },
  media: {
    list: (page = 1, pageSize = 20, mediaType?: string) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (mediaType) search.set('media_type', mediaType)
      return request<Page<MediaAsset>>(`/media?${search.toString()}`)
    },
    get: (id: string) => request<MediaAsset>(`/media/${id}`),
    upload: (file: File) => {
      const form = new FormData()
      form.set('file', file)
      return request<MediaAsset>('/media', { method: 'POST', body: form })
    },
    // Bearer-token-protected, like events.exportDownload -- returns an
    // in-memory blob URL for an <img>/<video> src, never a raw <a href>
    // that can't carry the Authorization header.
    contentUrl: async (id: string): Promise<string> => {
      const headers = new Headers()
      if (accessToken) headers.set('Authorization', `Bearer ${accessToken}`)
      const response = await fetch(`${API_BASE}/media/${id}/content`, { headers })
      if (!response.ok) throw new ApiError(response.status, `Failed to load media content (status ${response.status})`, null)
      const blob = await response.blob()
      return URL.createObjectURL(blob)
    },
  },
  cvModels: {
    list: (page = 1, pageSize = 50) => request<Page<CVModel>>(`/cv/models?page=${page}&page_size=${pageSize}`),
    get: (id: string) => request<CVModel>(`/cv/models/${id}`),
    register: (payload: { name: string; version: string; adapter_key: string; supported_media_types: string[]; status?: string }) =>
      request<CVModel>('/cv/models', { method: 'POST', body: JSON.stringify(payload) }),
  },
  inference: {
    submit: (payload: {
      media_asset_id: string
      model_record_id: string
      job_type: 'image_detection' | 'video_frame_analysis'
      confidence_threshold?: number
      nms_iou_threshold?: number
      frame_sample_interval_seconds?: number
      max_frames?: number
      idempotency_key?: string
    }) => request<InferenceJob>('/inference/jobs', { method: 'POST', body: JSON.stringify(payload) }),
    list: (params: { page?: number; page_size?: number; media_asset_id?: string; status?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.media_asset_id) search.set('media_asset_id', params.media_asset_id)
      if (params.status) search.set('status', params.status)
      return request<Page<InferenceJob>>(`/inference/jobs?${search.toString()}`)
    },
    get: (id: string) => request<InferenceJob>(`/inference/jobs/${id}`),
    detections: (id: string, page = 1, pageSize = 100) =>
      request<Page<DetectionResult>>(`/inference/jobs/${id}/detections?page=${page}&page_size=${pageSize}`),
    retry: (id: string) => request<InferenceJob>(`/inference/jobs/${id}/retry`, { method: 'POST' }),
  },
  detections: {
    review: (id: string, review_status: 'confirmed' | 'rejected', review_note?: string) =>
      request<DetectionResult>(`/detections/${id}/review`, { method: 'POST', body: JSON.stringify({ review_status, review_note }) }),
    promoteToEvidence: (id: string, title: string, summary?: string) =>
      request<Evidence>(`/detections/${id}/promote-to-evidence`, { method: 'POST', body: JSON.stringify({ title, summary }) }),
  },
  evaluation: {
    run: (payload: { model_record_id: string; sample_count?: number; iou_match_threshold?: number; dataset?: EvaluationDataset }) =>
      request<ModelEvaluationRun>('/evaluation/runs', { method: 'POST', body: JSON.stringify(payload) }),
    list: (modelRecordId?: string, page = 1, pageSize = 20) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (modelRecordId) search.set('model_record_id', modelRecordId)
      return request<Page<ModelEvaluationRun>>(`/evaluation/runs?${search.toString()}`)
    },
    get: (id: string) => request<ModelEvaluationRun>(`/evaluation/runs/${id}`),
  },
  // --- Phase 5: object tracking --------------------------------------
  tracking: {
    config: () => request<TrackerConfigDefaults>('/tracking/config'),
    submit: (payload: {
      inference_job_id: string
      tracker_key?: string
      min_iou_threshold?: number
      max_missed_frames?: number
      min_hits_to_confirm?: number
      require_class_match?: boolean
      idempotency_key?: string
    }) => request<TrackingJob>('/tracking/jobs', { method: 'POST', body: JSON.stringify(payload) }),
    list: (params: { page?: number; page_size?: number; media_asset_id?: string; status?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.media_asset_id) search.set('media_asset_id', params.media_asset_id)
      if (params.status) search.set('status', params.status)
      return request<Page<TrackingJob>>(`/tracking/jobs?${search.toString()}`)
    },
    get: (id: string) => request<TrackingJob>(`/tracking/jobs/${id}`),
    retry: (id: string) => request<TrackingJob>(`/tracking/jobs/${id}/retry`, { method: 'POST' }),
    summary: (id: string) => request<TrackingJobSummary>(`/tracking/jobs/${id}/summary`),
    tracks: (id: string, params: { page?: number; page_size?: number; state?: string } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 50))
      if (params.state) search.set('state', params.state)
      return request<Page<Track>>(`/tracking/jobs/${id}/tracks?${search.toString()}`)
    },
    frameTracks: (id: string, frameIndex: number) => request<TrackObservation[]>(`/tracking/jobs/${id}/frames/${frameIndex}/tracks`),
  },
  tracks: {
    get: (id: string) => request<Track>(`/tracking/tracks/${id}`),
    observations: (id: string, params: { page?: number; page_size?: number; frame_min?: number; frame_max?: number } = {}) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 100))
      if (params.frame_min !== undefined) search.set('frame_min', String(params.frame_min))
      if (params.frame_max !== undefined) search.set('frame_max', String(params.frame_max))
      return request<Page<TrackObservation>>(`/tracking/tracks/${id}/observations?${search.toString()}`)
    },
    motion: (id: string) => request<TrackMotion>(`/tracking/tracks/${id}/motion`),
    annotations: (id: string) => request<TrackAnnotation[]>(`/tracking/tracks/${id}/annotations`),
    annotate: (id: string, payload: { annotation_type: string; note?: string; supersedes_annotation_id?: string }) =>
      request<TrackAnnotation>(`/tracking/tracks/${id}/annotations`, { method: 'POST', body: JSON.stringify(payload) }),
  },
  trackingEvaluation: {
    run: (payload: { tracker_key?: string; min_iou_threshold?: number; max_missed_frames?: number; min_hits_to_confirm?: number; require_class_match?: boolean } = {}) =>
      request<TrackingEvaluationRun>('/tracking/evaluation/runs', { method: 'POST', body: JSON.stringify(payload) }),
    list: (trackerKey?: string, page = 1, pageSize = 20) => {
      const search = new URLSearchParams({ page: String(page), page_size: String(pageSize) })
      if (trackerKey) search.set('tracker_key', trackerKey)
      return request<Page<TrackingEvaluationRun>>(`/tracking/evaluation/runs?${search.toString()}`)
    },
    get: (id: string) => request<TrackingEvaluationRun>(`/tracking/evaluation/runs/${id}`),
  },
  // --- Phase 7: geospatial intelligence -------------------------------
  geospatial: {
    overview: (recordTypes?: GeoRecordType[]) => {
      const search = new URLSearchParams()
      recordTypes?.forEach((t) => search.append('record_types', t))
      return request<GeospatialOverview>(`/geospatial/overview?${search.toString()}`)
    },
    viewport: (params: {
      min_lat: number; max_lat: number; min_lon: number; max_lon: number
      record_types?: GeoRecordType[]; since?: string; until?: string; timestamp_type?: string; max_results?: number
    }) => {
      const search = new URLSearchParams()
      search.set('min_lat', String(params.min_lat))
      search.set('max_lat', String(params.max_lat))
      search.set('min_lon', String(params.min_lon))
      search.set('max_lon', String(params.max_lon))
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      if (params.timestamp_type) search.set('timestamp_type', params.timestamp_type)
      if (params.max_results) search.set('max_results', String(params.max_results))
      return request<GeospatialQueryResult>(`/geospatial/viewport?${search.toString()}`)
    },
    radius: (params: {
      center_latitude: number; center_longitude: number; radius_km: number
      record_types?: GeoRecordType[]; since?: string; until?: string; timestamp_type?: string; max_results?: number
    }) => {
      const search = new URLSearchParams()
      search.set('center_latitude', String(params.center_latitude))
      search.set('center_longitude', String(params.center_longitude))
      search.set('radius_km', String(params.radius_km))
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      if (params.timestamp_type) search.set('timestamp_type', params.timestamp_type)
      if (params.max_results) search.set('max_results', String(params.max_results))
      return request<GeospatialQueryResult>(`/geospatial/radius?${search.toString()}`)
    },
    qualitySummary: (recordTypes?: GeoRecordType[]) => {
      const search = new URLSearchParams()
      recordTypes?.forEach((t) => search.append('record_types', t))
      return request<LocationQualitySummary>(`/geospatial/quality/summary?${search.toString()}`)
    },
    qualityIssues: (params: { record_types?: GeoRecordType[]; only_issues?: boolean; limit?: number } = {}) => {
      const search = new URLSearchParams()
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.only_issues !== undefined) search.set('only_issues', String(params.only_issues))
      if (params.limit) search.set('limit', String(params.limit))
      return request<LocationQualityRecord[]>(`/geospatial/quality/issues?${search.toString()}`)
    },
    generateRelationships: (payload: { since?: string; until?: string; distance_threshold_m?: number; time_window_seconds?: number } = {}) =>
      request<SpatialRelationshipRunResult>('/geospatial/relationships/generate', { method: 'POST', body: JSON.stringify(payload) }),
    listRelationships: (params: { review_status?: string; limit?: number } = {}) => {
      const search = new URLSearchParams()
      if (params.review_status) search.set('review_status', params.review_status)
      if (params.limit) search.set('limit', String(params.limit))
      return request<SpatialRelationshipCandidate[]>(`/geospatial/relationships?${search.toString()}`)
    },
    timeline: (params: {
      since: string; until: string; record_types?: GeoRecordType[]; timestamp_type?: string; max_results?: number; ascending?: boolean
    }) => {
      const search = new URLSearchParams()
      search.set('since', params.since)
      search.set('until', params.until)
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.timestamp_type) search.set('timestamp_type', params.timestamp_type)
      if (params.max_results) search.set('max_results', String(params.max_results))
      if (params.ascending !== undefined) search.set('ascending', String(params.ascending))
      return request<GeospatialQueryResult>(`/geospatial/timeline?${search.toString()}`)
    },
    timeBuckets: (params: { since: string; until: string; bucket_seconds: number; record_types?: GeoRecordType[]; timestamp_type?: string }) => {
      const search = new URLSearchParams()
      search.set('since', params.since)
      search.set('until', params.until)
      search.set('bucket_seconds', String(params.bucket_seconds))
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.timestamp_type) search.set('timestamp_type', params.timestamp_type)
      return request<TimeBucketCountsResult>(`/geospatial/timeline/buckets?${search.toString()}`)
    },
    temporalGaps: (params: { record_type: GeoRecordType; since: string; until: string; min_gap_seconds: number; timestamp_type?: string }) => {
      const search = new URLSearchParams()
      search.set('record_type', params.record_type)
      search.set('since', params.since)
      search.set('until', params.until)
      search.set('min_gap_seconds', String(params.min_gap_seconds))
      if (params.timestamp_type) search.set('timestamp_type', params.timestamp_type)
      return request<TemporalGapsResult>(`/geospatial/analytics/temporal-gaps?${search.toString()}`)
    },
    spatialGrid: (params: { record_types?: GeoRecordType[]; since?: string; until?: string; grid_resolution_degrees?: number } = {}) => {
      const search = new URLSearchParams()
      params.record_types?.forEach((t) => search.append('record_types', t))
      if (params.since) search.set('since', params.since)
      if (params.until) search.set('until', params.until)
      if (params.grid_resolution_degrees) search.set('grid_resolution_degrees', String(params.grid_resolution_degrees))
      return request<SpatialGridResult>(`/geospatial/analytics/spatial-grid?${search.toString()}`)
    },
    // Export endpoints return the raw file (Content-Disposition:
    // attachment), never a JSON envelope -- these two fetch it as a
    // Blob and hand back the server-suggested filename so the caller
    // can trigger a real browser download, same bearer-token-protected
    // blob pattern as media.contentUrl above (never a raw <a href> that
    // can't carry the Authorization header).
    exportGeojson: (params: {
      record_types: GeoRecordType[]; min_lat?: number; max_lat?: number; min_lon?: number; max_lon?: number
      since?: string; until?: string; max_features?: number
    }) => fetchGeoExport('/geospatial/export/geojson', params),
    exportCsv: (params: {
      record_types: GeoRecordType[]; min_lat?: number; max_lat?: number; min_lon?: number; max_lon?: number
      since?: string; until?: string; max_features?: number
    }) => fetchGeoExport('/geospatial/export/csv', params),
  },
  // --- Phase 8: edge AI / offline-first operation --------------------
  // JWT-authenticated admin surface only (the Edge Operations Center).
  // The device-authenticated submission endpoints
  // (/edge/sync/batch, /edge/sync/health) are a separate protocol used
  // by actual edge devices and are intentionally never called from here.
  devices: {
    list: (
      params: { page?: number; page_size?: number; administrative_status?: DeviceAdministrativeStatus | string; connectivity_state?: DeviceConnectivityState | string; search?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.administrative_status) search.set('administrative_status', params.administrative_status)
      if (params.connectivity_state) search.set('connectivity_state', params.connectivity_state)
      if (params.search) search.set('search', params.search)
      return request<Page<Device>>(`/devices?${search.toString()}`)
    },
    get: (id: string) => request<Device>(`/devices/${id}`),
    register: (payload: {
      device_identifier: string
      device_name: string
      device_type: string
      deployment_label?: string
      capabilities?: string[]
      inference_backends?: string[]
      model_manifest?: Record<string, unknown>
      metadata_note?: string
    }) => request<DeviceRegistrationResult>('/devices', { method: 'POST', body: JSON.stringify(payload) }),
    activate: (id: string, reason?: string) => request<Device>(`/devices/${id}/activate`, { method: 'POST', body: JSON.stringify({ reason }) }),
    suspend: (id: string, reason?: string) => request<Device>(`/devices/${id}/suspend`, { method: 'POST', body: JSON.stringify({ reason }) }),
    revoke: (id: string, reason?: string) => request<Device>(`/devices/${id}/revoke`, { method: 'POST', body: JSON.stringify({ reason }) }),
    rotateKey: (id: string) => request<DeviceRegistrationResult>(`/devices/${id}/rotate-key`, { method: 'POST' }),
    healthReports: (id: string, page = 1, pageSize = 20) =>
      request<Page<DeviceHealthReport>>(`/devices/${id}/health-reports?page=${page}&page_size=${pageSize}`),
    statusHistory: (id: string) => request<AuditRecord[]>(`/devices/${id}/status-history`),
    // --- ---------------------------------------------
    maintenance: (id: string, reason?: string) => request<Device>(`/devices/${id}/maintenance`, { method: 'POST', body: JSON.stringify({ reason }) }),
    decommission: (id: string, reason?: string) => request<Device>(`/devices/${id}/decommission`, { method: 'POST', body: JSON.stringify({ reason }) }),
    lifecyclePreview: (id: string, targetStatus: string) =>
      request<LifecyclePreview>(`/devices/${id}/lifecycle-preview?target_status=${encodeURIComponent(targetStatus)}`),
    assignSite: (id: string, siteId: string | null) =>
      request<Device>(`/devices/${id}/site`, { method: 'POST', body: JSON.stringify({ site_id: siteId }) }),
    capabilities: (id: string) => request<DeviceCapability[]>(`/devices/${id}/capabilities`),
    getConfig: (id: string) => request<DeviceConfigState>(`/devices/${id}/config`),
    // Returns 409 on a revision conflict (someone else changed the
    // config since the caller read it) -- the caller must catch this
    // and ask the user to reload and retry, never silently overwrite.
    updateConfig: (id: string, new_config: Record<string, unknown>, expected_revision: number) =>
      request<DeviceConfigState>(`/devices/${id}/config`, { method: 'PUT', body: JSON.stringify({ new_config, expected_revision }) }),
    assignBaseline: (id: string, baseline_id: string) =>
      request<DeviceConfigState>(`/devices/${id}/config/baseline`, { method: 'POST', body: JSON.stringify({ baseline_id }) }),
  },
  // --- Phase 10: explainable AI, evaluation, scoring and review -------
  analytics: {
    evaluations: {
      overview: (params: { page?: number; page_size?: number; model_record_id?: string } = {}) => {
        const search = new URLSearchParams()
        Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && search.set(k, String(v)))
        return request<Page<EvaluationOverviewRow>>(`/model-evaluations?${search.toString()}`)
      },
      get: (id: string) => request<ClassificationEvaluation>(`/model-evaluations/${id}`),
      run: (payload: ClassificationEvaluationRequest) =>
        request<ClassificationEvaluation>('/model-evaluations', { method: 'POST', body: JSON.stringify(payload) }),
    },
    outputs: {
      list: (params: { output_type: ModelOutputType; page?: number; page_size?: number; model_record_id?: string }) => {
        const search = new URLSearchParams()
        Object.entries(params).forEach(([k, v]) => v !== undefined && v !== '' && search.set(k, String(v)))
        return request<ModelOutputPage>(`/model-outputs?${search.toString()}`)
      },
      get: (type: ModelOutputType, id: string) => request<ModelOutput>(`/model-outputs/${type}/${id}`),
      explanation: (type: ModelOutputType, id: string, method?: string) =>
        request<Explanation>(`/model-outputs/${type}/${id}/explanation${method ? `?method=${encodeURIComponent(method)}` : ''}`),
    },
    assessments: {
      rules: () => request<ScoringRules>('/assessment-scoring-rules'),
      score: (assessmentId: string, payload: { rule_key?: string; config_overrides?: Record<string, unknown> } = {}) =>
        request<AssessmentScoreSnapshot>(`/assessments/${assessmentId}/score`, { method: 'POST', body: JSON.stringify(payload) }),
      scores: (assessmentId: string) => request<AssessmentScoreSnapshot[]>(`/assessments/${assessmentId}/scores`),
      reviews: (assessmentId: string) => request<ReviewSummary>(`/assessments/${assessmentId}/reviews`),
      submitReview: (
        assessmentId: string,
        payload: { decision: ReviewDecision; notes: string; change_reason?: string | null; information_flags?: string[]; score_snapshot_id?: string | null },
      ) => request<AssessmentReviewRecord>(`/assessments/${assessmentId}/reviews`, { method: 'POST', body: JSON.stringify(payload) }),
    },
  },
  // --- Phase 9: enterprise edge fleet management ---------------------
  fleetSites: {
    list: () => request<FleetSite[]>('/fleet/sites'),
    get: (id: string) => request<FleetSite>(`/fleet/sites/${id}`),
    summary: (id: string) => request<FleetSiteSummary>(`/fleet/sites/${id}/summary`),
    create: (payload: { name: string; description?: string; latitude?: number; longitude?: number }) =>
      request<FleetSite>('/fleet/sites', { method: 'POST', body: JSON.stringify(payload) }),
  },
  fleetConfig: {
    listBaselines: () => request<DeviceConfigBaseline[]>('/fleet/config-baselines'),
    getBaseline: (id: string) => request<DeviceConfigBaseline>(`/fleet/config-baselines/${id}`),
    createBaseline: (payload: { name: string; expected_config: Record<string, unknown>; description?: string; version?: number }) =>
      request<DeviceConfigBaseline>('/fleet/config-baselines', { method: 'POST', body: JSON.stringify(payload) }),
  },
  fleetCapabilities: {
    summary: () => request<FleetCapabilitySummaryEntry[]>('/fleet/capabilities/summary'),
  },
  infraAlerts: {
    list: (
      params: { page?: number; page_size?: number; status?: InfraAlertStatus | string; severity?: InfraAlertSeverity | string; device_id?: string; alert_type?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.status) search.set('status', params.status)
      if (params.severity) search.set('severity', params.severity)
      if (params.device_id) search.set('device_id', params.device_id)
      if (params.alert_type) search.set('alert_type', params.alert_type)
      return request<Page<InfrastructureAlert>>(`/fleet/alerts?${search.toString()}`)
    },
    get: (id: string) => request<InfrastructureAlert>(`/fleet/alerts/${id}`),
    acknowledge: (id: string, note?: string) => request<InfrastructureAlert>(`/fleet/alerts/${id}/acknowledge`, { method: 'POST', body: JSON.stringify({ note }) }),
    resolve: (id: string, note?: string) => request<InfrastructureAlert>(`/fleet/alerts/${id}/resolve`, { method: 'POST', body: JSON.stringify({ note }) }),
    reopen: (id: string, note?: string) => request<InfrastructureAlert>(`/fleet/alerts/${id}/reopen`, { method: 'POST', body: JSON.stringify({ note }) }),
    // No background scheduler exists in this build (same as
    // edgeSync.recoverStale) -- device_offline/device_stale alerts are
    // only ever raised by this explicit sweep, since a silent device
    // makes no request of its own for the inline evaluation path to
    // react to. See backend/app/services/fleet_alert_service.py's
    // module docstring.
    evaluateSweep: () => request<{ evaluated_device_count: number; alerts_touched_count: number }>('/fleet/alerts/evaluate-sweep', { method: 'POST' }),
  },
  fleetAnalytics: {
    overview: () => request<FleetOverview>('/fleet/analytics/overview'),
  },
  edgeSync: {
    records: (
      params: { page?: number; page_size?: number; device_id?: string; sync_status?: SyncRecordStatus | string; record_type?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.device_id) search.set('device_id', params.device_id)
      if (params.sync_status) search.set('sync_status', params.sync_status)
      if (params.record_type) search.set('record_type', params.record_type)
      return request<Page<SyncRecord>>(`/edge/sync/records?${search.toString()}`)
    },
    get: (id: string) => request<SyncRecord>(`/edge/sync/records/${id}`),
    retry: (id: string, reason?: string) => request<SyncRecord>(`/edge/sync/records/${id}/retry`, { method: 'POST', body: JSON.stringify({ reason }) }),
    cancel: (id: string, reason?: string) => request<SyncRecord>(`/edge/sync/records/${id}/cancel`, { method: 'POST', body: JSON.stringify({ reason }) }),
    queueSummary: () => request<SyncQueueSummary>('/edge/sync/queue/summary'),
    recoverStale: () => request<{ recovered_count: number }>('/edge/sync/recover-stale', { method: 'POST' }),
  },
  edgeConflicts: {
    list: (
      params: { page?: number; page_size?: number; resolution_status?: string; device_id?: string; record_type?: string } = {},
    ) => {
      const search = new URLSearchParams()
      search.set('page', String(params.page ?? 1))
      search.set('page_size', String(params.page_size ?? 20))
      if (params.resolution_status) search.set('resolution_status', params.resolution_status)
      if (params.device_id) search.set('device_id', params.device_id)
      if (params.record_type) search.set('record_type', params.record_type)
      return request<Page<SyncConflict>>(`/edge/conflicts?${search.toString()}`)
    },
    get: (id: string) => request<SyncConflict>(`/edge/conflicts/${id}`),
    resolve: (id: string, resolution_strategy: SyncConflictResolutionStrategy, resolution_note?: string) =>
      request<SyncConflict>(`/edge/conflicts/${id}/resolve`, { method: 'POST', body: JSON.stringify({ resolution_strategy, resolution_note }) }),
  },
}

async function fetchGeoExport(
  path: string,
  params: {
    record_types: GeoRecordType[]; min_lat?: number; max_lat?: number; min_lon?: number; max_lon?: number
    since?: string; until?: string; max_features?: number
  },
): Promise<{ blob: Blob; filename: string }> {
  const search = new URLSearchParams()
  params.record_types.forEach((t) => search.append('record_types', t))
  if (params.min_lat !== undefined) search.set('min_lat', String(params.min_lat))
  if (params.max_lat !== undefined) search.set('max_lat', String(params.max_lat))
  if (params.min_lon !== undefined) search.set('min_lon', String(params.min_lon))
  if (params.max_lon !== undefined) search.set('max_lon', String(params.max_lon))
  if (params.since) search.set('since', params.since)
  if (params.until) search.set('until', params.until)
  if (params.max_features) search.set('max_features', String(params.max_features))

  const headers = new Headers()
  if (getAccessToken()) headers.set('Authorization', `Bearer ${getAccessToken()}`)
  const response = await fetch(`${API_BASE}${path}?${search.toString()}`, { headers })
  if (!response.ok) {
    let detail = `Export failed with status ${response.status}`
    try {
      const body = await response.json()
      if (typeof body.detail === 'string') detail = body.detail
    } catch {
      // no JSON body -- keep the generic message
    }
    throw new ApiError(response.status, detail, null)
  }
  const disposition = response.headers.get('Content-Disposition') ?? ''
  const match = /filename="([^"]+)"/.exec(disposition)
  const filename = match ? match[1] : 'geospatial_export'
  const blob = await response.blob()
  return { blob, filename }
}

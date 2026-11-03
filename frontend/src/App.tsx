import { lazy, Suspense, type ReactNode } from 'react'
import { Navigate, Route, BrowserRouter, Routes, useLocation } from 'react-router-dom'
import { AuthProvider } from './context/AuthContext'
import { useAuth } from './context/auth'
import { AppShell } from './components/layout/AppShell'
import { ErrorBoundary } from './components/ErrorBoundary'
import { AdminOnly } from './components/AdminOnly'
import { Spinner } from './components/ui/Primitives'
import { LoginPage } from './pages/LoginPage'
import { DashboardPage } from './pages/DashboardPage'

// Pages are code-split: each loads on first visit (Login and Overview stay in the main bundle).
const EventsPage = lazy(() => import('./pages/EventsPage').then((m) => ({ default: m.EventsPage })))
const EventDetailPage = lazy(() => import('./pages/EventDetailPage').then((m) => ({ default: m.EventDetailPage })))
const SourcesPage = lazy(() => import('./pages/SourcesPage').then((m) => ({ default: m.SourcesPage })))
const AssetsPage = lazy(() => import('./pages/AssetsPage').then((m) => ({ default: m.AssetsPage })))
const SensorsPage = lazy(() => import('./pages/SensorsPage').then((m) => ({ default: m.SensorsPage })))
const SensorDetailPage = lazy(() => import('./pages/SensorDetailPage').then((m) => ({ default: m.SensorDetailPage })))
const SensorIngestionPage = lazy(() => import('./pages/SensorIngestionPage').then((m) => ({ default: m.SensorIngestionPage })))
const AnomalyReviewPage = lazy(() => import('./pages/AnomalyReviewPage').then((m) => ({ default: m.AnomalyReviewPage })))
const CrossSourceComparisonPage = lazy(() => import('./pages/CrossSourceComparisonPage').then((m) => ({ default: m.CrossSourceComparisonPage })))
const InvestigationsPage = lazy(() => import('./pages/InvestigationsPage').then((m) => ({ default: m.InvestigationsPage })))
const CopilotPage = lazy(() => import('./pages/CopilotPage').then((m) => ({ default: m.CopilotPage })))
const ScenariosPage = lazy(() => import('./pages/ScenariosPage').then((m) => ({ default: m.ScenariosPage })))
const AccessAdminPage = lazy(() => import('./pages/AccessAdminPage').then((m) => ({ default: m.AccessAdminPage })))
const ExecutiveOverviewPage = lazy(() => import('./pages/reporting/ExecutiveOverviewPage').then((m) => ({ default: m.ExecutiveOverviewPage })))
const AnalystWorkspacePage = lazy(() => import('./pages/reporting/AnalystWorkspacePage').then((m) => ({ default: m.AnalystWorkspacePage })))
const OperationsDashboardPage = lazy(() => import('./pages/reporting/OperationsDashboardPage').then((m) => ({ default: m.OperationsDashboardPage })))
const ReportBuilderPage = lazy(() => import('./pages/reporting/ReportBuilderPage').then((m) => ({ default: m.ReportBuilderPage })))
const MlopsRegistryPage = lazy(() => import('./pages/mlops/MlopsRegistryPage').then((m) => ({ default: m.MlopsRegistryPage })))
const ModelVersionDetailPage = lazy(() => import('./pages/mlops/ModelVersionDetailPage').then((m) => ({ default: m.ModelVersionDetailPage })))
const ExperimentWorkspacePage = lazy(() => import('./pages/mlops/ExperimentWorkspacePage').then((m) => ({ default: m.ExperimentWorkspacePage })))
const MonitoringDashboardPage = lazy(() => import('./pages/mlops/MonitoringDashboardPage').then((m) => ({ default: m.MonitoringDashboardPage })))
const ReviewQueuePage = lazy(() => import('./pages/mlops/ReviewQueuePage').then((m) => ({ default: m.ReviewQueuePage })))
const LifecyclePage = lazy(() => import('./pages/LifecyclePage').then((m) => ({ default: m.LifecyclePage })))
const SecurityConfigPage = lazy(() => import('./pages/SecurityConfigPage').then((m) => ({ default: m.SecurityConfigPage })))
const ScenarioDetailPage = lazy(() => import('./pages/ScenarioDetailPage').then((m) => ({ default: m.ScenarioDetailPage })))
const InvestigationDetailPage = lazy(() => import('./pages/InvestigationDetailPage').then((m) => ({ default: m.InvestigationDetailPage })))
const IngestionJobsPage = lazy(() => import('./pages/IngestionJobsPage').then((m) => ({ default: m.IngestionJobsPage })))
const JobDetailPage = lazy(() => import('./pages/JobDetailPage').then((m) => ({ default: m.JobDetailPage })))
const DataQualityPage = lazy(() => import('./pages/DataQualityPage').then((m) => ({ default: m.DataQualityPage })))
const CorrelationPage = lazy(() => import('./pages/CorrelationPage').then((m) => ({ default: m.CorrelationPage })))
const RiskAssessmentsPage = lazy(() => import('./pages/RiskAssessmentsPage').then((m) => ({ default: m.RiskAssessmentsPage })))
const HealthPage = lazy(() => import('./pages/HealthPage').then((m) => ({ default: m.HealthPage })))
const AuditPage = lazy(() => import('./pages/AuditPage').then((m) => ({ default: m.AuditPage })))
const FusionPage = lazy(() => import('./pages/FusionPage').then((m) => ({ default: m.FusionPage })))
const EvidencePage = lazy(() => import('./pages/EvidencePage').then((m) => ({ default: m.EvidencePage })))
const RelationshipsPage = lazy(() => import('./pages/RelationshipsPage').then((m) => ({ default: m.RelationshipsPage })))
const ConflictsPage = lazy(() => import('./pages/ConflictsPage').then((m) => ({ default: m.ConflictsPage })))
const EvidenceGraphPage = lazy(() => import('./pages/EvidenceGraphPage').then((m) => ({ default: m.EvidenceGraphPage })))
const AssessmentsPage = lazy(() => import('./pages/AssessmentsPage').then((m) => ({ default: m.AssessmentsPage })))
const AssessmentDetailPage = lazy(() => import('./pages/AssessmentDetailPage').then((m) => ({ default: m.AssessmentDetailPage })))
const CVOverviewPage = lazy(() => import('./pages/cv/CVOverviewPage').then((m) => ({ default: m.CVOverviewPage })))
const MediaLibraryPage = lazy(() => import('./pages/cv/MediaLibraryPage').then((m) => ({ default: m.MediaLibraryPage })))
const ImageDetectionWorkspacePage = lazy(() => import('./pages/cv/ImageDetectionWorkspacePage').then((m) => ({ default: m.ImageDetectionWorkspacePage })))
const VideoAnalysisWorkspacePage = lazy(() => import('./pages/cv/VideoAnalysisWorkspacePage').then((m) => ({ default: m.VideoAnalysisWorkspacePage })))
const ModelRegistryPage = lazy(() => import('./pages/cv/ModelRegistryPage').then((m) => ({ default: m.ModelRegistryPage })))
const InferenceJobMonitorPage = lazy(() => import('./pages/cv/InferenceJobMonitorPage').then((m) => ({ default: m.InferenceJobMonitorPage })))
const InferenceJobDetailPage = lazy(() => import('./pages/cv/InferenceJobDetailPage').then((m) => ({ default: m.InferenceJobDetailPage })))
const EvaluationWorkspacePage = lazy(() => import('./pages/cv/EvaluationWorkspacePage').then((m) => ({ default: m.EvaluationWorkspacePage })))
const CVEvidenceLinksPage = lazy(() => import('./pages/cv/CVEvidenceLinksPage').then((m) => ({ default: m.CVEvidenceLinksPage })))
const TrackingOverviewPage = lazy(() => import('./pages/tracking/TrackingOverviewPage').then((m) => ({ default: m.TrackingOverviewPage })))
const TrackingWorkspacePage = lazy(() => import('./pages/tracking/TrackingWorkspacePage').then((m) => ({ default: m.TrackingWorkspacePage })))
const TrackingJobMonitorPage = lazy(() => import('./pages/tracking/TrackingJobMonitorPage').then((m) => ({ default: m.TrackingJobMonitorPage })))
const TrackingJobDetailPage = lazy(() => import('./pages/tracking/TrackingJobDetailPage').then((m) => ({ default: m.TrackingJobDetailPage })))
const TrackDetailPage = lazy(() => import('./pages/tracking/TrackDetailPage').then((m) => ({ default: m.TrackDetailPage })))
const TrackComparisonPage = lazy(() => import('./pages/tracking/TrackComparisonPage').then((m) => ({ default: m.TrackComparisonPage })))
const TrackingEvaluationPage = lazy(() => import('./pages/tracking/TrackingEvaluationPage').then((m) => ({ default: m.TrackingEvaluationPage })))
const GeospatialOverviewPage = lazy(() => import('./pages/geo/GeospatialOverviewPage').then((m) => ({ default: m.GeospatialOverviewPage })))
const MapExplorerPage = lazy(() => import('./pages/geo/MapExplorerPage').then((m) => ({ default: m.MapExplorerPage })))
const TimelineExplorerPage = lazy(() => import('./pages/geo/TimelineExplorerPage').then((m) => ({ default: m.TimelineExplorerPage })))
const LocationQualityCenterPage = lazy(() => import('./pages/geo/LocationQualityCenterPage').then((m) => ({ default: m.LocationQualityCenterPage })))
const SpatialRelationshipExplorerPage = lazy(() => import('./pages/geo/SpatialRelationshipExplorerPage').then((m) => ({ default: m.SpatialRelationshipExplorerPage })))
const GeographicAnalyticsDashboardPage = lazy(() => import('./pages/geo/GeographicAnalyticsDashboardPage').then((m) => ({ default: m.GeographicAnalyticsDashboardPage })))
const ExportCenterPage = lazy(() => import('./pages/geo/ExportCenterPage').then((m) => ({ default: m.ExportCenterPage })))
const EdgeDeviceListPage = lazy(() => import('./pages/edge/EdgeDeviceListPage').then((m) => ({ default: m.EdgeDeviceListPage })))
const EdgeDeviceDetailPage = lazy(() => import('./pages/edge/EdgeDeviceDetailPage').then((m) => ({ default: m.EdgeDeviceDetailPage })))
const EdgeSyncQueuePage = lazy(() => import('./pages/edge/EdgeSyncQueuePage').then((m) => ({ default: m.EdgeSyncQueuePage })))
const EdgeConflictReviewPage = lazy(() => import('./pages/edge/EdgeConflictReviewPage').then((m) => ({ default: m.EdgeConflictReviewPage })))
const EdgeConflictDetailPage = lazy(() => import('./pages/edge/EdgeConflictDetailPage').then((m) => ({ default: m.EdgeConflictDetailPage })))
const FleetOverviewPage = lazy(() => import('./pages/fleet/FleetOverviewPage').then((m) => ({ default: m.FleetOverviewPage })))
const FleetSitesPage = lazy(() => import('./pages/fleet/FleetSitesPage').then((m) => ({ default: m.FleetSitesPage })))
const FleetAlertCenterPage = lazy(() => import('./pages/fleet/FleetAlertCenterPage').then((m) => ({ default: m.FleetAlertCenterPage })))
const EvaluationDashboardPage = lazy(() => import('./pages/analytics/EvaluationDashboardPage').then((m) => ({ default: m.EvaluationDashboardPage })))
const EvaluationDetailPage = lazy(() => import('./pages/analytics/EvaluationDetailPage').then((m) => ({ default: m.EvaluationDetailPage })))
const ModelOutputsPage = lazy(() => import('./pages/analytics/ModelOutputsPage').then((m) => ({ default: m.ModelOutputsPage })))
const ModelOutputDetailPage = lazy(() => import('./pages/analytics/ModelOutputDetailPage').then((m) => ({ default: m.ModelOutputDetailPage })))

function ProtectedLayout({ children }: { children: ReactNode }) {
  const { user, loading } = useAuth()
  const location = useLocation()
  if (loading) {
    return (
      <div className="flex min-h-screen items-center justify-center bg-navy-950">
        <Spinner />
      </div>
    )
  }
  if (!user) return <Navigate to="/login" replace />
  return (
    <AppShell>
      <ErrorBoundary resetKey={location.pathname}>
        <Suspense fallback={<Spinner />}>{children}</Suspense>
      </ErrorBoundary>
    </AppShell>
  )
}

export default function App() {
  return (
    <BrowserRouter>
      <AuthProvider>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<ProtectedLayout><DashboardPage /></ProtectedLayout>} />
          <Route path="/events" element={<ProtectedLayout><EventsPage /></ProtectedLayout>} />
          <Route path="/events/:eventId" element={<ProtectedLayout><EventDetailPage /></ProtectedLayout>} />
          <Route path="/sources" element={<ProtectedLayout><SourcesPage /></ProtectedLayout>} />
          <Route path="/assets" element={<ProtectedLayout><AssetsPage /></ProtectedLayout>} />
          <Route path="/sensors" element={<ProtectedLayout><SensorsPage /></ProtectedLayout>} />
          <Route path="/sensors/ingestion" element={<ProtectedLayout><SensorIngestionPage /></ProtectedLayout>} />
          <Route path="/sensors/anomalies" element={<ProtectedLayout><AnomalyReviewPage /></ProtectedLayout>} />
          <Route path="/sensors/cross-source" element={<ProtectedLayout><CrossSourceComparisonPage /></ProtectedLayout>} />
          <Route path="/sensors/:sensorId" element={<ProtectedLayout><SensorDetailPage /></ProtectedLayout>} />
          <Route path="/copilot" element={<ProtectedLayout><CopilotPage /></ProtectedLayout>} />
          <Route path="/reporting/executive" element={<ProtectedLayout><ExecutiveOverviewPage /></ProtectedLayout>} />
          <Route path="/reporting/analyst" element={<ProtectedLayout><AnalystWorkspacePage /></ProtectedLayout>} />
          <Route path="/reporting/operations" element={<ProtectedLayout><OperationsDashboardPage /></ProtectedLayout>} />
          <Route path="/reporting/reports" element={<ProtectedLayout><ReportBuilderPage /></ProtectedLayout>} />
          <Route path="/mlops/models" element={<ProtectedLayout><MlopsRegistryPage /></ProtectedLayout>} />
          <Route path="/mlops/models/:modelId" element={<ProtectedLayout><ModelVersionDetailPage /></ProtectedLayout>} />
          <Route path="/mlops/experiments" element={<ProtectedLayout><ExperimentWorkspacePage /></ProtectedLayout>} />
          <Route path="/mlops/monitoring" element={<ProtectedLayout><MonitoringDashboardPage /></ProtectedLayout>} />
          <Route path="/mlops/review" element={<ProtectedLayout><ReviewQueuePage /></ProtectedLayout>} />
          <Route path="/admin/access" element={<ProtectedLayout><AdminOnly><AccessAdminPage /></AdminOnly></ProtectedLayout>} />
          <Route path="/admin/lifecycle" element={<ProtectedLayout><AdminOnly><LifecyclePage /></AdminOnly></ProtectedLayout>} />
          <Route path="/admin/security" element={<ProtectedLayout><AdminOnly><SecurityConfigPage /></AdminOnly></ProtectedLayout>} />
          <Route path="/scenarios" element={<ProtectedLayout><ScenariosPage /></ProtectedLayout>} />
          <Route path="/scenarios/:scenarioId" element={<ProtectedLayout><ScenarioDetailPage /></ProtectedLayout>} />
          <Route path="/investigations" element={<ProtectedLayout><InvestigationsPage /></ProtectedLayout>} />
          <Route path="/investigations/:investigationId" element={<ProtectedLayout><InvestigationDetailPage /></ProtectedLayout>} />
          <Route path="/ingestion" element={<ProtectedLayout><IngestionJobsPage /></ProtectedLayout>} />
          <Route path="/ingestion/:jobId" element={<ProtectedLayout><JobDetailPage /></ProtectedLayout>} />
          <Route path="/data-quality" element={<ProtectedLayout><DataQualityPage /></ProtectedLayout>} />
          <Route path="/correlation" element={<ProtectedLayout><CorrelationPage /></ProtectedLayout>} />
          <Route path="/fusion" element={<ProtectedLayout><FusionPage /></ProtectedLayout>} />
          <Route path="/fusion/evidence" element={<ProtectedLayout><EvidencePage /></ProtectedLayout>} />
          <Route path="/fusion/relationships" element={<ProtectedLayout><RelationshipsPage /></ProtectedLayout>} />
          <Route path="/fusion/conflicts" element={<ProtectedLayout><ConflictsPage /></ProtectedLayout>} />
          <Route path="/fusion/graph" element={<ProtectedLayout><EvidenceGraphPage /></ProtectedLayout>} />
          <Route path="/fusion/assessments" element={<ProtectedLayout><AssessmentsPage /></ProtectedLayout>} />
          <Route path="/fusion/assessments/:assessmentId" element={<ProtectedLayout><AssessmentDetailPage /></ProtectedLayout>} />
          <Route path="/analytics/evaluations" element={<ProtectedLayout><EvaluationDashboardPage /></ProtectedLayout>} />
          <Route path="/analytics/evaluations/:runId" element={<ProtectedLayout><EvaluationDetailPage /></ProtectedLayout>} />
          <Route path="/analytics/outputs" element={<ProtectedLayout><ModelOutputsPage /></ProtectedLayout>} />
          <Route path="/analytics/outputs/:outputType/:outputId" element={<ProtectedLayout><ModelOutputDetailPage /></ProtectedLayout>} />
          <Route path="/cv" element={<ProtectedLayout><CVOverviewPage /></ProtectedLayout>} />
          <Route path="/cv/media" element={<ProtectedLayout><MediaLibraryPage /></ProtectedLayout>} />
          <Route path="/cv/image-detection" element={<ProtectedLayout><ImageDetectionWorkspacePage /></ProtectedLayout>} />
          <Route path="/cv/video-analysis" element={<ProtectedLayout><VideoAnalysisWorkspacePage /></ProtectedLayout>} />
          <Route path="/cv/models" element={<ProtectedLayout><ModelRegistryPage /></ProtectedLayout>} />
          <Route path="/cv/jobs" element={<ProtectedLayout><InferenceJobMonitorPage /></ProtectedLayout>} />
          <Route path="/cv/jobs/:jobId" element={<ProtectedLayout><InferenceJobDetailPage /></ProtectedLayout>} />
          <Route path="/cv/evaluation" element={<ProtectedLayout><EvaluationWorkspacePage /></ProtectedLayout>} />
          <Route path="/cv/evidence" element={<ProtectedLayout><CVEvidenceLinksPage /></ProtectedLayout>} />
          <Route path="/tracking" element={<ProtectedLayout><TrackingOverviewPage /></ProtectedLayout>} />
          <Route path="/tracking/workspace" element={<ProtectedLayout><TrackingWorkspacePage /></ProtectedLayout>} />
          <Route path="/tracking/jobs" element={<ProtectedLayout><TrackingJobMonitorPage /></ProtectedLayout>} />
          <Route path="/tracking/jobs/:jobId" element={<ProtectedLayout><TrackingJobDetailPage /></ProtectedLayout>} />
          <Route path="/tracking/tracks/:trackId" element={<ProtectedLayout><TrackDetailPage /></ProtectedLayout>} />
          <Route path="/tracking/compare" element={<ProtectedLayout><TrackComparisonPage /></ProtectedLayout>} />
          <Route path="/tracking/evaluation" element={<ProtectedLayout><TrackingEvaluationPage /></ProtectedLayout>} />
          <Route path="/geospatial" element={<ProtectedLayout><GeospatialOverviewPage /></ProtectedLayout>} />
          <Route path="/geospatial/map" element={<ProtectedLayout><MapExplorerPage /></ProtectedLayout>} />
          <Route path="/geospatial/timeline" element={<ProtectedLayout><TimelineExplorerPage /></ProtectedLayout>} />
          <Route path="/geospatial/quality" element={<ProtectedLayout><LocationQualityCenterPage /></ProtectedLayout>} />
          <Route path="/geospatial/relationships" element={<ProtectedLayout><SpatialRelationshipExplorerPage /></ProtectedLayout>} />
          <Route path="/geospatial/analytics" element={<ProtectedLayout><GeographicAnalyticsDashboardPage /></ProtectedLayout>} />
          <Route path="/geospatial/export" element={<ProtectedLayout><ExportCenterPage /></ProtectedLayout>} />
          <Route path="/edge/devices" element={<ProtectedLayout><EdgeDeviceListPage /></ProtectedLayout>} />
          <Route path="/edge/devices/:deviceId" element={<ProtectedLayout><EdgeDeviceDetailPage /></ProtectedLayout>} />
          <Route path="/edge/sync" element={<ProtectedLayout><EdgeSyncQueuePage /></ProtectedLayout>} />
          <Route path="/edge/conflicts" element={<ProtectedLayout><EdgeConflictReviewPage /></ProtectedLayout>} />
          <Route path="/edge/conflicts/:conflictId" element={<ProtectedLayout><EdgeConflictDetailPage /></ProtectedLayout>} />
          <Route path="/fleet/overview" element={<ProtectedLayout><FleetOverviewPage /></ProtectedLayout>} />
          <Route path="/fleet/sites" element={<ProtectedLayout><FleetSitesPage /></ProtectedLayout>} />
          <Route path="/fleet/alerts" element={<ProtectedLayout><FleetAlertCenterPage /></ProtectedLayout>} />
          <Route path="/risk-assessments" element={<ProtectedLayout><RiskAssessmentsPage /></ProtectedLayout>} />
          <Route path="/health" element={<ProtectedLayout><HealthPage /></ProtectedLayout>} />
          <Route path="/audit" element={<ProtectedLayout><AdminOnly><AuditPage /></AdminOnly></ProtectedLayout>} />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </AuthProvider>
    </BrowserRouter>
  )
}

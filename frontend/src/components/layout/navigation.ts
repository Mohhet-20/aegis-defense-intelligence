// Single source of the app's navigation: the sidebar (AppShell) and the
// Overview page's workspace directory both render from this list, so a
// route added here appears in both. Every `to` must exist in App.tsx
// (tests/test_frontend_contract.py checks frontend links against routes).

export interface NavItem {
  to: string
  label: string
  adminOnly?: boolean
}

export interface NavGroup {
  title: string
  description: string
  items: NavItem[]
}

export const NAV_GROUPS: NavGroup[] = [
  {
    title: 'Data operations',
    description: 'Sources, file ingestion with provenance, data quality and rule-based event correlation.',
    items: [
      { to: '/events', label: 'Events' },
      { to: '/sources', label: 'Data Sources' },
      { to: '/ingestion', label: 'Ingestion Center' },
      { to: '/data-quality', label: 'Data Quality' },
      { to: '/correlation', label: 'Correlation Review' },
      { to: '/assets', label: 'Assets' },
    ],
  },
  {
    title: 'Sensors',
    description: 'Sensor registry, observation ingestion, statistical anomaly review and cross-source comparison.',
    items: [
      { to: '/sensors', label: 'Sensors' },
      { to: '/sensors/ingestion', label: 'Sensor Ingestion' },
      { to: '/sensors/anomalies', label: 'Anomaly Review' },
      { to: '/sensors/cross-source', label: 'Cross-Source Comparison' },
    ],
  },
  {
    title: 'Investigations & fusion',
    description: 'Cases, evidence, analyst-reviewed relationships, conflicts, assessments and the cited copilot.',
    items: [
      { to: '/investigations', label: 'Investigations' },
      { to: '/fusion', label: 'Intelligence Fusion' },
      { to: '/fusion/evidence', label: 'Evidence Library' },
      { to: '/fusion/relationships', label: 'Relationships' },
      { to: '/fusion/conflicts', label: 'Conflict Review' },
      { to: '/fusion/graph', label: 'Evidence Graph' },
      { to: '/fusion/assessments', label: 'Assessments' },
      { to: '/risk-assessments', label: 'Risk Assessments' },
      { to: '/copilot', label: 'Intelligence Copilot' },
    ],
  },
  {
    title: 'Computer vision & tracking',
    description: 'Private media, a real pretrained detector (SSD-MobileNet) and baselines, human review of detections, multi-object tracking.',
    items: [
      { to: '/cv', label: 'Computer Vision' },
      { to: '/cv/media', label: 'Media Library' },
      { to: '/cv/image-detection', label: 'Image Detection' },
      { to: '/cv/video-analysis', label: 'Video Analysis' },
      { to: '/cv/models', label: 'CV Model Registry' },
      { to: '/cv/jobs', label: 'Inference Jobs' },
      { to: '/cv/evaluation', label: 'Model Evaluation' },
      { to: '/cv/evidence', label: 'CV Evidence Links' },
      { to: '/tracking', label: 'Tracking' },
      { to: '/tracking/workspace', label: 'Tracking Workspace' },
      { to: '/tracking/jobs', label: 'Tracking Job Monitor' },
      { to: '/tracking/compare', label: 'Track Comparison' },
      { to: '/tracking/evaluation', label: 'Tracking Evaluation' },
    ],
  },
  {
    title: 'Geospatial',
    description: 'Map and timeline exploration, location quality, spatial relationships and bounded export.',
    items: [
      { to: '/geospatial', label: 'Geospatial Overview' },
      { to: '/geospatial/map', label: 'Map Explorer' },
      { to: '/geospatial/timeline', label: 'Timeline Explorer' },
      { to: '/geospatial/quality', label: 'Location Quality Center' },
      { to: '/geospatial/relationships', label: 'Spatial Relationships' },
      { to: '/geospatial/analytics', label: 'Geographic Analytics' },
      { to: '/geospatial/export', label: 'Geospatial Export' },
    ],
  },
  {
    title: 'Edge & fleet',
    description: 'Device registry, durable sync queue, conflict review and fleet health (simulated devices only).',
    items: [
      { to: '/fleet/overview', label: 'Fleet Overview' },
      { to: '/edge/devices', label: 'Edge Devices' },
      { to: '/fleet/sites', label: 'Fleet Sites' },
      { to: '/edge/sync', label: 'Sync Queue' },
      { to: '/edge/conflicts', label: 'Edge Conflict Review' },
      { to: '/fleet/alerts', label: 'Fleet Alerts' },
    ],
  },
  {
    title: 'Models & evaluation',
    description: 'Model registry and lifecycle, experiments, monitoring, explanations and review queues.',
    items: [
      { to: '/mlops/models', label: 'MLOps Model Registry' },
      { to: '/mlops/experiments', label: 'Experiment Workspace' },
      { to: '/mlops/monitoring', label: 'Model Monitoring' },
      { to: '/mlops/review', label: 'Model Review Queue' },
      { to: '/analytics/evaluations', label: 'Evaluation Dashboard' },
      { to: '/analytics/outputs', label: 'Model Outputs & Explanations' },
    ],
  },
  {
    title: 'Analytics & reporting',
    description: 'Dashboards computed from stored records, report generation, and clearly labelled simulations.',
    items: [
      { to: '/reporting/executive', label: 'Executive Overview' },
      { to: '/reporting/analyst', label: 'Analyst Workspace' },
      { to: '/reporting/operations', label: 'Operations Dashboard' },
      { to: '/reporting/reports', label: 'Reports' },
      { to: '/scenarios', label: 'Scenario Simulation' },
    ],
  },
  {
    title: 'Administration',
    description: 'System health, audit trail, accounts and roles, data lifecycle and security settings.',
    items: [
      { to: '/health', label: 'System Health' },
      { to: '/audit', label: 'Audit Explorer', adminOnly: true },
      { to: '/admin/access', label: 'Access Administration', adminOnly: true },
      { to: '/admin/lifecycle', label: 'Data Lifecycle', adminOnly: true },
      { to: '/admin/security', label: 'Security Configuration', adminOnly: true },
    ],
  },
]

/** Groups with the items this role may open (administrator-only pages hidden for others). */
export function visibleGroups(role: string | undefined): NavGroup[] {
  return NAV_GROUPS.map((g) => ({ ...g, items: g.items.filter((i) => !i.adminOnly || role === 'administrator') })).filter(
    (g) => g.items.length > 0,
  )
}

/** Longest nav prefix that matches a pathname, e.g. /cv/jobs/123 -> /cv/jobs. */
export function groupForPath(pathname: string): string | undefined {
  let best: { title: string; len: number } | undefined
  for (const g of NAV_GROUPS) {
    for (const i of g.items) {
      if ((pathname === i.to || pathname.startsWith(i.to + '/')) && (!best || i.to.length > best.len)) {
        best = { title: g.title, len: i.to.length }
      }
    }
  }
  return best?.title
}

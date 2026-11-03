"""Import every model so app.db.base.Base.metadata is fully populated --
required for Alembic autogenerate and for tests that call
Base.metadata.create_all() directly."""
from app.models.organization import Organization  # noqa: F401
from app.models.user import User  # noqa: F401
from app.models.data_source import DataSource  # noqa: F401
from app.models.asset import Asset  # noqa: F401
from app.models.sensor import Sensor  # noqa: F401
from app.models.event import Event  # noqa: F401
from app.models.observation import Observation  # noqa: F401
from app.models.investigation import Investigation  # noqa: F401
from app.models.model_record import ModelRecord  # noqa: F401
from app.models.risk_assessment import RiskAssessment  # noqa: F401
from app.models.ingestion_job import IngestionJob  # noqa: F401
from app.models.audit import AuditRecord  # noqa: F401
from app.models.device import Device  # noqa: F401
from app.models.raw_record import RawRecord  # noqa: F401
from app.models.event_correlation import EventCorrelation  # noqa: F401
from app.models.evidence import Evidence  # noqa: F401
from app.models.evidence_relationship import EvidenceRelationship  # noqa: F401
from app.models.conflict import Conflict  # noqa: F401
from app.models.assessment import Assessment, AssessmentEvidenceLink, AssessmentRevision  # noqa: F401
from app.models.fusion_job import FusionJob  # noqa: F401
from app.models.media_asset import MediaAsset  # noqa: F401
from app.models.inference_job import InferenceJob  # noqa: F401
from app.models.detection_result import DetectionResult  # noqa: F401
from app.models.model_evaluation_run import ModelEvaluationRun  # noqa: F401
from app.models.tracking_job import TrackingJob  # noqa: F401
from app.models.track import Track  # noqa: F401
from app.models.track_observation import TrackObservation  # noqa: F401
from app.models.track_annotation import TrackAnnotation  # noqa: F401
from app.models.tracking_evaluation_run import TrackingEvaluationRun  # noqa: F401
from app.models.observation_anomaly import ObservationAnomaly  # noqa: F401
from app.models.sync_record import SyncRecord  # noqa: F401
from app.models.sync_conflict import SyncConflict  # noqa: F401
from app.models.device_health_report import DeviceHealthReport  # noqa: F401
from app.models.fleet_site import FleetSite  # noqa: F401
from app.models.device_config_baseline import DeviceConfigBaseline  # noqa: F401
from app.models.device_capability import DeviceCapability  # noqa: F401
from app.models.infrastructure_alert import InfrastructureAlert  # noqa: F401
from app.models.classification_evaluation_run import ClassificationEvaluationRun  # noqa: F401
from app.models.assessment_score import AssessmentScoreSnapshot  # noqa: F401
from app.models.assessment_review import AssessmentReview  # noqa: F401
from app.models.investigation_workspace import (  # noqa: F401
    EvidenceIntegrityCheck, InvestigationLink, InvestigationMember, InvestigationNote,
    InvestigationNoteRevision, InvestigationStatusHistory,
)
from app.models.retrieval import CopilotConversation, CopilotMessage, RetrievalChunk, RetrievalDocument, RetrievalIndexRun  # noqa: F401
from app.models.scenario import Scenario, ScenarioRun, SyntheticDataset  # noqa: F401
from app.models.lifecycle import LifecycleRequest  # noqa: F401
from app.models.mlops import ExperimentBaseline, ExperimentRun, ModelLifecycleEvent, MonitoringSnapshot, ReviewSignal  # noqa: F401
from app.models.report import ReportRun  # noqa: F401
from app.models import analytics_indexes  # noqa: F401

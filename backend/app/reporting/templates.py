"""Report templates. Every template is backed by implemented analytics sections;
a template naming a section that does not exist cannot be registered (import-time check)."""
from __future__ import annotations

from app.core.security import Permission
from app.reporting.definitions import SECTION_IDS

SECTION_PERMISSIONS: dict[str, tuple[Permission, ...]] = {
    "events": (Permission.EVENT_READ,),
    "observations": (Permission.OBSERVATION_READ,),
    "ingestion": (Permission.DATA_QUALITY_READ,),
    "fusion": (Permission.FUSION_READ,),
    "sensors": (Permission.SENSOR_READ, Permission.OBSERVATION_READ),
    "investigations": (Permission.INVESTIGATION_READ,),
    "evidence": (Permission.EVIDENCE_READ,),
    "models": (Permission.MLOPS_READ,),
    "system": (Permission.REPORTING_READ,),
    "geo": (Permission.GEOSPATIAL_READ,),
    "review_backlog": (),
}

TEMPLATES: dict[str, dict] = {
    "platform_activity": {"title": "Platform activity", "description": "Event and observation volume, data origin and timing for the window, with the review backlog.",
                          "sections": ("events", "observations", "review_backlog")},
    "ingestion_quality": {"title": "Ingestion and data quality", "description": "Ingestion job outcomes, record rejection/duplication, late arrivals and missing-field rates.",
                          "sections": ("ingestion", "events", "observations")},
    "sensor_coverage": {"title": "Sensor coverage", "description": "Observation coverage per sensor against nominal sampling intervals, silent sensors and anomaly review state. Data coverage, not uptime.",
                        "sections": ("sensors", "observations")},
    "investigation_summary": {"title": "Investigation workflow summary", "description": "Investigations you can access: status, throughput, time to close and review backlog. Not a performance measure for analysts.",
                              "sections": ("investigations", "review_backlog")},
    "evidence_provenance": {"title": "Evidence and provenance", "description": "Evidence volume, review state, documentation gaps (origin links, integrity hashes), fusion relationships and conflicts.",
                            "sections": ("evidence", "fusion")},
    "model_evaluation": {"title": "Model evaluation and monitoring", "description": "Latest stored evaluations, review signals, monitoring coverage and inference job outcomes. Stored metrics only.",
                         "sections": ("models",)},
    "system_reliability": {"title": "System reliability", "description": "Dependency readiness, background job outcomes, request metrics (this process) and data-lifecycle requests.",
                           "sections": ("system", "ingestion")},
    "geospatial_summary": {"title": "Geospatial summary", "description": "Coordinate validity and suppressed, aggregated grid counts. No individual coordinates.",
                           "sections": ("geo",)},
    "custom": {"title": "Custom report", "description": "Choose any of the available analytics sections.", "sections": ()},
}
for _k, _t in TEMPLATES.items():
    for _s in _t["sections"]:
        assert _s in SECTION_IDS and _s in SECTION_PERMISSIONS, f"template {_k} references unknown section {_s}"


def required_permissions(sections: list[str]) -> list[str]:
    out: list[str] = []
    for s in sections:
        for p in SECTION_PERMISSIONS[s]:
            if p.value not in out:
                out.append(p.value)
    return sorted(out)

"""Phase 6: multi-sensor data platform, observation analytics, signal
quality, anomaly detection, and sensor health.

Pure, DB-free logic lives here (units, quality classification,
descriptive statistics, anomaly detection, adapters). Anything that
touches the database lives in app/services/ -- same split Phase 2's
app/connectors/ + app/services/ingestion_service.py already established,
and Phase 4/5's app/cv/ + app/tracking/ repeated.
"""

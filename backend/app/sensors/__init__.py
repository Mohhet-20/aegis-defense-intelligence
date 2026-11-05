"""Multi-sensor data platform, observation analytics, signal
quality, anomaly detection, and sensor health.

Pure, DB-free logic lives here (units, quality classification,
descriptive statistics, anomaly detection, adapters). Anything that
touches the database lives in app/services/ -- same split the
app/connectors/ + app/services/ingestion_service.py already established,
and the app/cv/ + app/tracking/ repeated.
"""

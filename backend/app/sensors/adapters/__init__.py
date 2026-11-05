"""Sensor observation adapters. Each adapter
implements the SAME app.connectors.base.BaseConnector interface
the data platform's Event connectors already use, and produces the same
app.connectors.types.RawRecord/ConnectorResult dataclasses -- this is
exactly the "future sensor/CV/edge adapter plugs in later without
rewriting the ingestion engine" extension point that interface's own
docstring already anticipated.

A sensor adapter's RawRecord.payload uses the canonical input shape
app/sensors/quality.py validates: {"sensor_id", "measurement_type",
"value", "unit", "observed_at", optionally "latitude"/"longitude",
"device_status"}. This is a DIFFERENT record shape from an Event
connector's payload (which has event_type/title/...) -- the two
connector families share an interface, never a schema.
"""

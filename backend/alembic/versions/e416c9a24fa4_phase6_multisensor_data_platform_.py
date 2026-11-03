"""prompt6_multisensor_data_platform_observation_analytics

Revision ID: e416c9a24fa4
Revises: e17c59a0bbd2
Create Date: 2026-10-13 15:32:26.461784

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = 'e416c9a24fa4'
down_revision: Union[str, None] = 'e17c59a0bbd2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # --- New table: observation_anomalies (Section 9) -----------------
    op.create_table(
        'observation_anomalies',
        sa.Column('organization_id', sa.String(length=36), nullable=False),
        sa.Column('sensor_id', sa.String(length=36), nullable=False),
        sa.Column('measurement_type', sa.String(length=100), nullable=False),
        sa.Column('observation_id', sa.String(length=36), nullable=True),
        sa.Column('window_start', sa.DateTime(timezone=True), nullable=True),
        sa.Column('window_end', sa.DateTime(timezone=True), nullable=True),
        sa.Column('detection_method', sa.String(length=50), nullable=False),
        sa.Column('method_version', sa.String(length=20), nullable=False),
        sa.Column('config', sa.JSON(), nullable=False),
        sa.Column('observed_value', sa.Float(), nullable=True),
        sa.Column('observed_summary', sa.JSON(), nullable=False),
        sa.Column('baseline_summary', sa.JSON(), nullable=True),
        sa.Column('explanation', sa.String(length=2000), nullable=False),
        sa.Column('severity', sa.String(length=10), nullable=False),
        sa.Column('category', sa.String(length=30), nullable=False),
        sa.Column('quality_flags', sa.JSON(), nullable=False),
        sa.Column('review_status', sa.String(length=30), nullable=False),
        sa.Column('reviewed_by_user_id', sa.String(length=36), nullable=True),
        sa.Column('reviewed_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('review_note', sa.String(length=2000), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), nullable=False),
        sa.Column('updated_at', sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(['observation_id'], ['observations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['organization_id'], ['organizations.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['reviewed_by_user_id'], ['users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['sensor_id'], ['sensors.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_observation_anomalies_category'), 'observation_anomalies', ['category'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_detection_method'), 'observation_anomalies', ['detection_method'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_measurement_type'), 'observation_anomalies', ['measurement_type'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_observation_id'), 'observation_anomalies', ['observation_id'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_organization_id'), 'observation_anomalies', ['organization_id'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_review_status'), 'observation_anomalies', ['review_status'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_sensor_id'), 'observation_anomalies', ['sensor_id'], unique=False)
    op.create_index(op.f('ix_observation_anomalies_severity'), 'observation_anomalies', ['severity'], unique=False)

    # --- observations: canonical schema extensions (Section 4) -------
    # NOT NULL columns get an explicit server_default so the existing
    # Phase-1 seed rows backfill cleanly rather than failing the ALTER.
    op.add_column('observations', sa.Column('ingested_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('observations', sa.Column('measurement_value', sa.Float(), nullable=True))
    op.add_column('observations', sa.Column('unit', sa.String(length=50), nullable=True))
    op.add_column('observations', sa.Column('validation_status', sa.String(length=20), nullable=False, server_default='valid'))
    op.add_column('observations', sa.Column('quality_flags', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('observations', sa.Column('source_record_id', sa.String(length=36), nullable=True))
    op.add_column('observations', sa.Column('ingestion_job_id', sa.String(length=36), nullable=True))
    op.add_column('observations', sa.Column('schema_version', sa.String(length=10), nullable=False, server_default='1.0'))
    op.add_column('observations', sa.Column('calibration_metadata', sa.JSON(), nullable=True))
    op.add_column('observations', sa.Column('uncertainty_metadata', sa.JSON(), nullable=True))
    op.create_index(op.f('ix_observations_ingested_at'), 'observations', ['ingested_at'], unique=False)
    op.create_index(op.f('ix_observations_ingestion_job_id'), 'observations', ['ingestion_job_id'], unique=False)
    op.create_index(op.f('ix_observations_source_record_id'), 'observations', ['source_record_id'], unique=False)
    op.create_index(op.f('ix_observations_validation_status'), 'observations', ['validation_status'], unique=False)
    with op.batch_alter_table('observations', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_observations_ingestion_job_id', 'ingestion_jobs', ['ingestion_job_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_observations_source_record_id', 'raw_records', ['source_record_id'], ['id'], ondelete='SET NULL')

    # --- sensors: richer registry metadata + lifecycle (Section 3) ---
    op.add_column('sensors', sa.Column('category', sa.String(length=50), nullable=True))
    op.add_column('sensors', sa.Column('description', sa.String(length=2000), nullable=True))
    op.add_column('sensors', sa.Column('manufacturer', sa.String(length=200), nullable=True))
    op.add_column('sensors', sa.Column('model_name', sa.String(length=200), nullable=True))
    op.add_column('sensors', sa.Column('asset_id', sa.String(length=36), nullable=True))
    op.add_column('sensors', sa.Column('measurement_types', sa.JSON(), nullable=False, server_default='[]'))
    op.add_column('sensors', sa.Column('measurement_units', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('sensors', sa.Column('operating_range', sa.JSON(), nullable=False, server_default='{}'))
    op.add_column('sensors', sa.Column('nominal_sampling_interval_seconds', sa.Float(), nullable=True))
    op.add_column('sensors', sa.Column('expected_data_format', sa.String(length=50), nullable=True))
    op.add_column('sensors', sa.Column('sensor_timezone', sa.String(length=50), nullable=False, server_default='UTC'))
    op.add_column('sensors', sa.Column('lifecycle_status', sa.String(length=20), nullable=False, server_default='registered'))
    op.add_column('sensors', sa.Column('last_ingestion_success_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sensors', sa.Column('device_reported_status', sa.String(length=50), nullable=True))
    op.add_column('sensors', sa.Column('device_reported_status_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sensors', sa.Column('retired_at', sa.DateTime(timezone=True), nullable=True))
    op.add_column('sensors', sa.Column('retired_by_user_id', sa.String(length=36), nullable=True))
    op.create_index(op.f('ix_sensors_asset_id'), 'sensors', ['asset_id'], unique=False)
    op.create_index(op.f('ix_sensors_category'), 'sensors', ['category'], unique=False)
    op.create_index(op.f('ix_sensors_lifecycle_status'), 'sensors', ['lifecycle_status'], unique=False)
    with op.batch_alter_table('sensors', schema=None) as batch_op:
        batch_op.create_foreign_key('fk_sensors_retired_by_user_id', 'users', ['retired_by_user_id'], ['id'], ondelete='SET NULL')
        batch_op.create_foreign_key('fk_sensors_asset_id', 'assets', ['asset_id'], ['id'], ondelete='SET NULL')

    # Existing Phase-1 seed rows (and any sensor created before this
    # migration) have no lifecycle_status set by application code yet
    # -- the server_default above already backfills 'registered' for
    # every pre-existing row, consistent with "a sensor's lifecycle
    # starts at registered until it reports real data."


def downgrade() -> None:
    with op.batch_alter_table('sensors', schema=None) as batch_op:
        batch_op.drop_constraint('fk_sensors_asset_id', type_='foreignkey')
        batch_op.drop_constraint('fk_sensors_retired_by_user_id', type_='foreignkey')
    op.drop_index(op.f('ix_sensors_lifecycle_status'), table_name='sensors')
    op.drop_index(op.f('ix_sensors_category'), table_name='sensors')
    op.drop_index(op.f('ix_sensors_asset_id'), table_name='sensors')
    op.drop_column('sensors', 'retired_by_user_id')
    op.drop_column('sensors', 'retired_at')
    op.drop_column('sensors', 'device_reported_status_at')
    op.drop_column('sensors', 'device_reported_status')
    op.drop_column('sensors', 'last_ingestion_success_at')
    op.drop_column('sensors', 'lifecycle_status')
    op.drop_column('sensors', 'sensor_timezone')
    op.drop_column('sensors', 'expected_data_format')
    op.drop_column('sensors', 'nominal_sampling_interval_seconds')
    op.drop_column('sensors', 'operating_range')
    op.drop_column('sensors', 'measurement_units')
    op.drop_column('sensors', 'measurement_types')
    op.drop_column('sensors', 'asset_id')
    op.drop_column('sensors', 'model_name')
    op.drop_column('sensors', 'manufacturer')
    op.drop_column('sensors', 'description')
    op.drop_column('sensors', 'category')

    with op.batch_alter_table('observations', schema=None) as batch_op:
        batch_op.drop_constraint('fk_observations_source_record_id', type_='foreignkey')
        batch_op.drop_constraint('fk_observations_ingestion_job_id', type_='foreignkey')
    op.drop_index(op.f('ix_observations_validation_status'), table_name='observations')
    op.drop_index(op.f('ix_observations_source_record_id'), table_name='observations')
    op.drop_index(op.f('ix_observations_ingestion_job_id'), table_name='observations')
    op.drop_index(op.f('ix_observations_ingested_at'), table_name='observations')
    op.drop_column('observations', 'uncertainty_metadata')
    op.drop_column('observations', 'calibration_metadata')
    op.drop_column('observations', 'schema_version')
    op.drop_column('observations', 'ingestion_job_id')
    op.drop_column('observations', 'source_record_id')
    op.drop_column('observations', 'quality_flags')
    op.drop_column('observations', 'validation_status')
    op.drop_column('observations', 'unit')
    op.drop_column('observations', 'measurement_value')
    op.drop_column('observations', 'ingested_at')

    op.drop_index(op.f('ix_observation_anomalies_severity'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_sensor_id'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_review_status'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_organization_id'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_observation_id'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_measurement_type'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_detection_method'), table_name='observation_anomalies')
    op.drop_index(op.f('ix_observation_anomalies_category'), table_name='observation_anomalies')
    op.drop_table('observation_anomalies')

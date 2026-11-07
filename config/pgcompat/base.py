"""
DEV-ONLY: lets Django 6.1 talk to a local PostgreSQL 13/14 (Django 6.1 officially needs 15+).
Used only when DEBUG is on and POSTGRES_ALLOW_OLD=True. Staging/production (RDS PostgreSQL 16) use the stock engine.
Upgrade local Postgres (`brew install postgresql@16`) and remove this when convenient.
"""
from django.db.backends.postgresql import base, features


class DatabaseFeatures(features.DatabaseFeatures):
    minimum_database_version = (13,)


class DatabaseWrapper(base.DatabaseWrapper):
    features_class = DatabaseFeatures

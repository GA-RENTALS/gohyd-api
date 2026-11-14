"""Row-level security for tenant tables, for use in migrations that create them.

Every table with a `tenant_id` column must only show the rows of the tenant set in `app.tenant_id` (see
tenancy/migrations/0003_enable_tenant_rls.py). A migration that creates such a table ends with::

    migrations.RunPython(*tenant_rls('my_new_table'))
"""
import hashlib


def _policy(table):
    return f'tenant_scope_{hashlib.sha256(table.encode()).hexdigest()[:10]}'


def tenant_rls(*tables):
    """(forwards, backwards) functions for RunPython that switch tenant RLS on / off for `tables`. Safe to re-run."""

    def enable(apps, schema_editor):
        connection = schema_editor.connection
        if connection.vendor != 'postgresql':
            raise RuntimeError('Tenant RLS requires PostgreSQL.')
        q = schema_editor.quote_name
        scope = f"{q('tenant_id')}::text = NULLIF(current_setting('app.tenant_id', true), '')"
        with connection.cursor() as cursor:
            for name in tables:
                table, policy = q(name), q(_policy(name))
                cursor.execute(f'ALTER TABLE {table} ENABLE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {table} FORCE ROW LEVEL SECURITY')
                cursor.execute(f'DROP POLICY IF EXISTS {policy} ON {table}')
                cursor.execute(f'CREATE POLICY {policy} ON {table} USING ({scope}) WITH CHECK ({scope})')

    def disable(apps, schema_editor):
        if schema_editor.connection.vendor != 'postgresql':
            return
        q = schema_editor.quote_name
        with schema_editor.connection.cursor() as cursor:
            for name in tables:
                table = q(name)
                cursor.execute(f'DROP POLICY IF EXISTS {q(_policy(name))} ON {table}')
                cursor.execute(f'ALTER TABLE {table} NO FORCE ROW LEVEL SECURITY')
                cursor.execute(f'ALTER TABLE {table} DISABLE ROW LEVEL SECURITY')

    return enable, disable

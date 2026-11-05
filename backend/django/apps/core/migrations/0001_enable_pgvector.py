from django.db import migrations


class Migration(migrations.Migration):
    """Enable pgvector for FastAPI's embedding tables.

    The reverse is a no-op so rolling back Django migrations never drops the
    extension (and with it any vector columns) out from under FastAPI.
    """

    initial = True

    dependencies = []

    operations = [
        migrations.RunSQL(
            sql="CREATE EXTENSION IF NOT EXISTS vector;",
            reverse_sql=migrations.RunSQL.noop,
        ),
    ]

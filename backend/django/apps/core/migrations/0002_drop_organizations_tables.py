from django.db import migrations

# The organizations app was removed without any user flow reaching it. Its
# tables stay behind on databases that ran its migration, so drop them here.
# IF EXISTS keeps this a no-op on fresh databases that never had them.
DROP_TABLES = """
DROP TABLE IF EXISTS organizations_orgrepository;
DROP TABLE IF EXISTS organizations_teammembership;
DROP TABLE IF EXISTS organizations_organization;
DELETE FROM django_migrations WHERE app = 'organizations';
"""


def remove_content_types(apps, schema_editor):
    # Deleting the content types cascades to their permissions and to any
    # user or group grants of those permissions.
    ContentType = apps.get_model("contenttypes", "ContentType")
    ContentType.objects.using(schema_editor.connection.alias).filter(
        app_label="organizations"
    ).delete()


class Migration(migrations.Migration):
    """Drop the tables, migration records and content types of the removed
    organizations app.

    The reverse is a no-op: the app and its models no longer exist, so there is
    nothing to recreate.
    """

    dependencies = [
        ("core", "0001_enable_pgvector"),
        ("contenttypes", "0002_remove_content_type_name"),
        ("auth", "0012_alter_user_first_name_max_length"),
        ("admin", "0003_logentry_add_action_flag_choices"),
        ("accounts", "0003_user_llm_config"),
    ]

    operations = [
        migrations.RunSQL(sql=DROP_TABLES, reverse_sql=migrations.RunSQL.noop),
        migrations.RunPython(remove_content_types, migrations.RunPython.noop),
    ]

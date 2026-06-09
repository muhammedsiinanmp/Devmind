from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("reviews", "0003_review_indexes"),
    ]

    operations = [
        migrations.AddField(
            model_name="reviewrun",
            name="diff_text",
            field=models.TextField(
                blank=True,
                default="",
                help_text="Raw unified diff stored at review time to avoid re-fetching from GitHub.",
            ),
        ),
    ]

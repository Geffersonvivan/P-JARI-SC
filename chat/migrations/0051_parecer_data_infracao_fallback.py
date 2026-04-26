from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0050_audit_event'),
    ]

    operations = [
        migrations.AddField(
            model_name='parecer',
            name='data_infracao_fallback',
            field=models.BooleanField(default=False),
        ),
    ]

# Generated manually 2026-03-28 — Bug 1/2 fix: tipo_penalidade + data_conclusao_multa

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0041_add_julgador_fields_parecer'),
    ]

    operations = [
        migrations.AddField(
            model_name='parecer',
            name='tipo_penalidade',
            field=models.CharField(blank=True, max_length=20, null=True),
        ),
        migrations.AddField(
            model_name='parecer',
            name='data_conclusao_multa',
            field=models.DateField(blank=True, null=True),
        ),
    ]

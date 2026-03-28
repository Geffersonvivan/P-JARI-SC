# Generated manually 2026-03-28 — Fase 1 auto-preenchimento

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0043_parecer_tem_flagrante_data_conhecimento'),
    ]

    operations = [
        migrations.AddField(
            model_name='parecer',
            name='fase1_extracao_json',
            field=models.JSONField(blank=True, null=True),
        ),
    ]

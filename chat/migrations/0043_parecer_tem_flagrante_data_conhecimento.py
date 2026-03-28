# Generated manually 2026-03-28 — Bug: FILTRO 3 multa com/sem flagrante (art. 282 §6º-A CTB)

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0042_parecer_tipo_penalidade_data_conclusao_multa'),
    ]

    operations = [
        migrations.AddField(
            model_name='parecer',
            name='tem_flagrante',
            field=models.BooleanField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='parecer',
            name='data_conhecimento_infracao',
            field=models.DateField(blank=True, null=True),
        ),
    ]

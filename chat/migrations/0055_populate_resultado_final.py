"""Data migration: popula resultado_final para pareceres existentes."""
from django.db import migrations


def populate_resultado_final(apps, schema_editor):
    Parecer = apps.get_model('chat', 'Parecer')
    # Atualiza em batch para não travar o banco
    # INDEFERIDO
    Parecer.objects.filter(
        parecer_final__icontains='INDEFERID',
        resultado_final__isnull=True,
    ).update(resultado_final='INDEFERIDO')
    # DEFERIDO (tudo que tem parecer_final mas não é indeferido)
    Parecer.objects.filter(
        resultado_final__isnull=True,
    ).exclude(
        parecer_final__isnull=True,
    ).exclude(
        parecer_final__exact='',
    ).update(resultado_final='DEFERIDO')


class Migration(migrations.Migration):
    dependencies = [
        ('chat', '0054_add_parecer_resultado_final'),
    ]

    operations = [
        migrations.RunPython(populate_resultado_final, migrations.RunPython.noop),
    ]

from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0049_add_subscription_model_and_profile_dates'),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name='AuditEvent',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('timestamp', models.DateTimeField(auto_now_add=True, db_index=True)),
                ('evento', models.CharField(
                    choices=[
                        ('fase_concluida',          'Fase Concluída'),
                        ('fase_erro',               'Erro de Fase'),
                        ('parecer_finalizado',      'Parecer Finalizado'),
                        ('filtro_bloqueado',        'Filtro Bloqueado (Admissibilidade)'),
                        ('admissibilidade_decisao', 'Decisão de Admissibilidade'),
                        ('blindagem_score',         'Score de Blindagem Registrado'),
                        ('credito_consumido',       'Crédito Consumido'),
                        ('upload_documentos',       'Upload de Documentos'),
                    ],
                    db_index=True,
                    max_length=60,
                )),
                ('fase', models.IntegerField(blank=True, null=True)),
                ('dados', models.JSONField(blank=True, default=dict)),
                ('user', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_events',
                    to=settings.AUTH_USER_MODEL,
                )),
                ('parecer', models.ForeignKey(
                    blank=True, null=True,
                    on_delete=django.db.models.deletion.SET_NULL,
                    related_name='audit_events',
                    to='chat.parecer',
                )),
            ],
            options={
                'ordering': ['-timestamp'],
                'indexes': [
                    models.Index(fields=['evento', 'timestamp'], name='audit_evento_ts_idx'),
                    models.Index(fields=['user', 'timestamp'], name='audit_user_ts_idx'),
                ],
            },
        ),
    ]

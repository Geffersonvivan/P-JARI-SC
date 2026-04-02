# Generated manually on 2026-04-02

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0047_add_data_totalizacao_pontos'),
    ]

    operations = [
        # Índice em status_fase — usado em filtros frequentes (Celery, dashboard, home)
        migrations.AlterField(
            model_name='parecer',
            name='status_fase',
            field=models.IntegerField(default=1, db_index=True),
        ),
        # Remove campo MercadoPago não utilizado (sistema migrou para Stripe).
        # Usa SeparateDatabaseAndState + DROP COLUMN IF EXISTS para ser idempotente:
        # se a coluna já foi removida manualmente no DB de produção, a migration não falha.
        migrations.SeparateDatabaseAndState(
            database_operations=[
                migrations.RunSQL(
                    sql="ALTER TABLE chat_userprofile DROP COLUMN IF EXISTS mp_customer_id",
                    reverse_sql="ALTER TABLE chat_userprofile ADD COLUMN mp_customer_id VARCHAR(255)",
                ),
            ],
            state_operations=[
                migrations.RemoveField(
                    model_name='userprofile',
                    name='mp_customer_id',
                ),
            ],
        ),
    ]

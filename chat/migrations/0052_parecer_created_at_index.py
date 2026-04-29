from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0051_parecer_data_infracao_fallback'),
    ]

    operations = [
        migrations.AlterField(
            model_name='parecer',
            name='created_at',
            field=models.DateTimeField(auto_now_add=True, db_index=True),
        ),
    ]

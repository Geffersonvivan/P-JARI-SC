from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('chat', '0038_parecer_feedback_notes_parecer_feedback_score_and_more'),
    ]

    operations = [
        migrations.AlterField(
            model_name='parecer',
            name='autuacao_pdf_path',
            field=models.FileField(blank=True, max_length=500, null=True, upload_to='uploads/'),
        ),
        migrations.AlterField(
            model_name='parecer',
            name='consolidado_pdf_path',
            field=models.FileField(blank=True, max_length=500, null=True, upload_to='uploads/'),
        ),
        migrations.AlterField(
            model_name='parecer',
            name='ata_pdf_path',
            field=models.FileField(blank=True, max_length=500, null=True, upload_to='uploads/'),
        ),
    ]

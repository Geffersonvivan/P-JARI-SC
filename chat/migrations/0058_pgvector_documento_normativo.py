from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ("chat", "0057_add_cag_fields"),
    ]

    operations = [
        migrations.CreateModel(
            name="DocumentoNormativo",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("nome_arquivo", models.CharField(db_index=True, max_length=255)),
                ("titulo", models.CharField(blank=True, max_length=500)),
                ("chunk_index", models.IntegerField()),
                ("pagina_inicio", models.IntegerField(default=0)),
                ("pagina_fim", models.IntegerField(default=0)),
                ("texto", models.TextField()),
                ("embedding", models.JSONField(default=list, help_text="Vetor 768d (text-embedding-004)")),
                ("indexado_em", models.DateTimeField(auto_now=True)),
            ],
            options={
                "verbose_name": "Documento Normativo (RAG)",
                "verbose_name_plural": "Documentos Normativos (RAG)",
                "unique_together": {("nome_arquivo", "chunk_index")},
            },
        ),
    ]

import os
import django
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from chat.models import AiRequestLog, Parecer, User

try:
    user = User.objects.first()
    parecer = Parecer.objects.filter(user=user).first()
    
    # Perplexity fake logs for latency
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Perplexity', fase='Jurisprudência', input_tokens=100, output_tokens=200, latency_ms=2350, model_name='sonar-pro')
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Perplexity', fase='Jurisprudência', input_tokens=150, output_tokens=300, latency_ms=812, model_name='sonar-pro')
    
    # Gemini Dispension
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Refinamento', input_tokens=500, output_tokens=150, latency_ms=1200, model_name='gemini-2.5-flash', is_pdf_defect=False)
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Refinamento', input_tokens=800, output_tokens=200, latency_ms=1300, model_name='gemini-2.5-flash', is_pdf_defect=False)
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Análise Mérito', input_tokens=1500, output_tokens=600, latency_ms=3500, model_name='gemini-2.5-pro', is_pdf_defect=False)
    
    # Context Fatigue
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Análise Mérito', input_tokens=254000, output_tokens=400, latency_ms=8000, model_name='gemini-2.5-pro', is_pdf_defect=False)
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Análise Mérito', input_tokens=180500, output_tokens=350, latency_ms=7500, model_name='gemini-2.5-pro', is_pdf_defect=False)
    
    # OCR Defect
    AiRequestLog.objects.create(parecer_referencia=parecer, user=user, provider='Gemini', fase='Fase 2 (DIR)', input_tokens=200, output_tokens=50, latency_ms=800, model_name='gemini-2.5-flash', is_pdf_defect=True)
    
    print("Advanced fakes created successfully.")
except Exception as e:
    print(f"Error: {e}")

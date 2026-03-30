
        let _onboardingDismissed = false;
        function dismissOnboarding() {
            if (_onboardingDismissed) return;
            _onboardingDismissed = true;
            const modal = document.getElementById('onboarding-modal');
            if (modal) {
                modal.style.opacity = '0';
                modal.style.transition = 'opacity 0.3s ease';
                setTimeout(() => modal.remove(), 300);
            }
            fetch("{% url 'dismiss_onboarding' %}", {
                method: 'POST',
                headers: {
                    'X-CSRFToken': '{{ csrf_token }}',
                    'Content-Type': 'application/json'
                }
            }).then(r => { if (!r.ok) console.warn('dismiss_onboarding falhou:', r.status); })
              .catch(console.error);
        }
    
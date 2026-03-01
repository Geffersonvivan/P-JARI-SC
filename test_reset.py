from django.test import Client
c = Client()
try:
    response = c.post('/accounts/password/reset/', {'email': 'geffersonvivan@gmail.com'})
    print(f"Status: {response.status_code}")
    print(response.content.decode('utf-8')[:500])
except Exception as e:
    import traceback
    traceback.print_exc()

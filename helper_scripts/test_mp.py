import mercadopago
sdk = mercadopago.SDK("APP_USR-7609649349925403-022422-2216c80bdf86d7bd7174409c618cf470-3225133655")
preference_data = {
    "items": [
        {
            "title": "P-JARI/SC Básico (40 Pareceres)",
            "description": "Créditos de sistema",
            "quantity": 1,
            "currency_id": "BRL",
            "unit_price": 720.0
        }
    ],
    "payer": {
        "name": "Cliente",
        "surname": "Teste",
        "email": "test_user_pjari_999@gmail.com"
    },
    "back_urls": {
        "success": "https://pjarisc.com.br/planos/?success=1",
        "failure": "https://pjarisc.com.br/planos/?failure=1",
        "pending": "https://pjarisc.com.br/planos/?pending=1"
    },
    "external_reference": "1"
}
request_options = mercadopago.config.RequestOptions()
request_options.custom_headers = {
    'x-integrator-id': 'dev_24c65fb163bf11ea96500242ac130004' 
}
res = sdk.preference().create(preference_data, request_options)
print(res)

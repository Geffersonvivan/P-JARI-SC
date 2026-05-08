import mercadopago
sdk = mercadopago.SDK("APP_USR-TEST-000000")
preference_data = {
    "items": [{"title": "Teste", "quantity": 1, "currency_id": "BRL", "unit_price": 540.0}]
}
res = sdk.preference().create(preference_data)
print(res)

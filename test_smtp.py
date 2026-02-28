import smtplib
import ssl
import sys

try:
    context = ssl.create_default_context()
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, context=context) as server:
        server.login("pjarisc@gmail.com", "gvgv@2020X")
        print("Success")
except Exception as e:
    print(f"Error: {e}")
    sys.exit(1)

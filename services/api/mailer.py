import os
import requests

RESEND_API_KEY = os.getenv("RESEND_API_KEY")
RESEND_FROM_EMAIL = os.getenv("RESEND_FROM_EMAIL", os.getenv("SMTP_USERNAME"))

def send_campaign(to_email: str, subject: str, content: str, from_name: str = "ALX Scales"):
    """
    Send an email using Resend's HTTP API instead of SMTP.
    """
    if not RESEND_API_KEY:
        print("RESEND: RESEND_API_KEY is not set, skipping send.")
        return

    from_email = RESEND_FROM_EMAIL or "no-reply@example.com"
    frm = f"{from_name} <{from_email}>"

    print("RESEND: preparing to send to", to_email)

    url = "https://api.resend.com/emails"
    headers = {
        "Authorization": f"Bearer {RESEND_API_KEY}",
        "Content-Type": "application/json",
    }
    data = {
        "from": frm,
        "to": [to_email],
        "subject": subject,
        "text": content,
    }

    try:
        resp = requests.post(url, headers=headers, json=data, timeout=10)
        if 200 <= resp.status_code < 300:
            print("RESEND: email sent successfully to", to_email)
        else:
            print("RESEND ERROR:", resp.status_code, resp.text)
    except Exception as e:
        print("RESEND EXCEPTION:", type(e).__name__, e)

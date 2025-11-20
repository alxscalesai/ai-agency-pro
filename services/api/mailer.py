import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import os

def send_campaign(to_email: str, subject: str, content: str, from_name: str = "ALX Scales"):
    msg = MIMEText(content, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, os.getenv("SMTP_USERNAME")))
    msg["To"] = to_email

    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
        server.starttls()
        server.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
        server.send_message(msg)
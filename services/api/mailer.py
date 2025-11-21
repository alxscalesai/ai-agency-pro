import smtplib
from email.mime.text import MIMEText
from email.utils import formataddr
import os

def send_campaign(to_email: str, subject: str, content: str, from_name: str = "ALX Scales"):
    print("SMTP: preparing to send to", to_email)
    msg = MIMEText(content, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"] = formataddr((from_name, os.getenv("SMTP_USERNAME")))
    msg["To"] = to_email

    with smtplib.SMTP(os.getenv("SMTP_SERVER"), int(os.getenv("SMTP_PORT"))) as server:
        print("SMTP: connecting to server", os.getenv("SMTP_SERVER"), os.getenv("SMTP_PORT"))
        server.starttls()
        print("SMTP: starting TLS")
        server.login(os.getenv("SMTP_USERNAME"), os.getenv("SMTP_PASSWORD"))
        print("SMTP: logged in as", os.getenv("SMTP_USERNAME"))
        server.send_message(msg)
        print("SMTP: message sent to", to_email)

"""Send ticket emails to human agents.   Owner: M4

Uses Gmail SMTP by default (free). If credentials are missing OR the app is
running in mock mode, the email is logged instead of sent — so tests and the
demo never break.
"""
import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from dotenv import load_dotenv
load_dotenv()

SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER", "").strip()
SMTP_PASS = os.getenv("SMTP_PASS", "").strip()
EMAIL_ENABLED = bool(SMTP_USER and SMTP_PASS)


def send_ticket_email(ticket_id: str, summary: dict, priority: str,
                      to_name: str, to_email: str) -> bool:
    """Send the ticket to the assigned human agent.

    Returns True if the email was sent, False if it was logged only.
    Never raises — a missing SMTP config or a down mail server must not break
    the escalation flow.
    """
    subject = f"[TeleCare] New {priority.upper()} ticket {ticket_id}"
    body = (
        f"Hi {to_name},\n\n"
        f"A new ticket has been assigned to you.\n\n"
        f"Ticket ID : {ticket_id}\n"
        f"Priority  : {priority}\n"
        f"Customer  : {summary.get('customer_mood', 'unknown')} mood\n"
        f"Issue     : {summary.get('issue', 'No issue provided')}\n"
        f"Tried     : {summary.get('what_was_tried', 'N/A')}\n\n"
        f"Please contact the customer within 24 hours.\n\n"
        f"— TeleCare AI Supervisor Agent"
    )

    if not EMAIL_ENABLED:
        # Mock mode: log instead of sending
        print(f"[notifier:MOCK] -> {to_email} | {subject}\n{body}\n")
        return False

    try:
        msg = MIMEMultipart()
        msg["From"] = SMTP_USER
        msg["To"] = to_email
        msg["Subject"] = subject
        msg.attach(MIMEText(body, "plain"))

        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
            server.starttls()
            server.login(SMTP_USER, SMTP_PASS)
            server.send_message(msg)
        return True
    except Exception as e:
        print(f"[notifier:ERROR] failed to send to {to_email}: {e}")
        return False
"""
direct_email_service.py
-----------------------
Send emails directly to faculty members by resolving their name via DB.
"""

import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from src.utils.config_loader import Config
from src.utils.user_resolver import resolve_faculty_member


class DirectEmailService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = Config.SENDER_EMAIL
        self.sender_password = Config.SENDER_PASSWORD

    def send_email(self, target_name: str, subject: str, message_body: str) -> dict:
        """
        Resolve a faculty member's name to an email address and send them an email.

        Parameters
        ----------
        target_name  : str — display name (fuzzy matched against DB)
        subject      : str
        message_body : str — plain text body

        Returns dict with success bool.
        """
        recipient = resolve_faculty_member(target_name)

        if not recipient:
            return {
                "success": False,
                "error": f"Could not find anyone named '{target_name}' in the database",
            }

        recipient_email = recipient["email"]
        recipient_name = recipient["name"]

        try:
            msg = MIMEMultipart()
            msg["From"] = self.sender_email
            msg["To"] = recipient_email
            msg["Subject"] = subject
            msg.attach(MIMEText(message_body, "plain"))

            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, msg.as_string())

            return {
                "success": True,
                "recipient_name": recipient_name,
                "recipient_email": recipient_email,
            }

        except Exception as e:
            return {"success": False, "error": str(e)}

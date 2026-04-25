import os
import smtplib
from datetime import datetime
from email.message import EmailMessage

from jinja2 import Template

from src.utils.config_loader import Config


def send_meeting_notification(
    recipient_email: str,
    notification_type: str,
    meeting_details: dict,
    ics_attachment: str = None,
    recipient_phone: str = None,
) -> dict:
    """
    Send an HTML email notification for a meeting event.

    Parameters
    ----------
    recipient_email : str
    notification_type : str — one of "invite", "update", "cancel"
    meeting_details : dict
        {
            "title": str,
            "start": ISO datetime string,
            "end":   ISO datetime string,
            "link":  Google Meet URL,
            "organizer": str
        }
    ics_attachment : str (optional) — path to a .ics file

    Returns dict with "success" bool.
    """

    sender_email = Config.SENDER_EMAIL
    sender_password = Config.SENDER_PASSWORD

    if not sender_email or not sender_password:
        return {"success": False, "error": "Missing SENDER_EMAIL or SENDER_PASSWORD in config"}

    # Map notification type to template file and subject
    type_map = {
        "invite": ("templates/email_invite.html", f"Meeting Invitation: {meeting_details.get('title', 'Meeting')}"),
        "update": ("templates/email_update.html", f"Meeting Updated: {meeting_details.get('title', 'Meeting')}"),
        "cancel": ("templates/email_cancel.html", f"Meeting Cancelled: {meeting_details.get('title', 'Meeting')}"),
    }

    if notification_type not in type_map:
        return {"success": False, "error": "Invalid notification_type. Must be invite/update/cancel"}

    template_path, subject = type_map[notification_type]

    if not os.path.exists(template_path):
        return {"success": False, "error": f"Template file not found: {template_path}"}

    try:
        # Render Jinja2 template
        with open(template_path, "r", encoding="utf-8") as f:
            html_template = f.read()

        render_data = meeting_details.copy()
        if "time_str" not in render_data:
            render_data["time_str"] = f"{meeting_details.get('start', '')} to {meeting_details.get('end', '')}"
        if "location" not in render_data:
            render_data["location"] = meeting_details.get("link", "N/A")
        if "agenda" not in render_data:
            render_data["agenda"] = "N/A"

        html_body = Template(html_template).render(**render_data)

        # Build EmailMessage
        msg = EmailMessage()
        msg["From"] = sender_email
        msg["To"] = recipient_email
        msg["Subject"] = subject
        msg.set_content("Meeting notification (HTML-capable email client recommended).")
        msg.add_alternative(html_body, subtype="html")

        # Attach .ics if provided
        if ics_attachment:
            if not os.path.exists(ics_attachment):
                return {"success": False, "error": f"ICS file not found: {ics_attachment}"}
            with open(ics_attachment, "rb") as f:
                msg.add_attachment(
                    f.read(),
                    maintype="text",
                    subtype="calendar",
                    filename=os.path.basename(ics_attachment),
                )

        # Send
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(sender_email, sender_password)
            server.send_message(msg)

        # Optional WhatsApp echo — fire-and-forget queue.
        whatsapp_status = None
        if recipient_phone:
            try:
                from src.services.whatsapp_queue import queue_whatsapp
                wa_body = (
                    f"{subject}\n\n"
                    f"When: {meeting_details.get('start', '')}–{meeting_details.get('end', '')}\n"
                    f"Where: {meeting_details.get('link') or meeting_details.get('location') or 'TBD'}\n"
                    f"Organizer: {meeting_details.get('organizer', '')}"
                )
                queue_whatsapp(recipient_phone, wa_body,
                               metadata={"channel": "meeting_notification",
                                         "type": notification_type})
                whatsapp_status = "queued"
            except Exception as e:
                whatsapp_status = f"failed: {e}"

        return {
            "success": True,
            "recipient": recipient_email,
            "notification_type": notification_type,
            "sent_at": datetime.utcnow().isoformat(),
            "whatsapp": whatsapp_status,
        }

    except smtplib.SMTPAuthenticationError:
        return {"success": False, "error": "SMTP authentication failed"}
    except smtplib.SMTPException as e:
        return {"success": False, "error": f"SMTP error: {str(e)}"}
    except Exception as e:
        return {"success": False, "error": str(e)}

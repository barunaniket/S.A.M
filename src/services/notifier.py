import smtplib
import os
from email.message import EmailMessage
from jinja2 import Template

def send_meeting_email(recipient_email, meeting_details):
    """
    Sends an HTML meeting invitation via SMTP[cite: 91, 93].
    """
    sender_email = os.getenv("SENDER_EMAIL")
    sender_password = os.getenv("SENDER_PASSWORD") # Use an App Password for Gmail [cite: 129, 324]

    # 1. Create the Email Message
    msg = EmailMessage()
    msg['Subject'] = f"Meeting Invitation: {meeting_details['title']}"
    msg['From'] = sender_email
    msg['To'] = recipient_email

    # 2. Define the HTML Template [cite: 93, 157]
    html_template = """
    <html>
        <body>
            <h2>Hello, you have been invited to a meeting!</h2>
            <p><strong>Topic:</strong> {{ title }}</p>
            <p><strong>Time:</strong> {{ start_time }}</p>
            <p><strong>Link:</strong> <a href="{{ link }}">Join Google Meet</a></p>
        </body>
    </html>
    """
    
    # 3. Render Template with Data
    template = Template(html_template)
    content = template.render(
        title=meeting_details['title'],
        start_time=meeting_details['start'],
        link=meeting_details['link']
    )
    msg.set_content(content, subtype='html')

    # 4. Send the Email [cite: 129, 156]
    try:
        with smtplib.SMTP_SSL('smtp.gmail.com', 465) as smtp:
            smtp.login(sender_email, sender_password)
            smtp.send_message(msg)
            print(f"Notification sent to {recipient_email}")
            return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
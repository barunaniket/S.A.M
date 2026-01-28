'''
This file is used to send emails directly to the
people using the send_email(self, target_name, subject, message_body)
'''

import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from utils.config_loader import Config
from utils.user_resolver import resolve_faculty_member

class DirectEmailService:
    def __init__(self):
        self.smtp_server = "smtp.gmail.com"
        self.smtp_port = 587
        self.sender_email = Config.SENDER_EMAIL
        self.sender_password = Config.SENDER_PASSWORD

    def send_email(self, target_name, subject, message_body):
        """
        1. Resolves the name to an email using your existing utils.
        2. Sends a direct text/HTML email.
        """
        print(f"🔍 Searching for details on: '{target_name}'...")
        
        # REUSE: Using your existing resolver to fetch DB info
        recipient = resolve_faculty_member(target_name)
        
        if not recipient:
            print(f"❌ Error: Could not find anyone named '{target_name}' in the database.")
            return False

        recipient_email = recipient['email']
        recipient_name = recipient['name']
        
        print(f"✅ Found: {recipient_name} <{recipient_email}>")
        print(f"📨 Sending email...")

        try:
            # Construct the email
            msg = MIMEMultipart()
            msg['From'] = self.sender_email
            msg['To'] = recipient_email
            msg['Subject'] = subject

            # Attach body (Plain text or HTML)
            msg.attach(MIMEText(message_body, 'plain'))

            # Send via SMTP
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.sender_email, self.sender_password)
                server.sendmail(self.sender_email, recipient_email, msg.as_string())

            print(f"🚀 Email successfully sent to {recipient_name}!")
            return True

        except Exception as e:
            print(f"❌ Failed to send email: {e}")
            return False
        
'''
how to use this service?
ye service basically direct email bhejne ke liye hai without calendar invite stuff.
DB se banda dhoondhega aur seedha email bhej dega.

from services.direct_email_service import DirectEmailService # pehle import kar lo

email_service = DirectEmailService() # service initialize karo

# bas naam aur details pass kardo
# ye khud fuzzy match karke sahi bande ko dhoondh lega DB se
target_name = "Ayush" 
subject = "Urgent Meeting"
body = "Bhai kal meeting hai, time pe aana."

success = email_service.send_email(target_name, subject, body)

if success:
    print("Email chala gaya!")
else:
    print("Chud gye guru")
'''
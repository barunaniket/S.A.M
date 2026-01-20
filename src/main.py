import os
from dotenv import load_dotenv
from utils.google_auth import get_calendar_service
import click
from services.notifier import send_meeting_email

load_dotenv()


@click.group()
def cli():
    """S.A.M. (Smart Administrative Messenger) CLI Test"""
    pass

@cli.command()
@click.option('--to', required=True, help='Recipient email address')
@click.option('--subject', default='Test Meeting', help='Meeting title')
def test_mail(to, subject):
    """Sends a test invitation email."""
    meeting_details = {
        'title': subject,
        'start': '2025-01-25 at 3:00 PM',
        'link': 'https://meet.google.com/test-link'
    }
    
    click.echo(f"Attempting to send test email to {to}...")
    success = send_meeting_email(to, meeting_details)
    
    if success:
        click.echo("Success! Check your inbox.")
    else:
        click.echo("Failed to send email. Check your SMTP settings and .env file.")

if __name__ == '__main__':
    cli()
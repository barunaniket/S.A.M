import sys
import os

# 1. Add 'src' to path so we can import modules from the parent directory
# This mimics the setup in tests/test_resolver.py
sys.path.append(os.path.join(os.path.dirname(__file__), '../src'))

from services.direct_email_service import DirectEmailService

def test_email_sending():
    print("--- Testing Direct Email Service ---")
    
    # Initialize the service
    # This will load credentials from your .env file automatically via Config
    email_service = DirectEmailService()
    
    # INPUT: Ask for a name that exists in your DB (e.g., 'Aniket', 'Ayush')
    target_name = input("Enter the name of the faculty to email (fuzzy match): ")
    
    subject = "Test Email from S.A.M Test Script"
    body = f"""
    Hello,
    
    This is a test email sent specifically to verify the DirectEmailService functionality.
    
    Timestamp: {os.times()}
    
    Regards,
    S.A.M Dev Team
    """
    
    print(f"\nAttempting to send email to '{target_name}'...")
    
    # Call the function
    success = email_service.send_email(target_name, subject, body)
    
    print("\n--- Result ---")
    if success:
        print("✅ Test PASSED: Email sent successfully.")
    else:
        print("❌ Test FAILED: Email could not be sent. Check logs above.")

if __name__ == "__main__":
    # Ensure .env is loaded (DirectEmailService imports Config which loads it)
    try:
        test_email_sending()
    except KeyboardInterrupt:
        print("\nTest cancelled.")
    except Exception as e:
        print(f"\nAn error occurred: {e}")
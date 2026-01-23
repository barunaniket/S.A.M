'''
agar kissi koo janna hai ki kya karta hai yea file.
toh yea basically ek loader and validator dono sath me hai.
bar bar iss code ko manually har ek service me load krne kee jagah 
directly iss module koo import kr lenge
'''

import os
import sys
from dotenv import load_dotenv

#turrant load kr liyae environment vars .env se
load_dotenv()

#define kr diyae kaunsa keys koo use krna hai
REQUIRED_KEYS = [
    "GOOGLE_CLIENT_ID",
    "GOOGLE_CLIENT_SECRET",
    "GOOGLE_PROJECT_ID",
    "GOOGLE_API_SCOPES",
    "SENDER_EMAIL",
    "SENDER_PASSWORD"
]

class Config:
    """
    Central configuration class.
    Access variables like: Config.GOOGLE_CLIENT_ID
    """
    
    # Google API Credentials
    GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
    GOOGLE_CLIENT_SECRET = os.getenv("GOOGLE_CLIENT_SECRET")
    GOOGLE_PROJECT_ID = os.getenv("GOOGLE_PROJECT_ID")
    
    # Scopes need to be split into a list if they are space-separated string
    _scopes_str = os.getenv("GOOGLE_API_SCOPES", "")
    GOOGLE_API_SCOPES = _scopes_str.split(" ") if _scopes_str else []

    # Email Credentials
    SENDER_EMAIL = os.getenv("SENDER_EMAIL")
    SENDER_PASSWORD = os.getenv("SENDER_PASSWORD")

    @classmethod
    def validate(cls):
        """
        Checks if all required environment variables are set.
        Raises an error if any are missing.
        """
        missing_keys = []
        for key in REQUIRED_KEYS:
            if not os.getenv(key):
                missing_keys.append(key)
        
        if missing_keys:
            print(f"CRITICAL ERROR: Missing configuration keys in .env: {', '.join(missing_keys)}")
            print("Please update your .env file with the correct credentials.")
            sys.exit(1)

#validation is necessary agar hamlog koo creds verify karna hai toh
Config.validate()


'''
kaise iss config koo use krna hai is below

from utils.config_loader import Config #pehele import kiya module koo

def send_meeting_email(to_email, details):
    sender = Config.SENDER_EMAIL #and simply config kee thru use kr liya
    password = Config.SENDER_PASSWORD
    # ... rest of code
'''
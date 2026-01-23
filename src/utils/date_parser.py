'''
iss file kee need kishan bhai koo pta hai kyu hai
peechli baar dates koo handle krne me bhaut issues aaye the
so basically agar ham bolenge ki tomorrow toh apne local time zone 
jisme hamlog hai uske hee hisab se vo date extract krke dega
so problem nahi hogi
'''

from datetime import datetime, timedelta
from dateutil import parser

def parse_iso_from_llm(time_string):
    """
    Validates and converts the date string received from Gemini API.
    
    Why this is needed:
    Gemini might return "2025-01-25 15:00" or "Jan 25, 2025 3pm".
    This function standardizes ANY format into a Python datetime object.
    """
    try:
        dt_object = parser.parse(time_string)
        return dt_object
    except (ValueError, TypeError):
        print(f"Error: Gemini returned an invalid date format: '{time_string}'")
        return None

def calculate_end_time(start_dt, duration_minutes=60):
    """
    Calculates the meeting end time.
    Required because Google Calendar needs both a Start and End time.
    """
    return start_dt + timedelta(minutes=duration_minutes)

def format_for_google(dt_object):
    """
    Final step: Converts the python object to the strict string Google API demands.
    Output: '2025-01-25T15:00:00'
    """
    if dt_object:
        return dt_object.isoformat()
    return None

"""
how to use this?
btw note : isko tumlog shayad hee directly use kroge. but still.

from utils.date_parser import parse_iso_from_llm, format_for_google, calculate_end_time #import kro pehele

llm_response = "January 25, 2025 at 3 PM" #man loo ki AI ne yea response diya

start_dt = parse_iso_from_llm(llm_response) #parser wagerah kee madad se krlo
end_dt = calculate_end_time(start_dt, duration_minutes=60)

google_start = format_for_google(start_dt) #phir format kr lena
google_end = format_for_google(end_dt)

print(f"Ready for API: Start={google_start}, End={google_end}")
"""
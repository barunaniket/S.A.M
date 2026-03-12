from utils.db_handler import get_faculty_by_id
from utils.config_loader import get_llm_client
from utils.config_loader import  sanitize_text

class LLMhandler:
    def __init__(self):
        self.llm_client = get_llm_client()


    def generate_context_aware_student_mail(self,student_mail_body:str,faculty_id:int)->dict:
        faculty_profile = get_faculty_by_id(faculty_id)
        if not faculty_profile :
            raise ValueError("Faculty not found")

        faculty_name = faculty_profile["name"]
        tone = faculty_profile.get("tone","formal")
        office_hours = faculty_profile.get("office_hours","")
        signature = faculty_profile.get("signature",faculty_name)

        clean_mail_body = sanitize_text(student_mail_body)

        system_prompt =  (
            f"You are replying as {faculty_name},a university.\n"
            f"Use a {tone} tone .\n"

        )

        if office_hours:
            system_prompt +=(f"Your office hours are {office_hours}.\n")

        system_prompt+=(
            "write a polite and helpful email reply to the student.\n"
            "end the email with the following signature.\n"
            f"{signature}"
        )

        llm_response = self.llm_client.generate(
            system_prompt=system_prompt,
            user_prompt=clean_mail_body
        )


        response = {
            "subject":"Re:student inquiry",
            "body": llm_response.strip(),
            "metadata":{
                "faculty_id":faculty_id,
                "tone":tone
            }

        }


        return response








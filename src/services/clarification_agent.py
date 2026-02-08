# clarification_agent.py
# Proactive Questions Agent (Ayush)

def get_clarification(missing_fields: list, context: dict) -> str:
    """
    Generates targeted clarification questions for missing meeting details.
    """

    # Predefined question templates (constant memory, fast lookup)
    FIELD_QUESTIONS = {
        "date": "On which date should I schedule the meeting?",
        "time": "What time should the meeting start?",
        "duration": "How long should the meeting be?",
        "participants": "Who should I invite to the meeting?"
    }

    questions = []

    # 1️⃣ Generate questions for missing fields
    for field in missing_fields:
        question = FIELD_QUESTIONS.get(field)
        if question:
            questions.append(question)

    # 2️⃣ Handle ambiguous participant names
    ambiguous = context.get("ambiguous_person")
    if ambiguous:
        name = ambiguous["name"]
        options = ambiguous["options"]

        # Build ambiguity question efficiently
        lines = [
            f"I found multiple people named '{name}'. Which one did you mean?"
        ]
        lines.extend(
            f"{i}) {option}" for i, option in enumerate(options, 1)
        )

        questions.append("\n".join(lines))

    # 3️⃣ Return combined clarification prompt
    return "\n".join(questions)

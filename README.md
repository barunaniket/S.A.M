# S.A.M – Smart Administrative Messenger

**Automating the Link Between Faculty Data and Scheduling**

S.A.M (Smart Administrative Messenger) is an intelligent, agentic AI system designed to automate meeting coordination and administrative scheduling in educational institutions using natural language interactions.

---

## 🚀 Overview

Educational institutions face significant overhead in coordinating meetings due to manual communication, scheduling conflicts, and lack of centralized tracking. **S.A.M** addresses these challenges by enabling users to create, manage, and track meetings using natural language while automatically handling participant resolution, conflict detection, calendar updates, and notifications.

The system is initially implemented as a **Python CLI application** powered by **Google Gemini API**, with planned expansion into WhatsApp, Telegram, and a web-based interface.

---

## 🎯 Key Features

* Natural language meeting creation (text-based)
* Automatic participant identification from faculty database
* Google Calendar integration with conflict detection
* Smart conflict resolution with alternative time suggestions
* Email notifications with `.ics` calendar attachments
* Meeting rescheduling and cancellation
* Attendance and response tracking
* Centralized logging and audit trail
* Modular, agent-based architecture for future expansion

---

## 🧠 How It Works (High-Level Flow)

1. User enters a natural language command
2. LLM parses intent, date, time, and participants
3. Faculty members are resolved using fuzzy matching
4. Google Calendar is checked for conflicts
5. Conflicts are classified and resolved if needed
6. Calendar events are created/updated
7. Email notifications are sent
8. All actions are logged for tracking and reporting

---

## 🏗️ System Architecture

**Multi-Layer Architecture:**

* **Layer 1:** User Interaction (CLI → WhatsApp/Telegram → Web UI)
* **Layer 2:** Agent Orchestration (LLM reasoning & planning)
* **Layer 3:** Business Logic (Parsing, Resolution, Conflict Detection)
* **Layer 4:** Integrations (Google Calendar, Email, Messaging APIs)
* **Layer 5:** Data Layer (Faculty DB, Meetings, Logs)

---

## 🛠️ Technology Stack

### Phase 1 – CLI Prototype

* **Language:** Python 3.10+
* **LLM:** Google Gemini API
* **Date Parsing:** `dateparser`, `python-dateutil`
* **Database:** CSV → SQLite
* **Calendar:** Google Calendar API
* **Email:** Gmail SMTP
* **CLI:** `click` / `argparse`
* **Testing:** `pytest`

### Future Phases

* **Workflow Automation:** n8n
* **Messaging:** WhatsApp Business API, Telegram Bot API
* **Backend:** FastAPI / Django REST
* **Frontend:** React + Tailwind CSS
* **Database:** PostgreSQL

---

## 📦 Database Schema (Core)

* **Faculty**
* **Meetings**
* **Meeting Participants**
* **Reminders**
* **Activity Logs**

Each meeting maintains full lifecycle tracking including responses, notifications, and status.

---

## 🧪 Testing Strategy

* **Unit Tests:** NLP parsing, date extraction, conflict detection
* **Integration Tests:** Full workflow (input → calendar → email)
* **System Tests:** Real-world scheduling scenarios
* **Performance Target:** < 3 seconds per request
* **Accuracy Targets:**

  * ≥95% participant identification
  * ≥90% conflict detection

---

## ⏱️ Expected Impact

* ⏳ **70–80% reduction** in coordination time
* ✅ **95%+ accuracy** in scheduling
* ⚠️ **90% conflict prevention** before meetings are created
* 📩 **99% email delivery success rate**

---

## 💻 CLI Usage Examples

```bash
# Create a meeting
sam create "Meeting on Jan 25 at 3 PM with Dr. Sharma and Prof. Kumar"

# List upcoming meetings
sam list --days 7

# Reschedule a meeting
sam reschedule <meeting_id> --date "Jun 26" --time "4 PM"

# Cancel a meeting
sam cancel <meeting_id>

# View meeting details
sam show <meeting_id>

# Add participant
sam add-participant <meeting_id> --name "Dr. Singh"
```

---

## 🔐 Requirements

### Software

* Python 3.10+
* SQLite 3.x
* Google Cloud Project (Calendar API enabled)
* Gmail account or institutional SMTP
* n8n (Phase 2+)

### API Keys

* Google Gemini API Key
* Google Calendar OAuth Credentials
* Gmail SMTP Credentials
* Twilio (WhatsApp – Phase 3)
* Telegram Bot Token (Phase 3)

---

## 🧩 Future Enhancements

* Voice input (Speech-to-Text)
* Web dashboard for meeting management
* Multi-language support
* AI-generated agendas
* Sentiment analysis of meeting feedback
* LMS & Zoom/Teams integration
* Predictive scheduling using ML
* Mobile app notifications

---

## 📚 Project Status

* **Version:** 1.0
* **Duration:** Jan 2025 – Apr 2025
* **Current Phase:** CLI Prototype
* **License:** Open for academic and experimental use

---

## 🤝 Contributing

This project is designed with a modular and extensible architecture. Contributions for NLP improvements, UI layers, integrations, and testing are welcome.

---

## 📌 Conclusion

S.A.M demonstrates how agentic AI can significantly reduce administrative friction in educational environments by combining natural language understanding, automation, and intelligent orchestration into a single scalable system.

---

If you want, I can also:

* Split this into **README + ARCHITECTURE.md**
* Create a **minimal README** for GitHub
* Add **badges**, **project screenshots**, or **setup instructions**
* Convert it into **MkDocs / Docusaurus** docs

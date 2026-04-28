  All 5 migrations, 17 services, 8 new routes, 5 new frontend pages + a role-aware sidebar. Final compile clean across all Python files.                                                        
                                                                                                                                                                                                
  Run order to test                                                                                                                                                                             
                                                                                                                                                                                                
  # 1. System dep (one-time, sudo) — Python deps already installed in .venv                                                                                                                     
  sudo dnf install -y tesseract                                                                                                                                                                 
                                                                                                                                                                                              
  # 2. Migrations in order
  python scripts/migrate_v4_foundations.py                                                                                                                                                      
  python scripts/migrate_v5_timetable.py                                                                                                                                                        
  python scripts/migrate_v6_academic_calendar.py                                                                                                                                              
  python scripts/migrate_v7_tasks.py
  python scripts/migrate_v8_booking_briefing.py                                                                                                                                                 
                                                                                                                                                                                              
  # 3. Stack — note the new `beat` container                                                                                                                                                    
  docker compose build           # bakes Tesseract + ffmpeg into the image                                                                                                                      
  docker compose up -d                                                                                                                                                                          
  docker compose logs -f beat    # heartbeat every 5min: "tick_user_briefings: dispatched N briefing(s)"                                                                                        
                                                                                                                                                                                                
  # 4. Re-login so JWTs carry the new `role` claim                                                                                                                                              
                                                                                                                                                                                              
  # 5. Frontend                                                                                                                                                                                 
  cd frontend && npm run dev                                                                                                                                                                    
                                      
  Smoke-test checklist (golden path)                                                                                                                                                            
                                      
  1. Faculty WhatsApp: "set up my timetable" → photo of timetable → review buttons → "Save". Confirm timetable_entries rows.                                                                    
  2. Student WhatsApp: "where is Prof Sharma now?" → SAM answers from grid + active meetings.                                                                                                 
  3. SUPER_ADMIN web at /app/super-admin/calendar: upload PDF calendar → review → save. Try scheduling a meeting on a holiday → blocked.                                                        
  4. SUPER_ADMIN at /app/super-admin/users: edit a user's role to BOOKING_AUTHORITY. Have them log out + back in to refresh JWT.                                                                
  5. Admin WhatsApp or web /app/admin/tasks/upload: drop a sheet/PDF/voice memo → review → confirm. Each assignee gets a DM. Check task_reminders rows.                                         
  6. Booking authority /app/booking/queue: see pending requests → approve/deny.                                                                                                                 
  7. Class cancellation: faculty WhatsApp "cancel today's DSA class" → broadcast goes to user_group named like the batch.                                                                       
  8. Daily briefing: in /app/settings → Daily briefing, set briefing_time to now+5min, save. Beat tick fires the briefing.                                                                      
                                                                                                                                                                                                
  Honest gaps before you ship                                                                                                                                                                   
                                                                                                                                                                                                
  - Whisper first call still warms up despite the boot signal — model files download on first run (~150 MB). Pre-pull to SAM_WHISPER_MODEL_DIR in production.                                   
  - Class-enrolment: cancellation_service requires a user_groups row whose name matches the timetable entry's batch (e.g. "CSE-3A"). The existing /app/groups UI lets you create/populate these
  manually for now.                                                                                                                                                                             
  - RBAC audit on pre-v1 routes (meetings, groups, broadcasts, analytics etc.) is still pending — they have JWT auth but no role guard. New routes are all gated.                               
  - Faculty name disambiguation asks the user when scores are within 6 points; common names in big orgs may need a manual hint.                                                                 
  - OCR on phone-camera timetables is genuinely lossy; the editable grid in /app/timetable/upload and the WhatsApp confirm step are the safety net.                                             
                                                                                                                                                                                                
  Memory updated with the new architecture so future sessions have the full picture without re-reading. Tell me what you want to test first and I'll help debug, or pick the RBAC audit / OCR   
  tuning / class-enrolment UX as the next chunk.
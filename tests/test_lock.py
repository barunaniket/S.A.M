# tests/test_lock.py
import asyncio
import sys
import os

# Add the project root to python path so we can import src
sys.path.append(os.getcwd())

from src.utils.concurrency import distributed_lock, DoubleBookingError

async def try_booking(student_name):
    print(f"👤 {student_name} is attempting to book...")
    
    try:
        # We must use 'async with' now!
        async with distributed_lock("meeting:10am_slot", lock_timeout=5, retries=0):
            print(f"✅ {student_name} LOCKED the slot! Processing...")
            await asyncio.sleep(2) # Simulate work (non-blocking)
            print(f"✨ {student_name} finished booking.")
            
    except DoubleBookingError:
        print(f"❌ {student_name} was BLOCKED (Double Booking prevented).")
    except Exception as e:
        print(f"⚠️ Unexpected error for {student_name}: {e}")

async def main():
    # Run both students at the EXACT same time
    await asyncio.gather(
        try_booking("Student A"),
        try_booking("Student B")
    )

if __name__ == "__main__":
    asyncio.run(main())
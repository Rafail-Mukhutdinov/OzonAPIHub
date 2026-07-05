import sys
import os
import asyncio
from datetime import datetime

# Add project root to sys.path
PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, PROJECT_ROOT)

from dotenv import load_dotenv
load_dotenv(os.path.join(PROJECT_ROOT, ".env"))

# Set DATABASE_URL if not present (docker default)
if not os.getenv("DATABASE_URL"):
    os.environ["DATABASE_URL"] = "postgresql://ozonuser:ozonpass@localhost:5433/ozondb"

from db.database import SessionLocal, User, OzonCredential
from services.sync import sync_user_orders
from services.ozon import init_http_client, close_http_client

async def main():
    db = SessionLocal()
    try:
        # Get the first active user with credentials
        user = db.query(User).join(OzonCredential).filter(OzonCredential.is_active == True).first()
        if not user:
            print("No active users with Ozon credentials found.")
            return

        print(f"Starting sync for user: {user.id} ({user.email})...")
        
        init_http_client()
        
        # Trigger the sync
        success = await sync_user_orders(user, db)
        
        if success:
            print("Sync completed successfully!")
        else:
            print("Sync failed or no new data found.")
            
    except Exception as e:
        print(f"Error during manual sync: {e}")
        import traceback
        traceback.print_exc()
    finally:
        await close_http_client()
        db.close()

if __name__ == "__main__":
    asyncio.run(main())

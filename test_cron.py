import asyncio
import logging
from app.core.database import AsyncSessionLocal
from app.modules.payment.service import PaymentService

logging.basicConfig(level=logging.INFO)

async def test_cron():
    print("Connecting to database and running daily subscription process...")
    async with AsyncSessionLocal() as session:
        service = PaymentService(session)
        result = await service.process_daily_subscriptions()
        print("\n--- CRON JOB COMPLETED ---")
        print("Results:")
        for key, value in result.items():
            print(f"  {key}: {value}")

if __name__ == "__main__":
    asyncio.run(test_cron())

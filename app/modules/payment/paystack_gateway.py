import httpx
from typing import Any
from fastapi import HTTPException

from app.core.config import settings
from app.modules.payment.gateway_base import PaymentGateway


class PaystackGateway(PaymentGateway):
    def __init__(self):
        self.secret_key = settings.paystack_secret_key
        self.base_url = "https://api.paystack.co"

    @property
    def headers(self):
        return {
            "Authorization": f"Bearer {self.secret_key}",
            "Content-Type": "application/json",
        }

    async def initialize_transaction(
        self, amount: float, email: str, reference: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}/transaction/initialize"
        payload = {
            "email": email,
            "amount": int(amount * 100),  # Paystack expects kobo/cents
            "reference": reference,
            "metadata": metadata or {},
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Paystack Init Error: {response.text}")
                
            data = response.json()
            if not data.get("status"):
                raise HTTPException(status_code=400, detail=data.get("message", "Unknown Paystack Error"))
                
            return {
                "authorization_url": data["data"]["authorization_url"],
                "access_code": data["data"]["access_code"],
                "reference": data["data"]["reference"],
            }

    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        url = f"{self.base_url}/transaction/verify/{reference}"
        
        async with httpx.AsyncClient() as client:
            response = await client.get(url, headers=self.headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Paystack Verify Error: {response.text}")
                
            data = response.json()
            if not data.get("status"):
                raise HTTPException(status_code=400, detail=data.get("message", "Unknown Paystack Error"))
                
            transaction_data = data["data"]
            status_map = {
                "success": "SUCCESS",
                "failed": "FAILED",
                "abandoned": "FAILED"
            }
            mapped_status = status_map.get(transaction_data["status"], "PENDING")
            
            return {
                "status": mapped_status,
                "amount": transaction_data["amount"] / 100.0,
                "authorization": transaction_data.get("authorization"),
                "full_response": transaction_data,
            }

    async def charge_saved_card(
        self, authorization_code: str, amount: float, email: str, reference: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        url = f"{self.base_url}/transaction/charge_authorization"
        payload = {
            "email": email,
            "amount": int(amount * 100),
            "authorization_code": authorization_code,
            "reference": reference,
            "metadata": metadata or {},
        }
        
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=self.headers)
            
            if response.status_code != 200:
                raise HTTPException(status_code=400, detail=f"Paystack Charge Error: {response.text}")
                
            data = response.json()
            if not data.get("status"):
                raise HTTPException(status_code=400, detail=data.get("message", "Unknown Paystack Error"))
                
            transaction_data = data["data"]
            status_map = {
                "success": "SUCCESS",
                "failed": "FAILED",
                "abandoned": "FAILED"
            }
            mapped_status = status_map.get(transaction_data["status"], "PENDING")
            
            return {
                "status": mapped_status,
                "amount": transaction_data["amount"] / 100.0,
                "authorization": transaction_data.get("authorization"),
                "full_response": transaction_data,
            }

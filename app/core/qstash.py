from fastapi import HTTPException, Request
from qstash import AsyncQStash, Receiver

from app.core.config import settings


def get_qstash_client() -> AsyncQStash:
    """
    Returns a configured AsyncQStash client for publishing messages.
    """
    if not settings.qstash_token:
        raise ValueError("QSTASH_TOKEN is not configured.")
        
    return AsyncQStash(token=settings.qstash_token)


async def verify_qstash_signature(request: Request) -> bytes:
    """
    FastAPI dependency that verifies the Upstash-Signature header.
    Returns the raw body of the request if the signature is valid.
    Raises an HTTPException if the signature is invalid or missing.
    """
    signature = request.headers.get("Upstash-Signature")
    if not signature:
        raise HTTPException(status_code=400, detail="Missing Upstash-Signature header")

    body = await request.body()
    
    receiver = Receiver(
        current_signing_key=settings.qstash_current_signing_key,
        next_signing_key=settings.qstash_next_signing_key,
    )
    
    try:
        receiver.verify(
            body=body.decode("utf-8"),
            signature=signature,
            url=str(request.url)
        )
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid QStash signature: {str(e)}")

    return body

from abc import ABC, abstractmethod
from typing import Any


class PaymentGateway(ABC):
    @abstractmethod
    async def initialize_transaction(
        self, amount: float, email: str, reference: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        """
        Initialize a transaction with the gateway.
        Should return a dictionary containing at least:
        - authorization_url: str
        - access_code: str (or equivalent session token)
        - reference: str
        """
        pass

    @abstractmethod
    async def verify_transaction(self, reference: str) -> dict[str, Any]:
        """
        Verify a transaction status with the gateway.
        Should return a dictionary containing at least:
        - status: "SUCCESS", "FAILED", "PENDING"
        - amount: float (the amount actually paid)
        - authorization: dict | None (if a card was used and can be saved, contain reusable auth data)
        - full_response: the raw response from the gateway
        """
        pass

    @abstractmethod
    async def charge_saved_card(
        self, authorization_code: str, amount: float, email: str, reference: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        """
        Charge a previously saved card.
        Should return the verification result (similar to verify_transaction).
        """
        pass

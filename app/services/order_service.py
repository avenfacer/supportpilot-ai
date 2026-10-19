import logging
from dataclasses import dataclass
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import ValidationError
from sqlalchemy.exc import SQLAlchemyError

from app.repositories.base import OrderRepository
from app.schemas.order import OrderRecord, OrderSummary

logger = logging.getLogger(__name__)

FailureMode = Literal["none", "timeout", "unavailable"]


class OrderApiError(Exception):
    pass


class OrderApiTimeout(OrderApiError):
    pass


class OrderApiUnavailable(OrderApiError):
    pass


class OrderClient(Protocol):
    """Boundary to the store's order system. A real implementation would call its HTTP API
    with an httpx client configured with ORDER_API_TIMEOUT_SECONDS."""

    def fetch(self, order_id: str) -> OrderRecord | None: ...


class MockOrderClient:
    """DEMO-ONLY mock store API backed by the synthetic `orders` table.

    `failure_mode` lets tests, evals, and demos simulate an unavailable or slow upstream.
    """

    def __init__(self, repository: OrderRepository, failure_mode: FailureMode = "none"):
        self._repo = repository
        self.failure_mode = failure_mode

    def fetch(self, order_id: str) -> OrderRecord | None:
        if self.failure_mode == "timeout":
            raise OrderApiTimeout("simulated order API timeout")
        if self.failure_mode == "unavailable":
            raise OrderApiUnavailable("simulated order API outage")
        try:
            return self._repo.get(order_id)
        except SQLAlchemyError as exc:
            raise OrderApiUnavailable("order store query failed") from exc


class OrderLookupStatus(StrEnum):
    FOUND = "found"
    NOT_FOUND = "not_found"
    UNAUTHORIZED = "unauthorized"
    TIMEOUT = "timeout"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class OrderLookupResult:
    status: OrderLookupStatus
    order: OrderSummary | None = None
    attempts: int = 1

    @property
    def is_failure(self) -> bool:
        return self.status in (OrderLookupStatus.TIMEOUT, OrderLookupStatus.UNAVAILABLE)


class OrderService:
    """Order access with server-side ownership enforcement.

    The customer ID always comes from the trusted request context, never from model output.
    """

    def __init__(self, client: OrderClient, *, max_attempts: int = 2):
        self._client = client
        self._max_attempts = max_attempts

    def lookup(self, order_id: str, customer_id: str) -> OrderLookupResult:
        last_failure = OrderLookupStatus.UNAVAILABLE
        for attempt in range(1, self._max_attempts + 1):
            try:
                record = self._client.fetch(order_id)
            except OrderApiTimeout:
                last_failure = OrderLookupStatus.TIMEOUT
            except OrderApiUnavailable:
                last_failure = OrderLookupStatus.UNAVAILABLE
            else:
                return self._authorize(order_id, customer_id, record, attempt)
            # Order lookup is a read, so retrying is safe.
            logger.warning(
                "order_lookup_failed", extra={"attempt": attempt, "failure": last_failure.value}
            )
        return OrderLookupResult(status=last_failure, attempts=self._max_attempts)

    @staticmethod
    def _authorize(
        order_id: str, customer_id: str, record: OrderRecord | None, attempt: int
    ) -> OrderLookupResult:
        if record is None:
            return OrderLookupResult(OrderLookupStatus.NOT_FOUND, attempts=attempt)
        try:
            # Upstream data is untrusted: re-validate before using it.
            record = OrderRecord.model_validate(record.model_dump())
        except ValidationError:
            logger.error("order_record_invalid", extra={"order_id": order_id})
            return OrderLookupResult(OrderLookupStatus.UNAVAILABLE, attempts=attempt)
        if record.order_id != order_id:
            logger.error("order_record_mismatch", extra={"order_id": order_id})
            return OrderLookupResult(OrderLookupStatus.UNAVAILABLE, attempts=attempt)
        if record.customer_id != customer_id:
            logger.warning(
                "order_access_denied", extra={"order_id": order_id, "customer_id": customer_id}
            )
            return OrderLookupResult(OrderLookupStatus.UNAUTHORIZED, attempts=attempt)
        return OrderLookupResult(
            OrderLookupStatus.FOUND, order=OrderSummary.from_record(record), attempts=attempt
        )

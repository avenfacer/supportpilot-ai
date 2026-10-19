"""Request identity and admin access.

DEMO-ONLY AUTHENTICATION: the customer identity is taken from the `X-Demo-Customer-Id` header
so reviewers can switch between synthetic customers. Any caller can claim any demo customer, so
this must never be used with real data. In production, replace `get_optional_customer` with a
dependency that verifies a session cookie or an OIDC/JWT access token and derives the customer
ID from its verified claims. Everything downstream only depends on `CustomerContext`.
"""

import re
import secrets
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, Header

from app.api.state import get_settings_dep
from app.core.config import Settings
from app.core.errors import AppError, AuthenticationRequiredError, NotFoundError

DEMO_CUSTOMER_HEADER = "X-Demo-Customer-Id"
ADMIN_TOKEN_HEADER = "X-Admin-Token"  # noqa: S105 - a header name, not a secret
_CUSTOMER_ID_RE = re.compile(r"^CUST-\d{3,6}$")


@dataclass(frozen=True)
class CustomerContext:
    customer_id: str
    auth_method: Literal["demo_header"] = "demo_header"


def get_optional_customer(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    demo_customer_id: Annotated[
        str | None,
        Header(
            alias=DEMO_CUSTOMER_HEADER,
            description="DEMO ONLY: synthetic customer to act as, e.g. CUST-001.",
        ),
    ] = None,
) -> CustomerContext | None:
    if not settings.enable_demo_auth or demo_customer_id is None:
        return None
    value = demo_customer_id.strip().upper()
    if not _CUSTOMER_ID_RE.match(value):
        raise AuthenticationRequiredError("The demo customer header is invalid.")
    return CustomerContext(customer_id=value)


def require_customer(
    customer: Annotated[CustomerContext | None, Depends(get_optional_customer)],
) -> CustomerContext:
    if customer is None:
        raise AuthenticationRequiredError()
    return customer


def require_admin(
    settings: Annotated[Settings, Depends(get_settings_dep)],
    admin_token: Annotated[str | None, Header(alias=ADMIN_TOKEN_HEADER)] = None,
) -> None:
    if not settings.enable_admin_endpoints or settings.admin_token is None:
        raise NotFoundError()
    expected = settings.admin_token.get_secret_value()
    if not admin_token or not secrets.compare_digest(admin_token, expected):
        raise AppError("forbidden", "Admin access is required.", http_status=403)

"""Response schemas for the billing API."""

from pydantic import BaseModel


class BillingUrlResponse(BaseModel):
    """A redirect target — a Stripe Checkout or Customer Portal URL."""

    url: str


class WebhookAck(BaseModel):
    """Ack returned to Stripe after a webhook is received. A typed schema (not a
    bare dict) per the project's FastAPI rule; the body is informational — Stripe
    only cares about the 2xx status."""

    received: bool

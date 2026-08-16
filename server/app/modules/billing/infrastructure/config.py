"""Dormant Stripe configuration loaded only by payment adapters."""

import os

STRIPE_API_KEY = os.getenv("STRIPE_API_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")
MONTHLY_PRICE_ID = os.getenv("STRIPE_MONTHLY_PRICE_ID")
YEARLY_PRICE_ID = os.getenv("STRIPE_YEARLY_PRICE_ID")
YOUR_DOMAIN = os.getenv("CLIENT_DOMAIN", "http://127.0.0.1:7300")


def is_valid_price_id(price_id: str) -> bool:
    return price_id in [MONTHLY_PRICE_ID, YEARLY_PRICE_ID]

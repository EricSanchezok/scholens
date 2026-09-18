"""Shared outbound egress address policy for source downloads."""

from __future__ import annotations

import os

# Local proxy DNS (for example Clash fake-ip mode) answers public hosts with
# synthetic non-public addresses. Production must keep the strict
# public-address requirement; this opt-out exists only for local proxy
# development.
ALLOW_NON_PUBLIC_SOURCE_ADDRESSES = (
    os.getenv("ALLOW_NON_PUBLIC_SOURCE_ADDRESSES") == "1"
)

"""Contract for a future trusted subscription service. Never verifies payments locally."""
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol


@dataclass(frozen=True)
class LicenseStatus:
    authenticated: bool
    entitlements: frozenset[str]
    device_activated: bool
    trial_expires_at: datetime | None
    offline_grace_expires_at: datetime | None
    # A remote provider must verify a signed, expiring authority response.
    authority_verified: bool = False


class SubscriptionProvider(Protocol):
    async def login(self, authorization_code: str, verifier: str) -> LicenseStatus: ...
    async def logout(self) -> None: ...
    async def status(self) -> LicenseStatus: ...
    async def activate_device(self, device_public_key: str) -> LicenseStatus: ...
    async def deactivate_device(self) -> None: ...
    async def start_trial(self) -> LicenseStatus: ...
    async def api_authentication_headers(self) -> dict[str, str]: ...


class SubscriptionNotConfigured(RuntimeError):
    pass

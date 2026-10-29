"""
app/core/auth_policy.py — Declarative identity separation, RBAC roles, and endpoint access policies.

Defines the security model established in Milestone 3A:
1. Three decoupled identities: Web User, Enrolled Speaker Voice, IoT Device.
2. Roles: Admin, User, Device, Anonymous.
3. Explicit endpoint permission matrix.
"""

from enum import Enum
from typing import Optional
from pydantic import BaseModel, Field


class IdentityType(str, Enum):
    """
    Decoupled identity domains in VoiceLock Enterprise.
    These three identities must NEVER be conflated.
    """
    WEB_USER = "web_user"          # Human operator/employee authenticated via Firebase JWT
    SPEAKER_VOICE = "speaker_voice"  # Passive biometric voiceprint (192-d ECAPA-TDNN vector)
    IOT_DEVICE = "iot_device"        # Physical hardware terminal authenticated via pre-shared secret


class Role(str, Enum):
    """Access control roles."""
    ADMIN = "admin"
    USER = "user"
    DEVICE = "device"
    ANONYMOUS = "anonymous"


class AuthScheme(str, Enum):
    """Accepted authentication schemes for API endpoints."""
    PUBLIC = "public"            # No authentication required
    FIREBASE_JWT = "firebase_jwt"  # Bearer token issued by Firebase Auth
    DEVICE_KEY = "device_key"      # X-Device-Key / HMAC token issued to hardware
    EITHER = "either"              # Accepts either valid Firebase JWT or Device Key


class Permission(str, Enum):
    """Granular permissions governing system operations."""
    HEALTH_READ = "health:read"
    SPEAKERS_LIST = "speakers:list"
    SPEAKER_ENROLL = "speaker:enroll"
    SPEAKER_DELETE = "speaker:delete"
    CHALLENGE_CREATE = "challenge:create"
    VERIFY_BIOMETRIC = "verify:biometric"
    IDENTIFY_BIOMETRIC = "identify:biometric"
    DEVICES_LIST = "devices:list"
    METRICS_READ = "metrics:read"


ROLE_PERMISSIONS: dict[Role, set[Permission]] = {
    Role.ANONYMOUS: {
        Permission.HEALTH_READ,
    },
    Role.DEVICE: {
        Permission.HEALTH_READ,
        Permission.CHALLENGE_CREATE,
        Permission.VERIFY_BIOMETRIC,
    },
    Role.USER: {
        Permission.HEALTH_READ,
        Permission.CHALLENGE_CREATE,
        Permission.VERIFY_BIOMETRIC,
    },
    Role.ADMIN: {
        Permission.HEALTH_READ,
        Permission.SPEAKERS_LIST,
        Permission.SPEAKER_ENROLL,
        Permission.SPEAKER_DELETE,
        Permission.CHALLENGE_CREATE,
        Permission.VERIFY_BIOMETRIC,
        Permission.IDENTIFY_BIOMETRIC,
        Permission.DEVICES_LIST,
        Permission.METRICS_READ,
    },
}


class EndpointPolicy(BaseModel):
    """Declarative access policy for an API endpoint."""
    path: str = Field(..., description="Route URL path")
    method: str = Field(..., description="HTTP method (GET, POST, WS, etc.)")
    auth_scheme: AuthScheme = Field(..., description="Authentication scheme required")
    required_permissions: list[Permission] = Field(default_factory=list, description="Permissions required to execute")
    description: str = Field(..., description="Security rationale and boundary description")


ENDPOINT_POLICIES: list[EndpointPolicy] = [
    EndpointPolicy(
        path="/",
        method="GET",
        auth_scheme=AuthScheme.PUBLIC,
        required_permissions=[Permission.HEALTH_READ],
        description="Public health check and liveness discovery for load balancers and clients.",
    ),
    EndpointPolicy(
        path="/speakers",
        method="GET",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.SPEAKERS_LIST],
        description="Enrolled speaker directory. Restricted to Admin to prevent user enumeration.",
    ),
    EndpointPolicy(
        path="/speakers",
        method="POST",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.SPEAKER_ENROLL],
        description="Enroll a new biometric speaker voiceprint into the persistent registry. Restricted to Admin.",
    ),
    EndpointPolicy(
        path="/devices",
        method="GET",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.DEVICES_LIST],
        description="Enrolled hardware terminal directory. Restricted to Admin.",
    ),
    EndpointPolicy(
        path="/challenge",
        method="POST",
        auth_scheme=AuthScheme.EITHER,
        required_permissions=[Permission.CHALLENGE_CREATE],
        description="Issue stateful liveness challenge digits. Requires authenticated device or user.",
    ),
    EndpointPolicy(
        path="/verify",
        method="POST",
        auth_scheme=AuthScheme.EITHER,
        required_permissions=[Permission.VERIFY_BIOMETRIC],
        description="1-to-1 biometric verification and liveness evaluation for door access.",
    ),
    EndpointPolicy(
        path="/identify",
        method="POST",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.IDENTIFY_BIOMETRIC],
        description="1-to-N unconstrained speaker identification. Restricted to Admin due to biometric leakage risk.",
    ),
    EndpointPolicy(
        path="/ws/identify",
        method="WS",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.IDENTIFY_BIOMETRIC],
        description="Real-time streaming biometric identification. Restricted to Admin.",
    ),
    EndpointPolicy(
        path="/metrics/verification",
        method="GET",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.METRICS_READ],
        description="Aggregate biometric verification telemetry and success metrics. Restricted to Admin.",
    ),
    EndpointPolicy(
        path="/metrics",
        method="GET",
        auth_scheme=AuthScheme.FIREBASE_JWT,
        required_permissions=[Permission.METRICS_READ],
        description="Aggregate biometric verification telemetry alias. Restricted to Admin.",
    ),
]


def has_permission(role: Role, permission: Permission) -> bool:
    """Return True if the given role possesses the specified permission."""
    perms = ROLE_PERMISSIONS.get(role, set())
    return permission in perms


def get_endpoint_policy(path: str, method: str) -> Optional[EndpointPolicy]:
    """Look up the defined endpoint policy for a path and method."""
    clean_method = method.upper()
    for policy in ENDPOINT_POLICIES:
        if policy.path == path and policy.method == clean_method:
            return policy
    return None


def is_public_endpoint(path: str, method: str) -> bool:
    """Return True if the endpoint does not require authentication."""
    policy = get_endpoint_policy(path, method)
    if policy is None:
        return False
    return policy.auth_scheme == AuthScheme.PUBLIC

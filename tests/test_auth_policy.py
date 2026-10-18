"""
tests/test_auth_policy.py — Unit tests for declarative authentication and authorization access policies.
"""

from app.core.auth_policy import (
    IdentityType,
    Role,
    AuthScheme,
    Permission,
    ROLE_PERMISSIONS,
    ENDPOINT_POLICIES,
    has_permission,
    get_endpoint_policy,
    is_public_endpoint,
)


def test_identity_types_distinct():
    """Verify that the three identity domains are strictly decoupled."""
    assert IdentityType.WEB_USER != IdentityType.SPEAKER_VOICE
    assert IdentityType.WEB_USER != IdentityType.IOT_DEVICE
    assert IdentityType.SPEAKER_VOICE != IdentityType.IOT_DEVICE
    assert len(IdentityType) == 3


def test_anonymous_role_permissions():
    """Anonymous callers must have minimal read-only health permission only."""
    assert has_permission(Role.ANONYMOUS, Permission.HEALTH_READ)
    assert not has_permission(Role.ANONYMOUS, Permission.SPEAKERS_LIST)
    assert not has_permission(Role.ANONYMOUS, Permission.CHALLENGE_CREATE)
    assert not has_permission(Role.ANONYMOUS, Permission.VERIFY_BIOMETRIC)
    assert not has_permission(Role.ANONYMOUS, Permission.IDENTIFY_BIOMETRIC)
    assert not has_permission(Role.ANONYMOUS, Permission.METRICS_READ)


def test_device_role_permissions():
    """Hardware devices can create challenges and verify biometrics, but cannot list or enroll speakers."""
    assert has_permission(Role.DEVICE, Permission.HEALTH_READ)
    assert has_permission(Role.DEVICE, Permission.CHALLENGE_CREATE)
    assert has_permission(Role.DEVICE, Permission.VERIFY_BIOMETRIC)
    assert not has_permission(Role.DEVICE, Permission.SPEAKERS_LIST)
    assert not has_permission(Role.DEVICE, Permission.SPEAKER_ENROLL)
    assert not has_permission(Role.DEVICE, Permission.IDENTIFY_BIOMETRIC)
    assert not has_permission(Role.DEVICE, Permission.METRICS_READ)


def test_user_role_permissions():
    """Standard authenticated users cannot enumerate directory or perform unconstrained identification."""
    assert has_permission(Role.USER, Permission.HEALTH_READ)
    assert has_permission(Role.USER, Permission.CHALLENGE_CREATE)
    assert has_permission(Role.USER, Permission.VERIFY_BIOMETRIC)
    assert not has_permission(Role.USER, Permission.SPEAKERS_LIST)
    assert not has_permission(Role.USER, Permission.SPEAKER_ENROLL)
    assert not has_permission(Role.USER, Permission.IDENTIFY_BIOMETRIC)
    assert not has_permission(Role.USER, Permission.METRICS_READ)


def test_admin_role_permissions():
    """Admins possess complete operational permissions."""
    for perm in Permission:
        assert has_permission(Role.ADMIN, perm)


def test_endpoint_policy_discovery():
    """Verify endpoint policy lookup returns exact policy specifications."""
    health_policy = get_endpoint_policy("/", "GET")
    assert health_policy is not None
    assert health_policy.auth_scheme == AuthScheme.PUBLIC
    assert is_public_endpoint("/", "GET")

    speakers_policy = get_endpoint_policy("/speakers", "GET")
    assert speakers_policy is not None
    assert speakers_policy.auth_scheme == AuthScheme.FIREBASE_JWT
    assert Permission.SPEAKERS_LIST in speakers_policy.required_permissions
    assert not is_public_endpoint("/speakers", "GET")

    devices_policy = get_endpoint_policy("/devices", "GET")
    assert devices_policy is not None
    assert devices_policy.auth_scheme == AuthScheme.FIREBASE_JWT
    assert Permission.DEVICES_LIST in devices_policy.required_permissions
    assert not is_public_endpoint("/devices", "GET")

    verify_policy = get_endpoint_policy("/verify", "POST")
    assert verify_policy is not None
    assert verify_policy.auth_scheme == AuthScheme.EITHER
    assert Permission.VERIFY_BIOMETRIC in verify_policy.required_permissions

    identify_policy = get_endpoint_policy("/identify", "POST")
    assert identify_policy is not None
    assert identify_policy.auth_scheme == AuthScheme.FIREBASE_JWT
    assert Permission.IDENTIFY_BIOMETRIC in identify_policy.required_permissions

    metrics_policy = get_endpoint_policy("/metrics/verification", "GET")
    assert metrics_policy is not None
    assert metrics_policy.auth_scheme == AuthScheme.FIREBASE_JWT
    assert Permission.METRICS_READ in metrics_policy.required_permissions
    assert not is_public_endpoint("/metrics/verification", "GET")


def test_nonexistent_endpoint_policy():
    """Looking up an unregistered route returns None and is not public."""
    assert get_endpoint_policy("/nonexistent", "GET") is None
    assert not is_public_endpoint("/nonexistent", "GET")

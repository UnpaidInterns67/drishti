from dataclasses import replace
import pytest
from backend.config import settings


def demo_settings():
    return replace(settings, environment="demo", auth_cookie_secure=True,
                   require_https=True, data_volume_encrypted=False,
                   allowed_hosts=("demo.example.test",),
                   cors_origins=("https://demo.example.test",),
                   bootstrap_officer_password="synthetic-test-password-123")


def test_demo_is_hosted_but_not_production():
    config = demo_settings()
    assert config.is_hosted and not config.is_production
    config.validate_startup()


@pytest.mark.parametrize("changes", [
    {"auth_cookie_secure": False}, {"require_https": False},
    {"allowed_hosts": ("*",)}, {"cors_origins": ("http://example.test",)},
    {"bootstrap_officer_password": "short"},
])
def test_demo_retains_hosted_security(changes):
    with pytest.raises(RuntimeError):
        replace(demo_settings(), **changes).validate_startup()


def test_production_still_requires_encrypted_storage():
    with pytest.raises(RuntimeError, match="DATA_VOLUME_ENCRYPTED"):
        replace(demo_settings(), environment="production").validate_startup()

import os
from dataclasses import dataclass
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _easyocr_model_directory() -> Path:
    """Resolve a usable EasyOCR model directory for API inference."""
    configured = os.getenv("EASYOCR_MODEL_DIRECTORY")
    if configured:
        return Path(configured)

    # EasyOCR's default downloader stores models beside the active virtual
    # environment. Reuse them instead of downloading a second copy when the
    # first API request arrives.
    for candidate in (
        PROJECT_ROOT / ".venv" / "easyocr_models",
        PROJECT_ROOT / "venv" / "easyocr_models",
    ):
        if candidate.is_dir():
            return candidate

    return PROJECT_ROOT / "runtime" / "easyocr_models"


def _cors_origins():
    configured = os.getenv("CORS_ORIGINS")
    if configured:
        return tuple(origin.strip() for origin in configured.split(",") if origin.strip())
    return (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    )


def _csv_environment(name: str, default: str) -> tuple[str, ...]:
    return tuple(
        value.strip()
        for value in os.getenv(name, default).split(",")
        if value.strip()
    )


def _environment_bool(name: str, default: str) -> bool:
    return os.getenv(name, default).lower() not in {"0", "false", "no"}


@dataclass(frozen=True)
class Settings:
    environment: str = os.getenv("APP_ENV", "development").strip().lower()
    demo_enabled: bool = _environment_bool("DEMO_ENABLED", "false")
    api_prefix: str = "/api/v1"
    max_upload_bytes: int = int(os.getenv("MAX_UPLOAD_BYTES", 15 * 1024 * 1024))
    session_ttl_seconds: int = int(os.getenv("SESSION_TTL_SECONDS", 30 * 60))
    runtime_directory: Path = Path(
        os.getenv("RUNTIME_DIRECTORY", PROJECT_ROOT / "runtime")
    )
    easyocr_model_directory: Path = _easyocr_model_directory()
    database_path: Path = Path(
        os.getenv(
            "DATABASE_PATH",
            PROJECT_ROOT / "runtime" / "identity_verification.db",
        )
    )
    uidai_certificate_directory: Path = Path(
        os.getenv("UIDAI_CERTIFICATE_DIRECTORY", PROJECT_ROOT / "certs")
    )
    duplicate_face_threshold: float = float(
        os.getenv("DUPLICATE_FACE_THRESHOLD", "0.50")
    )
    bootstrap_officer_username: str | None = (
        os.getenv("BOOTSTRAP_OFFICER_USERNAME") or None
    )
    bootstrap_officer_password: str | None = (
        os.getenv("BOOTSTRAP_OFFICER_PASSWORD") or None
    )
    auth_session_ttl_seconds: int = int(
        os.getenv("AUTH_SESSION_TTL_SECONDS", str(8 * 60 * 60))
    )
    auth_cookie_secure: bool = os.getenv(
        "AUTH_COOKIE_SECURE", "true"
    ).lower() not in {"0", "false", "no"}
    cors_origins: tuple[str, ...] = _cors_origins()
    allowed_hosts: tuple[str, ...] = _csv_environment(
        "ALLOWED_HOSTS", "localhost,127.0.0.1,testserver"
    )
    require_https: bool = _environment_bool("REQUIRE_HTTPS", "false")
    data_volume_encrypted: bool = _environment_bool(
        "DATA_VOLUME_ENCRYPTED", "false"
    )
    max_image_pixels: int = int(os.getenv("MAX_IMAGE_PIXELS", "25000000"))
    analysis_max_dimension: int = int(os.getenv("ANALYSIS_MAX_DIMENSION", "1280"))
    api_rate_limit: int = int(os.getenv("API_RATE_LIMIT", "300"))
    api_rate_window_seconds: int = int(
        os.getenv("API_RATE_WINDOW_SECONDS", "60")
    )
    login_rate_limit: int = int(os.getenv("LOGIN_RATE_LIMIT", "20"))
    login_rate_window_seconds: int = int(
        os.getenv("LOGIN_RATE_WINDOW_SECONDS", "300")
    )

    @property
    def is_production(self) -> bool:
        return self.environment == "production"

    @property
    def is_hosted(self) -> bool:
        return self.environment in {"production", "demo"}

    def validate_startup(self) -> None:
        if self.environment not in {"development", "test", "production", "demo"}:
            raise RuntimeError("APP_ENV must be development, test, production, or demo")
        if self.max_upload_bytes <= 0 or self.max_image_pixels <= 0 or self.analysis_max_dimension < 640:
            raise RuntimeError("Upload limits must be positive")
        if not self.allowed_hosts:
            raise RuntimeError("ALLOWED_HOSTS must contain at least one hostname")
        if not self.is_hosted:
            return
        failures = []
        if not self.auth_cookie_secure:
            failures.append("AUTH_COOKIE_SECURE must be true")
        if not self.require_https:
            failures.append("REQUIRE_HTTPS must be true")
        if self.is_production and not self.data_volume_encrypted:
            failures.append("DATA_VOLUME_ENCRYPTED must attest encrypted storage")
        if "*" in self.allowed_hosts:
            failures.append("ALLOWED_HOSTS cannot contain *")
        if any(not origin.startswith("https://") for origin in self.cors_origins):
            failures.append("CORS_ORIGINS must contain only HTTPS origins")
        password = self.bootstrap_officer_password or ""
        if password and (
            len(password) < 14
            or "replace-with" in password.lower()
            or password.lower() in {"password", "admin123", "changeme"}
        ):
            failures.append("bootstrap password is weak or still a placeholder")
        if failures:
            raise RuntimeError("Unsafe production configuration: " + "; ".join(failures))


settings = Settings()

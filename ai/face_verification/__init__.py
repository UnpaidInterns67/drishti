__all__ = ["IdentityVerifier", "find_duplicate_identities"]


def __getattr__(name):
    """Load optional computer-vision dependencies only when requested."""
    if name == "IdentityVerifier":
        from .verifier import IdentityVerifier

        return IdentityVerifier
    if name == "find_duplicate_identities":
        from .identity_search import find_duplicate_identities

        return find_duplicate_identities
    raise AttributeError(name)

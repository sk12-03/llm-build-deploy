import os

def verify_secret(provided: str) -> bool:
    """Return True only if the provided secret matches .env SERVER_SECRET."""
    return provided and provided == os.getenv("SERVER_SECRET", "")

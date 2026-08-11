"""KRX market-data ingestion package."""

from .config import Settings, load_environment

load_environment()

__all__ = ["Settings", "load_environment"]

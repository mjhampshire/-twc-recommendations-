"""ClickHouse configuration.

Load from environment variables for production,
with sensible defaults for development.
"""
import os
from dataclasses import dataclass


@dataclass
class ClickHouseConfig:
    """ClickHouse connection configuration."""
    host: str
    port: int = 8443
    username: str = "default"
    password: str = ""
    database: str = "default"
    secure: bool = True

    @classmethod
    def from_env(cls) -> "ClickHouseConfig":
        """Load configuration from environment variables."""
        return cls(
            host=os.getenv("CLICKHOUSE_HOST", "localhost"),
            port=int(os.getenv("CLICKHOUSE_PORT", "8443")),
            username=os.getenv("CLICKHOUSE_USER", "default"),
            password=os.getenv("CLICKHOUSE_PASSWORD", ""),
            database=os.getenv("CLICKHOUSE_DATABASE", "default"),
            secure=os.getenv("CLICKHOUSE_SECURE", "true").lower() == "true",
        )


def get_clickhouse_config() -> ClickHouseConfig:
    """Get the ClickHouse configuration."""
    return ClickHouseConfig.from_env()

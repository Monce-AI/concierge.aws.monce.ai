"""Configuration for Concierge API."""

import os
from dataclasses import dataclass
from typing import Optional


@dataclass
class Config:
    """Application configuration loaded from environment variables."""

    # AWS Bedrock
    aws_region: str = "eu-west-3"
    aws_bearer_token: Optional[str] = None
    bedrock_model: str = "anthropic.claude-3-sonnet-20240229-v1:0"

    # AWS IAM (for SES, S3 email bucket)
    aws_access_key_id: Optional[str] = None
    aws_secret_access_key: Optional[str] = None

    # Data paths (server-side)
    data_dir: str = "/opt/concierge/data"

    # API
    api_host: str = "0.0.0.0"
    api_port: int = 8000

    @classmethod
    def from_env(cls) -> "Config":
        return cls(
            aws_region=os.getenv("AWS_REGION", "eu-west-3"),
            aws_bearer_token=os.getenv("AWS_BEARER_TOKEN_BEDROCK"),
            bedrock_model=os.getenv("BEDROCK_MODEL", "anthropic.claude-3-sonnet-20240229-v1:0"),
            aws_access_key_id=os.getenv("AWS_ACCESS_KEY_ID"),
            aws_secret_access_key=os.getenv("AWS_SECRET_ACCESS_KEY"),
            data_dir=os.getenv("CONCIERGE_DATA_DIR", "/opt/concierge/data"),
            api_host=os.getenv("API_HOST", "0.0.0.0"),
            api_port=int(os.getenv("API_PORT", "8000")),
        )


config = Config.from_env()

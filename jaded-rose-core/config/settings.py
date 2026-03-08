"""Application settings loaded from environment variables via pydantic BaseSettings."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration for the Jaded Rose Core platform.

    All values are read from environment variables (or a .env file).
    """

    # OpenAI
    OPENAI_API_KEY: str

    # Pinecone
    PINECONE_API_KEY: str
    PINECONE_ENVIRONMENT: str = "us-east-1"
    PINECONE_INDEX_NAME: str = "jaded-rose"

    # Shopify
    SHOPIFY_STORE_URL: str
    SHOPIFY_ADMIN_API_KEY: str
    SHOPIFY_STOREFRONT_TOKEN: str = ""
    SHOPIFY_WEBHOOK_SECRET: str = ""

    # GCP
    GCP_PROJECT_ID: str
    GCP_PUBSUB_TOPIC: str = "jaded-rose-tasks"
    CLOUD_SQL_CONNECTION_STRING: str

    # Redis
    REDIS_URL: str = "redis://localhost:6379/0"

    class Config:
        """Pydantic configuration."""

        env_file = ".env"
        env_file_encoding = "utf-8"


settings = Settings()  # type: ignore[call-arg]

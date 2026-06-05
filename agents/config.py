"""
CertIQ — Agent Configuration
==============================

Central configuration for the CertIQ agent system.
Loads settings from environment variables (.env file).

Key design decisions:
  - GitHub Models as inference backend (not Azure OpenAI)
  - Tiered model selection: gpt-4o for reasoning, gpt-4o-mini for simple tasks
  - Confidence threshold for self-reflection trigger
  - Retry configuration for rate limit handling (429 errors)
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """
    Application settings loaded from environment variables.
    Create a .env file from .env.example and fill in your values.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- GitHub Models (Inference) ---
    github_token: str = Field(
        default="",
        description="GitHub Personal Access Token with models:read scope",
    )
    github_models_endpoint: str = Field(
        default="https://models.github.ai/inference",
        description="GitHub Models API endpoint",
    )
    github_model_primary: str = Field(
        default="openai/gpt-4o",
        description="Primary model for complex reasoning agents",
    )
    github_model_lite: str = Field(
        default="openai/gpt-4o-mini",
        description="Lite model for simpler tasks (Engagement, Critic)",
    )

    # --- Azure AI Search (Foundry IQ) ---
    azure_search_endpoint: str = Field(
        default="",
        description="Azure AI Search endpoint URL",
    )
    azure_search_admin_key: str = Field(
        default="",
        description="Azure AI Search admin key",
    )
    azure_search_index_name: str = Field(
        default="certiq-knowledge",
        description="Azure AI Search index name for knowledge base",
    )

    # --- Azure Blob Storage ---
    azure_blob_connection_string: str = Field(
        default="",
        description="Azure Blob Storage connection string",
    )
    azure_blob_container_name: str = Field(
        default="org-knowledge",
        description="Blob container name for knowledge base documents",
    )

    # --- Agent Behavior ---
    confidence_threshold: float = Field(
        default=0.65,
        description="Confidence score below which self-reflection is triggered",
    )
    plan_health_escalation_threshold: float = Field(
        default=0.6,
        description="Plan Health below which escalation is considered",
    )
    plan_health_escalation_weeks: int = Field(
        default=2,
        description="Consecutive weeks below threshold before escalation triggers",
    )

    # --- API Settings ---
    api_host: str = Field(default="0.0.0.0")
    api_port: int = Field(default=8000)
    cors_origins: str = Field(
        default="http://localhost:5173,http://localhost:3000",
        description="Comma-separated list of allowed CORS origins",
    )

    # --- Logging ---
    log_level: str = Field(default="INFO")

    # --- Retry Configuration ---
    max_retries: int = Field(
        default=3,
        description="Max retries for rate-limited API calls",
    )
    retry_min_wait: float = Field(
        default=1.0,
        description="Minimum wait time (seconds) between retries",
    )
    retry_max_wait: float = Field(
        default=30.0,
        description="Maximum wait time (seconds) between retries",
    )

    # ---------------------------------------------------------------
    # Computed properties
    # ---------------------------------------------------------------

    @property
    def cors_origins_list(self) -> list[str]:
        """Parse comma-separated CORS origins into a list."""
        return [origin.strip() for origin in self.cors_origins.split(",") if origin.strip()]

    def get_model(self, tier: str = "primary") -> str:
        """
        Get the model name for a given tier.

        Args:
            tier: "primary" for gpt-4o, "lite" for gpt-4o-mini

        Returns:
            Model name in publisher/model format (e.g., "openai/gpt-4o")
        """
        if tier == "lite":
            return self.github_model_lite
        return self.github_model_primary

    def get_model_for_agent(self, agent_name: str) -> str:
        """
        Get the correct model for a specific agent based on tiered assignment.

        Tiered assignment:
          - gpt-4o: orchestrator, learning_path_curator, assessment,
                    study_plan_generator, manager_insights
          - gpt-4o-mini: engagement, critic_verifier
        """
        lite_agents = {"engagement", "critic_verifier"}
        tier = "lite" if agent_name in lite_agents else "primary"
        return self.get_model(tier)


@lru_cache
def get_settings() -> Settings:
    """
    Get cached application settings.
    Settings are loaded once and reused throughout the application lifecycle.
    """
    return Settings()


# Module-level convenience reference
settings = get_settings()

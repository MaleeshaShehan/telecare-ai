"""Reads .env once and exposes typed settings to every agent.

Usage:
    from shared.config import settings
    settings.orchestrator_port
"""
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    # Load from .env in the repo root. Environment variables override the file,
    # which is how tests force LLM_PROVIDER=mock.
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # LLM. Primary first; on error or rate limit the call goes to the fallback.
    llm_provider: str = "mock"          # gemini | openai | groq | mock
    llm_fallback: str = "openai"        # GPT is our backup
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    openai_api_key: str = ""
    openai_model: str = "gpt-4o-mini"
    groq_api_key: str = ""              # optional third provider, used only if a key is set
    groq_model: str = "llama-3.1-8b-instant"

    # Security
    jwt_secret: str = "dev-only-change-me"
    fernet_key: str = ""
    internal_api_key: str = "dev-only-change-me"
    jwt_ttl_minutes: int = 15
    otp_ttl_seconds: int = 300

    # Optional per-agent infrastructure. Each builder decides whether to use these.
    supabase_url: str = ""          # empty -> the agent uses its local SQLite path
    supabase_key: str = ""          # service role key, server-side only, never to the browser
    sms_provider: str = "simulated"  # simulated | http   (Account Agent OTP channel)
    sms_gateway_url: str = ""        # the member's SMS gateway endpoint (POST number + text)
    sms_gateway_key: str = ""
    sms_sender_id: str = "TeleCare"

    # Retrieval
    retrieval_min_similarity: float = 0.35

    # Ports
    orchestrator_port: int = 8000
    knowledge_port: int = 8001
    account_port: int = 8002
    supervisor_port: int = 8003
    ui_port: int = 8501

    # Convenience: base URL of each specialist, used by shared/http.py
    def agent_url(self, agent: str) -> str:
        ports = {
            "orchestrator": self.orchestrator_port,
            "knowledge_agent": self.knowledge_port,
            "account_agent": self.account_port,
            "supervisor_agent": self.supervisor_port,
        }
        return f"http://127.0.0.1:{ports[agent]}"


settings = Settings()

import os
from dataclasses import dataclass

from dotenv import load_dotenv

load_dotenv()

MCP_BASE_URL = os.getenv("MCP_BASE_URL", "http://localhost:5678")
MCP_SHARED_TOKEN = os.getenv("MCP_SHARED_TOKEN", "")
MCP_USE_NGROK = os.getenv("MCP_USE_NGROK", "false").lower() == "true"

def _split_env_list(env_name: str, default_csv: str) -> tuple[str, ...]:
    raw = os.getenv(env_name, "").strip()
    if raw:
        parts = [p.strip() for p in raw.split(",")]
        return tuple(p for p in parts if p)
    parts = [p.strip() for p in default_csv.split(",")]
    return tuple(p for p in parts if p)


@dataclass(frozen=True)
class Settings:
    app_title: str = os.getenv("APP_TITLE", "Aprimo MCP Agent")
    anthropic_api_key: str = os.getenv("ANTHROPIC_API_KEY", "")
    anthropic_model: str = os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5")

    llm_provider: str = os.getenv("LLM_PROVIDER", "anthropic").lower()  # "anthropic" or "openai"

    openai_api_key: str = os.getenv("OPENAI_API_KEY", "")
    openai_model: str = os.getenv("OPENAI_MODEL", "gpt-4o-mini")

    anthropic_model_options: tuple[str, ...] = _split_env_list(
        "ANTHROPIC_MODEL_OPTIONS",
        "claude-haiku-4-5",
    )
    openai_model_options: tuple[str, ...] = _split_env_list(
        "OPENAI_MODEL_OPTIONS",
        "gpt-4o-mini,gpt-4o",
    )

    # LangSmith tracing (LangChain)
    langsmith_api_key: str = os.getenv("LANGCHAIN_API_KEY", "")
    langsmith_project: str = os.getenv("LANGCHAIN_PROJECT", "Aprimo MCP Agent")
    langsmith_tracing_v2: bool = (
        os.getenv("LANGCHAIN_TRACING_V2", "true").lower() == "true"
    )

    mcp_server_url: str = os.getenv("MCP_SERVER_URL", "")
    mcp_transport: str = os.getenv("MCP_TRANSPORT", "http")
    mcp_auth_token: str = os.getenv("MCP_AUTH_TOKEN", "")
    mcp_auth_header_name: str = os.getenv("MCP_AUTH_HEADER_NAME", "Authorization")
    mcp_header_name: str = os.getenv("MCP_HEADER_NAME", "")
    mcp_header_value: str = os.getenv("MCP_HEADER_VALUE", "")
    mcp_tool_name_prefix: bool = os.getenv("MCP_TOOL_NAME_PREFIX", "false").lower() == "true"

    asset_columns: int = int(os.getenv("ASSET_COLUMNS", "4"))
    thumbnail_width: int = int(os.getenv("THUMBNAIL_WIDTH", "220"))


settings = Settings()


def build_mcp_headers() -> dict[str, str]:
    headers: dict[str, str] = {}

    if settings.mcp_auth_token:
        if settings.mcp_auth_header_name.lower() == "authorization":
            headers[settings.mcp_auth_header_name] = f"Bearer {settings.mcp_auth_token}"
        else:
            headers[settings.mcp_auth_header_name] = settings.mcp_auth_token

    if settings.mcp_header_name and settings.mcp_header_value:
        headers[settings.mcp_header_name] = settings.mcp_header_value

    return headers

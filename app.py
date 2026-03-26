import asyncio
import json
import os
from typing import Any

import streamlit as st
from langchain_anthropic import ChatAnthropic
try:
    from langchain_openai import ChatOpenAI  # type: ignore[reportMissingImports]
except ImportError:
    ChatOpenAI = None
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent

from config import build_mcp_headers, settings
from models import Asset

if settings.langsmith_api_key:
    os.environ["LANGCHAIN_API_KEY"] = settings.langsmith_api_key
if settings.langsmith_project:
    os.environ["LANGCHAIN_PROJECT"] = settings.langsmith_project
os.environ["LANGCHAIN_TRACING_V2"] = (
    "true" if settings.langsmith_tracing_v2 else "false"
)


st.set_page_config(page_title=settings.app_title, page_icon="🔌", layout="wide")
st.title(f"🔌 {settings.app_title}")
st.caption("Streamlit + Anthropic + LangGraph + remote n8n MCP")


async def get_client() -> MultiServerMCPClient:
    connection: dict[str, Any] = {
        "transport": settings.mcp_transport,
        "url": settings.mcp_server_url,
    }
    headers = build_mcp_headers()
    if headers:
        connection["headers"] = headers

    return MultiServerMCPClient(
        {"n8n": connection},
        tool_name_prefix=settings.mcp_tool_name_prefix,
    )

async def list_tools_async() -> list:
    client = await get_client()
    tools = await client.get_tools()
    return tools


async def run_agent_async(
    messages: list[dict[str, str]],
    llm_provider: str,
    llm_model: str,
):

    client = await get_client()

    tools = await client.get_tools()

    if llm_provider == "openai":
        if ChatOpenAI is None:
            raise RuntimeError("langchain_openai is not installed.")
        llm = ChatOpenAI(
            model=llm_model,
            api_key=settings.openai_api_key,
            temperature=0,
        )
    else:
        llm = ChatAnthropic(
            model=llm_model,
            api_key=settings.anthropic_api_key,
            temperature=0,
        )

    agent = create_agent(llm, tools)

    result = await agent.ainvoke({
        "messages": messages
    })

    return result

def run_async(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()

def normalize_possible_json(value: Any) -> list[dict[str, Any]]:
    queue = [value]
    found: list[dict[str, Any]] = []

    asset_like_keys = {
        "assetId",
        "asset_id",
        "fileName",
        "file_name",
        "thumbnailUrl",
        "thumbnail_url",
        "originalSizeUri",
        "original_size_uri",
        "full_url",
        "fullUrl",
    }

    while queue:
        current = queue.pop(0)

        if current is None:
            continue

        if isinstance(current, str):
            current = current.strip()
            if not current:
                continue
            try:
                decoded = json.loads(current)
            except Exception:
                continue
            queue.append(decoded)
            continue

        if isinstance(current, list):
            queue.extend(current)
            continue

        if not isinstance(current, dict):
            continue

        # 1) wrapped result collections
        results = current.get("results") or current.get("assets") or current.get("items")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    found.append(item)

        # 2) direct asset-like row
        if any(k in current for k in asset_like_keys):
            found.append(current)

        # 3) common nested containers
        for key in ("data", "content", "payload", "result"):
            nested = current.get(key)
            if nested is not None:
                queue.append(nested)

    # de-dupe identical dict references/content roughly by stable JSON string
    deduped: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in found:
        try:
            sig = json.dumps(item, sort_keys=True, default=str)
        except Exception:
            sig = str(item)
        if sig not in seen:
            seen.add(sig)
            deduped.append(item)

    return deduped

def extract_assets(messages: list[BaseMessage]) -> list[Asset]:
    assets: list[Asset] = []
    seen: set[str] = set()

    for message in messages:
        if not isinstance(message, (ToolMessage, AIMessage)):
            continue

        chunks = message.content if isinstance(message.content, list) else [message.content]
        for chunk in chunks:
            if isinstance(chunk, dict):
                payload = chunk.get("text", chunk)
            else:
                payload = chunk

            for raw in normalize_possible_json(payload):
                try:
                    asset = Asset.from_result(raw)
                except Exception:
                    continue
                unique_key = asset.asset_id or asset.full_url or asset.thumbnail_url or asset.title or ""
                if unique_key and unique_key not in seen:
                    seen.add(unique_key)
                    assets.append(asset)

    return assets

def extract_facets(messages: list[BaseMessage]) -> list[dict[str, Any]]:
    facets: list[dict[str, Any]] = []

    for message in messages:
        if not isinstance(message, (ToolMessage, AIMessage)):
            continue

        chunks = message.content if isinstance(message.content, list) else [message.content]
        for chunk in chunks:
            if isinstance(chunk, dict):
                payload = chunk.get("text", chunk)
            else:
                payload = chunk

            queue = [payload]
            while queue:
                current = queue.pop(0)

                if current is None:
                    continue

                if isinstance(current, str):
                    current = current.strip()
                    if not current:
                        continue
                    try:
                        current = json.loads(current)
                    except Exception:
                        continue

                if isinstance(current, list):
                    queue.extend(current)
                    continue

                if not isinstance(current, dict):
                    continue

                if "facets" in current and isinstance(current["facets"], list):
                    facets = current["facets"]

                for key in ("data", "content", "payload", "result"):
                    nested = current.get(key)
                    if nested is not None:
                        queue.append(nested)

    return facets

def display_facets(facets: list[dict[str, Any]]):
    if not facets:
        return

    with st.expander("Facets", expanded=False):
        for facet in facets:
            name = facet.get("name", "Unnamed facet")
            values = facet.get("values", [])
            if not values:
                continue

            st.markdown(f"**{name}**")
            for value in values:
                key = value.get("key", "")
                count = value.get("count", 0)
                st.write(f"- {key} ({count})")

def display_assets(assets: list[Asset]):
    if not assets:
        st.info("No assets were detected in the tool results.")
        return

    cols = st.columns(settings.asset_columns)
    for index, asset in enumerate(assets):
        with cols[index % settings.asset_columns]:
            image_url = asset.thumbnail_url or asset.full_url
            if image_url:
                st.image(image_url, width=settings.thumbnail_width)
            st.markdown(f"**{asset.title or 'Untitled asset'}**")
            if asset.asset_id:
                st.caption(f"Asset ID: {asset.asset_id}")
            if asset.description:
                st.write(asset.description)
            if asset.full_url:
                st.link_button("Open asset", asset.full_url, use_container_width=True)


with st.sidebar:
    st.subheader("Connection")
    st.text_input("MCP transport", value=settings.mcp_transport, disabled=True)
    st.text_input("MCP server URL", value=settings.mcp_server_url, disabled=True)
    st.divider()
    st.subheader("LLM")

    llm_provider_display = st.selectbox(
        "LLM Provider",
        ["Anthropic", "OpenAI"],
        index=0 if settings.llm_provider != "openai" else 1,
        key="llm_provider_display",
    )
    llm_provider = "anthropic" if llm_provider_display == "Anthropic" else "openai"

    if llm_provider == "anthropic":
        model_options = list(settings.anthropic_model_options)
        default_model = settings.anthropic_model
    else:
        model_options = list(settings.openai_model_options)
        default_model = settings.openai_model

    try:
        default_index = model_options.index(default_model)
    except ValueError:
        default_index = 0

    st.selectbox(
        "Model",
        model_options,
        index=default_index,
        key="llm_model",
    )

    if st.button("List MCP tools", use_container_width=True):
        if not settings.mcp_server_url:
            st.error("Set MCP_SERVER_URL in .env first.")
        else:
            try:
                tools = run_async(list_tools_async())
                st.success(f"Connected. Found {len(tools)} tool(s).")
                for tool in tools:
                    with st.expander(tool.name):
                        st.write(tool.description or "No description")
                        schema = getattr(tool, "args_schema", None)
                        if schema is not None:
                            try:
                                st.json(schema.model_json_schema())
                            except Exception:
                                st.write("Schema available but could not be rendered.")
            except Exception as exc:
                st.error(f"Tool discovery failed: {exc}")

    if st.button("Clear chat", use_container_width=True):
        st.session_state.chat_history = []
        st.session_state.agent_messages = []
        st.rerun()


if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        st.markdown(msg["content"])
        if msg.get("assets"):
            display_assets(msg["assets"])

prompt = st.chat_input("Ask n8n MCP to search Aprimo assets")

if prompt:
    llm_provider_display = st.session_state.get("llm_provider_display", "Anthropic")
    llm_provider = "anthropic" if llm_provider_display == "Anthropic" else "openai"
    llm_model = st.session_state.get(
        "llm_model",
        settings.anthropic_model if llm_provider == "anthropic" else settings.openai_model,
    )

    if llm_provider == "anthropic":
        if not settings.anthropic_api_key:
            st.error("Set ANTHROPIC_API_KEY in .env.")
            st.stop()
    else:
        if not settings.openai_api_key:
            st.error("Set OPENAI_API_KEY in .env.")
            st.stop()

    if not settings.mcp_server_url:
        st.error("Set MCP_SERVER_URL in .env.")
        st.stop()

    st.session_state.chat_history.append({"role": "user", "content": prompt})
    with st.chat_message("user"):
        st.markdown(prompt)

    message_input = [
        {"role": item["role"], "content": item["content"]}
        for item in st.session_state.chat_history
    ]


    with st.chat_message("assistant"):
        with st.spinner("Thinking..."):
            try:
                result = run_async(run_agent_async(message_input, llm_provider, llm_model))
                final_message = result["messages"][-1]

                answer = (
                    final_message.content
                    if isinstance(final_message.content, str)
                    else str(final_message.content)
                )

                # Extract assets
                assets = extract_assets(result["messages"])

                # NEW: Extract facets
                facets = extract_facets(result["messages"])

            except Exception as exc:
                answer = f"Agent error: {exc}"
                assets = []
                facets = []

        st.markdown(answer)

        # Display assets
        display_assets(assets)

        # NEW: Display facets
        display_facets(facets)

    # Store in session
    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": answer,
            "assets": assets,
            "facets": facets,
        }
    )
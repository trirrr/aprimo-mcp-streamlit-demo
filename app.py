import asyncio
import json
import os
import re
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
os.environ["LANGCHAIN_TRACING_V2"] = "true" if settings.langsmith_tracing_v2 else "false"


st.set_page_config(page_title=settings.app_title, page_icon="🔌", layout="wide")
st.title(f"🔌 {settings.app_title}")
st.caption("Streamlit + LangChain + multi-model LLM support + remote n8n MCP")


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

    result = await agent.ainvoke({"messages": messages})
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

        results = current.get("results") or current.get("assets") or current.get("items")
        if isinstance(results, list):
            for item in results:
                if isinstance(item, dict):
                    found.append(item)

        if any(k in current for k in asset_like_keys):
            found.append(current)

        for key in ("data", "content", "payload", "result"):
            nested = current.get(key)
            if nested is not None:
                queue.append(nested)

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

                unique_key = (
                    asset.asset_id
                    or asset.full_url
                    or asset.thumbnail_url
                    or asset.file_name
                    or asset.title
                    or ""
                )

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


def clean_answer_text(answer: str) -> str:
    if not answer:
        return ""

    cleaned = answer

    # Remove markdown image embeds
    cleaned = re.sub(r"!\[[^\]]*\]\([^)]+\)", "", cleaned)

    # Remove standalone "View Original Image" style links
    cleaned = re.sub(
        r'^\s*[-*]?\s*\[View Original Image\]\([^)]+\)\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Remove simple image-intro lines
    cleaned = re.sub(
        r'^\s*Here is an image related to .*?:\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Remove raw image URLs on their own line
    cleaned = re.sub(
        r'^\s*https?://\S+\.(png|jpg|jpeg|webp|gif)(\?\S*)?\s*$',
        "",
        cleaned,
        flags=re.IGNORECASE | re.MULTILINE,
    )

    # Collapse excessive blank lines
    cleaned = re.sub(r"\n{3,}", "\n\n", cleaned).strip()

    return cleaned


def format_ai_influenced(value: Any) -> str:
    if value is True:
        return "Yes"
    if value is False:
        return "No"
    if value is None:
        return "Not provided"
    return str(value)


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


def render_metadata_line(label: str, value: Any):
    if value is None:
        return
    value_str = str(value).strip()
    if not value_str:
        return
    st.markdown(f"**{label}:** {value_str}")


def display_assets(assets: list[Asset]):
    if not assets:
        st.info("No assets were detected in the tool results.")
        return

    st.markdown("### Search Results")

    for asset in assets:
        with st.container(border=True):
            left, right = st.columns([1, 2], gap="large")

            with left:
                image_url = asset.thumbnail_url or asset.full_url
                if image_url:
                    st.image(image_url, width=settings.thumbnail_width)
                else:
                    st.caption("No preview available")

            with right:
                st.markdown(f"#### {asset.title or 'Untitled asset'}")

                render_metadata_line("Asset ID", asset.asset_id)
                render_metadata_line("File Name", asset.file_name)
                render_metadata_line("State", asset.state)
                render_metadata_line("AI Influenced", format_ai_influenced(asset.ai_influenced))
                render_metadata_line("Description", asset.description)

                if asset.full_url:
                    st.link_button("Open asset", asset.full_url, width="content")

        st.write("")


# Session defaults
if "llm_provider_display" not in st.session_state:
    st.session_state.llm_provider_display = "OpenAI"

if "chat_history" not in st.session_state:
    st.session_state.chat_history = []

if "agent_messages" not in st.session_state:
    st.session_state.agent_messages = []


with st.sidebar:
    st.subheader("Connection")
    st.text_input("MCP transport", value=settings.mcp_transport, disabled=True)
    st.text_input("MCP server URL", value=settings.mcp_server_url, disabled=True)
    st.divider()
    st.subheader("LLM")

    llm_provider_display = st.selectbox(
        "LLM Provider",
        ["OpenAI", "Anthropic"],
        index=0 if st.session_state.llm_provider_display == "OpenAI" else 1,
        key="llm_provider_display",
    )
    llm_provider = "anthropic" if llm_provider_display == "Anthropic" else "openai"

    if llm_provider == "anthropic":
        model_options = list(settings.anthropic_model_options)
        default_model = settings.anthropic_model
    else:
        model_options = list(settings.openai_model_options)
        default_model = settings.openai_model

    if "llm_model" not in st.session_state or st.session_state.llm_model not in model_options:
        st.session_state.llm_model = default_model

    try:
        default_index = model_options.index(st.session_state.llm_model)
    except ValueError:
        default_index = 0
        st.session_state.llm_model = model_options[0]

    st.selectbox(
        "Model",
        model_options,
        index=default_index,
        key="llm_model",
    )

    if st.button("List MCP tools", width="stretch"):
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

    if st.button("Clear chat", width="stretch"):
        st.session_state.chat_history = []
        st.session_state.agent_messages = []
        st.rerun()


for msg in st.session_state.chat_history:
    with st.chat_message(msg["role"]):
        if msg.get("content"):
            st.markdown(msg["content"])
        if msg.get("assets"):
            display_assets(msg["assets"])
        if msg.get("facets"):
            display_facets(msg["facets"])


prompt = st.chat_input("Ask n8n MCP to search Aprimo assets")

if prompt:
    llm_provider_display = st.session_state.get("llm_provider_display", "OpenAI")
    llm_provider = "anthropic" if llm_provider_display == "Anthropic" else "openai"
    llm_model = st.session_state.get(
        "llm_model",
        settings.openai_model if llm_provider == "openai" else settings.anthropic_model,
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


    system_prompt = (
         "You are an Aprimo DAM search assistant. "
         "Use the available MCP search tools to retrieve multiple relevant assets, not just the single best match. "
         "For broad people, brand, object, or concept searches, aim to return up to 10 assets when available. "
         "Do not stop after finding the first relevant asset. "
         "Prefer recall over over-filtering unless the user explicitly asks for only one result. "
         "Respond with a concise, professional summary only. "
         "Do not list per-asset metadata in the prose response. "
         "Do not embed markdown images. "
         "Do not include direct asset preview links like 'View Original Image'. "
         "The UI will render thumbnails and metadata separately."
     )
 
    history_without_latest_user = st.session_state.chat_history[:-1]

    search_instruction = (
        f"Search Aprimo for: {prompt}\n\n"
        "Return up to 10 relevant assets if available. "
        "Do not stop at the first match unless only one valid result exists. "
        "Prefer broader useful recall for people, objects, brands, and concepts."
    )

    message_input = [{"role": "system", "content": system_prompt}] + [
        {"role": item["role"], "content": item["content"]}
        for item in history_without_latest_user
    ] + [
        {"role": "user", "content": search_instruction}
    ]

    with st.chat_message("assistant"):
        with st.spinner("Searching Aprimo assets..."):
            try:
                result = run_async(run_agent_async(message_input, llm_provider, llm_model))
                final_message = result["messages"][-1]

                answer = (
                    final_message.content
                    if isinstance(final_message.content, str)
                    else str(final_message.content)
                )
                answer = clean_answer_text(answer)

                assets = extract_assets(result["messages"])
                facets = extract_facets(result["messages"])

                if assets:
                    answer = f"Found {len(assets)} asset(s)." if len(assets) > 1 else "Found 1 asset."                    

            except Exception as exc:
                answer = f"Agent error: {exc}"
                assets = []
                facets = []

        if answer and not assets:
             st.markdown(answer)
        elif assets:
            st.caption(answer)

        display_assets(assets)
        display_facets(facets)

    st.session_state.chat_history.append(
        {
            "role": "assistant",
            "content": answer,
            "assets": assets,
            "facets": facets,
        }
    )
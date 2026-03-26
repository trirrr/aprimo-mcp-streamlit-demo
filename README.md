# Aprimo MCP Streamlit Demo

A Streamlit-based demo that connects an LLM-powered chat interface to Aprimo DAM search through n8n Model Context Protocol (MCP) workflows.

This repository is designed for local development first, with a clean path to team sharing once credentials and workflow configuration are in place.

## Overview

The project lets a user enter a natural-language query in Streamlit, routes the request through an MCP-enabled n8n workflow, calls Aprimo DAM search APIs, and returns structured asset results back to the UI.

## Architecture

```text
Streamlit UI
  -> LangChain MCP client
    -> n8n MCP workflow
      -> Aprimo OAuth token request
      -> Aprimo DAM search
      -> Record/public-link enrichment
      -> Structured response back to Streamlit
```

Optional for local hardening:

```text
Streamlit UI
  -> FastAPI proxy
    -> n8n MCP workflow
```

## Included Files

- `app.py` — Streamlit chat UI and MCP client integration
- `config.py` — environment-based app settings
- `models.py` — response models used by the UI
- `mcp_proxy_fastapi.py` — optional local proxy for MCP routing
- `requirements.txt` — Python dependencies
- `n8n/aprimo-mcp-search-sanitized.json` — sanitized parent MCP workflow
- `n8n/aprimo-search-child-sanitized.json` — sanitized child search workflow

## Features

- Streamlit chat interface for Aprimo search
- MCP-based tool calling through n8n
- Asset result rendering with metadata
- Support for local development with Anthropic or OpenAI-compatible model wiring
- Optional FastAPI proxy for local endpoint control

## Prerequisites

- Python 3.11+
- n8n running locally or on an accessible host
- Aprimo tenant and API credentials
- A valid LLM API key for your selected model provider

## Project Setup

### 1. Clone the repository

```bash
git clone https://github.com/YOUR_USERNAME/YOUR_REPO_NAME.git
cd YOUR_REPO_NAME
```

### 2. Create and activate a virtual environment

**Windows (PowerShell)**

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

**macOS / Linux**

```bash
python -m venv .venv
source .venv/bin/activate
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Create your local `.env`

Example:

```env
# LLM
ANTHROPIC_API_KEY=YOUR_ANTHROPIC_KEY
OPENAI_API_KEY=YOUR_OPENAI_KEY

# MCP
MCP_SERVER_URL=http://localhost:5678/mcp/REPLACE_WITH_MCP_PATH
MCP_TRANSPORT=http
MCP_AUTH_HEADER_NAME=
MCP_AUTH_TOKEN=
MCP_HEADER_NAME=
MCP_HEADER_VALUE=
```

> Do not commit `.env` files. This repository is intended to stay secret-free.

## n8n Workflow Setup

The repository includes two sanitized workflow exports:

- `aprimo-mcp-search-sanitized.json` — parent workflow exposing the MCP tool
- `aprimo-search-child-sanitized.json` — child workflow that performs Aprimo token + search operations

### Import order

1. Import the child workflow first
2. Import the parent workflow second
3. Update the parent workflow so the tool node points to the imported child workflow
4. Set the MCP Trigger path in the parent workflow
5. Activate the workflows

### Required replacements after import

Replace these placeholders in n8n:

- `REPLACE_WITH_MCP_PATH`
- `REPLACE_WITH_CHILD_WORKFLOW_ID`
- `REPLACE_WITH_APRIMO_CLIENT_ID`
- `REPLACE_WITH_APRIMO_CLIENT_SECRET`
- `{{TENANT}}`

### Tenant variable guidance

The sanitized child workflow replaces hardcoded `partnerdemo111` references with `{{TENANT}}` so you can adapt it to your own Aprimo environment.

Use these patterns when updating URLs:

- OAuth base: `https://YOUR_TENANT.aprimo.com`
- DAM API base: `https://YOUR_TENANT.dam.aprimo.com`

For production-quality n8n configuration, move secrets out of node bodies and into n8n credentials or environment variables wherever possible.

## Running the App

Start Streamlit:

```bash
streamlit run app.py
```

If you use the optional proxy, start it separately and point `MCP_SERVER_URL` to the proxy URL instead of the direct n8n MCP URL.

## Recommended Security Practices

- Never commit `.env`, `.env.*`, or raw credential exports
- Store Aprimo secrets in n8n credentials or environment variables
- Keep the raw n8n MCP endpoint private during development
- Expose only the Streamlit app when sharing with teammates
- Rotate any credential that was previously saved in an exported workflow

## Publishing to GitHub

Before pushing:

1. Confirm `.env` and `.env.proxy` are ignored
2. Confirm only sanitized n8n workflow exports are included
3. Verify the repository contains no tenant-specific secrets or MCP path IDs
4. Test setup using only the instructions in this README

## Suggested Repository Structure

```text
.
|-- app.py
|-- config.py
|-- models.py
|-- mcp_proxy_fastapi.py
|-- requirements.txt
|-- README.md
|-- n8n/
|   |-- aprimo-mcp-search-sanitized.json
|   `-- aprimo-search-child-sanitized.json
`-- .env.example
```

## Notes

- Local Streamlit testing may still show a non-blocking `Unknown SSE event: endpoint` console warning depending on MCP client and server versions.
- For this project, `MCP_TRANSPORT=http` is the intended setting for Streamlit.
- When ready to share with a dev team, publish the code first, then expose only the Streamlit UI rather than the raw MCP endpoint.

## License

Add the license of your choice before publishing, such as MIT.

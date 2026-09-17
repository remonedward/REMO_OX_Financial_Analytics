"""
REMO_OX Financial Analytics - LLM Client
Universal LLM integration via LiteLLM with MCP tool-calling loop.

Supports any LLM provider: OpenAI, Anthropic, Gemini, Ollama, Groq,
Azure OpenAI, Together AI, OpenRouter, and any OpenAI-compatible endpoint.
"""

import asyncio
import json
import logging
import os
import time
from pathlib import Path

import litellm
from mcp import ClientSession
from mcp.client.sse import sse_client

logger = logging.getLogger(__name__)

# Suppress litellm's verbose logging
litellm.suppress_debug_info = True

# Default MCP server URL (overridden via env var in Docker)
MCP_SERVER_URL = os.environ.get("MCP_SERVER_URL", "http://localhost:8000/sse")

# Safety limit to prevent infinite tool-calling loops
MAX_TOOL_ITERATIONS = 10

# System prompt that instructs the LLM on its role and capabilities
SYSTEM_PROMPT = """\
You are REMO_OX, an expert financial data analyst assistant. \
You help users analyze their financial data using the available tools.

**Your capabilities:**
1. **analyze_data** — Read and analyze Excel data: summaries, statistics, \
column info, correlations, missing values, value counts, and more.
2. **generate_chart** — Create visualizations: bar, line, pie, scatter, \
and histogram charts from the data.
3. **export_pdf_report** — Generate professional PDF reports with text \
summaries and optional embedded charts.

**Guidelines:**
- Always start by understanding the data structure (use analyze_data with \
query_type="columns" or "summary") before performing deeper analysis.
- Use the tools to get real data — never guess or fabricate numbers.
- Choose appropriate chart types based on the data characteristics.
- Provide clear, insightful explanations of results.
- If a tool returns an error, explain the issue clearly and suggest a fix.
- Be concise but thorough.
- Respond in the same language the user writes in.\
"""


async def get_mcp_tools(server_url: str = MCP_SERVER_URL) -> list[dict]:
    """
    Connect to the MCP server and retrieve available tool definitions.
    Returns tools in OpenAI-compatible function-calling format.
    """
    tools: list[dict] = []
    try:
        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                for tool in result.tools:
                    openai_tool = {
                        "type": "function",
                        "function": {
                            "name": tool.name,
                            "description": tool.description or "",
                            "parameters": (
                                tool.inputSchema
                                if tool.inputSchema
                                else {"type": "object", "properties": {}}
                            ),
                        },
                    }
                    tools.append(openai_tool)
    except Exception as e:
        logger.error(f"Failed to fetch MCP tools: {e}")
    return tools


async def call_mcp_tool(
    tool_name: str,
    arguments: dict,
    server_url: str = MCP_SERVER_URL,
) -> str:
    """
    Call a specific tool on the MCP server and return its response as a string.
    """
    try:
        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)

                if result.content:
                    parts = []
                    for item in result.content:
                        if hasattr(item, "text"):
                            parts.append(item.text)
                        else:
                            parts.append(str(item))
                    return "\n".join(parts)

                return json.dumps({"result": "Tool executed (no content returned)."})
    except Exception as e:
        logger.error(f"MCP tool call failed: {e}")
        return json.dumps({"error": f"Tool call failed: {str(e)}"})


def _inject_session_paths(
    tool_name: str,
    arguments: dict,
    session_dir: str,
) -> dict:
    """
    Inject session-specific file paths into tool arguments.
    This ensures user input never controls file paths directly — all paths
    are forced into the session directory.
    """
    args = dict(arguments)

    # Inject data file path for tools that read data
    if tool_name in ("analyze_data", "generate_chart"):
        args["file_path"] = str(Path(session_dir) / "data.xlsx")

    # Force chart output into session directory
    if tool_name == "generate_chart":
        if not args.get("output_path"):
            args["output_path"] = str(
                Path(session_dir) / f"chart_{int(time.time())}.png"
            )
        else:
            chart_name = Path(args["output_path"]).name
            args["output_path"] = str(Path(session_dir) / chart_name)

    # Force PDF output into session directory
    if tool_name == "export_pdf_report":
        if not args.get("output_path"):
            args["output_path"] = str(
                Path(session_dir) / f"report_{int(time.time())}.pdf"
            )
        else:
            pdf_name = Path(args["output_path"]).name
            args["output_path"] = str(Path(session_dir) / pdf_name)

        # If a chart_path is referenced, ensure it points to session dir
        if args.get("chart_path"):
            chart_name = Path(args["chart_path"]).name
            args["chart_path"] = str(Path(session_dir) / chart_name)

    return args


async def chat_with_tools(
    messages: list[dict],
    model: str,
    api_key: str | None = None,
    api_base: str | None = None,
    session_dir: str = "",
    server_url: str = MCP_SERVER_URL,
) -> tuple[str, list[dict], list[str]]:
    """
    Send a chat message to the LLM with MCP tool definitions and handle
    the complete tool-calling loop automatically.

    Args:
        messages: Chat history in OpenAI format [{role, content}, ...].
        model: LiteLLM model string (e.g. "gpt-4o", "claude-3-sonnet",
               "gemini/gemini-pro", "ollama/llama3").
        api_key: API key for the provider (None for local models).
        api_base: Custom API base URL (for Ollama, Azure, etc.).
        session_dir: Session directory path for file path injection.
        server_url: MCP server SSE endpoint URL.

    Returns:
        Tuple of:
          - final_response_text (str)
          - updated_messages list (for chat history persistence)
          - list of generated file paths (charts, PDFs)
    """
    # Fetch available tools from MCP server
    tools = await get_mcp_tools(server_url)
    if not tools:
        logger.warning("No MCP tools available — proceeding without tools.")

    # Build the full message list with system prompt
    full_messages = [{"role": "system", "content": SYSTEM_PROMPT}] + [
        {"role": m["role"], "content": m["content"]}
        for m in messages
    ]

    generated_files: list[str] = []

    # Prepare litellm completion kwargs
    kwargs: dict = {
        "model": model,
        "messages": full_messages,
    }
    if "gemini" not in model.lower():
        kwargs["temperature"] = 0.2
    if api_key:
        kwargs["api_key"] = api_key
    if api_base:
        kwargs["api_base"] = api_base
    if tools:
        kwargs["tools"] = tools
        kwargs["tool_choice"] = "auto"

    # --- Tool-calling loop ---
    for iteration in range(MAX_TOOL_ITERATIONS):
        try:
            response = litellm.completion(**kwargs)
        except Exception as e:
            error_msg = f"LLM API Error: {str(e)}"
            logger.error(error_msg)
            return error_msg, messages, generated_files

        choice = response.choices[0]
        resp_msg = choice.message

        # Build the assistant message for the conversation
        assistant_entry: dict = {
            "role": "assistant",
            "content": resp_msg.content or "",
        }
        if resp_msg.tool_calls:
            assistant_entry["tool_calls"] = [
                {
                    "id": tc.id,
                    "type": "function",
                    "function": {
                        "name": tc.function.name,
                        "arguments": tc.function.arguments,
                    },
                }
                for tc in resp_msg.tool_calls
            ]
        full_messages.append(assistant_entry)

        # If no tool calls, the LLM is done — return final response
        if not resp_msg.tool_calls:
            final_text = resp_msg.content or ""
            messages.append({"role": "assistant", "content": final_text})
            return final_text, messages, generated_files

        # Process each tool call
        for tc in resp_msg.tool_calls:
            tool_name = tc.function.name
            try:
                tool_args = json.loads(tc.function.arguments)
            except json.JSONDecodeError:
                tool_args = {}

            # Inject session-specific paths (security: user can't control paths)
            if session_dir:
                tool_args = _inject_session_paths(
                    tool_name, tool_args, session_dir
                )

            logger.info(f"Tool call: {tool_name}({tool_args})")

            # Execute the tool via MCP
            tool_result = await call_mcp_tool(tool_name, tool_args, server_url)

            # Track generated output files
            try:
                result_data = json.loads(tool_result)
                if isinstance(result_data, dict) and result_data.get("output_path"):
                    generated_files.append(result_data["output_path"])
            except (json.JSONDecodeError, TypeError):
                pass

            # Append tool result to conversation
            full_messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "content": tool_result,
            })

        # Continue loop with updated messages
        kwargs["messages"] = full_messages

    # Exhausted max iterations — return whatever we have
    final_text = resp_msg.content or "Analysis complete (max tool iterations reached)."
    messages.append({"role": "assistant", "content": final_text})
    return final_text, messages, generated_files

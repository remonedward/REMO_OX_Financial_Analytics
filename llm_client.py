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


import mcp_server

# Default MCP tool definitions in OpenAI format for resilient execution
DEFAULT_TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "analyze_data",
            "description": "Analyze financial data from an Excel file. Returns statistical summaries, columns, head rows, specific value counts, correlations, etc.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the .xlsx file.",
                    },
                    "query_type": {
                        "type": "string",
                        "enum": [
                            "summary", "columns", "head", "tail", "describe",
                            "shape", "dtypes", "value_counts", "unique", "missing", "corr",
                        ],
                        "description": "Type of analysis to perform.",
                    },
                    "column": {
                        "type": "string",
                        "description": "Target column name for value_counts, unique, or describe.",
                    },
                    "n_rows": {
                        "type": "integer",
                        "description": "Number of rows to return for head/tail (default 5).",
                    },
                },
                "required": ["file_path", "query_type"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "generate_chart",
            "description": "Generate a chart from Excel data and save it as a PNG image.",
            "parameters": {
                "type": "object",
                "properties": {
                    "file_path": {
                        "type": "string",
                        "description": "Absolute path to the .xlsx file.",
                    },
                    "x_column": {
                        "type": "string",
                        "description": "Column name for X-axis (or labels for pie chart).",
                    },
                    "y_column": {
                        "type": "string",
                        "description": "Column name for Y-axis (or values for pie chart).",
                    },
                    "chart_type": {
                        "type": "string",
                        "enum": ["bar", "line", "pie", "scatter", "hist"],
                        "description": "Chart type.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Optional title for the chart.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path where the PNG file will be saved.",
                    },
                },
                "required": ["file_path", "x_column", "output_path"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "export_pdf_report",
            "description": "Generate a professional PDF report with text summary and optional chart.",
            "parameters": {
                "type": "object",
                "properties": {
                    "summary_text": {
                        "type": "string",
                        "description": "The main text content / analysis summary for the report body.",
                    },
                    "output_path": {
                        "type": "string",
                        "description": "Path where the PDF file will be saved.",
                    },
                    "chart_path": {
                        "type": "string",
                        "description": "Optional path to a chart image (PNG) to embed.",
                    },
                    "title": {
                        "type": "string",
                        "description": "Report title (default: REMO_OX Financial Report).",
                    },
                },
                "required": ["summary_text", "output_path"],
            },
        },
    },
]


def _execute_tool_directly(tool_name: str, arguments: dict) -> str:
    """Fallback to direct execution from mcp_server module."""
    try:
        if tool_name == "analyze_data":
            return mcp_server.analyze_data(
                file_path=arguments.get("file_path", ""),
                query_type=arguments.get("query_type", "summary"),
                column=arguments.get("column", ""),
                n_rows=int(arguments.get("n_rows", 5)),
            )
        elif tool_name == "generate_chart":
            return mcp_server.generate_chart(
                file_path=arguments.get("file_path", ""),
                x_column=arguments.get("x_column", ""),
                y_column=arguments.get("y_column", ""),
                chart_type=arguments.get("chart_type", "bar"),
                title=arguments.get("title", ""),
                output_path=arguments.get("output_path", ""),
            )
        elif tool_name == "export_pdf_report":
            return mcp_server.export_pdf_report(
                summary_text=arguments.get("summary_text", ""),
                output_path=arguments.get("output_path", ""),
                chart_path=arguments.get("chart_path", ""),
                title=arguments.get("title", "REMO_OX Financial Report"),
            )
        else:
            return json.dumps({"error": f"Unknown tool: {tool_name}"})
    except Exception as e:
        logger.exception("Direct tool execution failed")
        return json.dumps({"error": str(e)})


async def get_mcp_tools(server_url: str = MCP_SERVER_URL) -> list[dict]:
    """
    Connect to the MCP server and retrieve available tool definitions.
    Falls back to built-in schemas if SSE retrieval encounters any issue.
    """
    try:
        async with sse_client(server_url) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                tools = []
                for tool in result.tools:
                    tools.append({
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
                    })
                if tools:
                    return tools
    except Exception as e:
        logger.info(f"Using default tool definitions (SSE retrieval info: {e})")
    return DEFAULT_TOOLS


async def call_mcp_tool(
    tool_name: str,
    arguments: dict,
    server_url: str = MCP_SERVER_URL,
) -> str:
    """
    Call a specific tool on the MCP server.
    First tries SSE; falls back to direct execution if SSE fails or raises error.
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
                return json.dumps({"result": "Tool executed."})
    except Exception as e:
        logger.info(f"SSE call bypassed, executing directly: {tool_name} ({e})")
        return _execute_tool_directly(tool_name, arguments)


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
    file_info: dict | None = None,
) -> tuple[str, list[dict], list[str]]:
    """
    Send a chat message to the LLM with MCP tool definitions and handle
    the complete tool-calling loop automatically.
    """
    # Fetch available tools from MCP server (or fallback)
    tools = await get_mcp_tools(server_url)

    # Build system prompt, enriched with current file info if present
    sys_prompt = SYSTEM_PROMPT
    if file_info and file_info.get("columns"):
        fname = file_info.get("original_name", "data.xlsx")
        rows = file_info.get("row_count", "unknown")
        cols_desc = ", ".join(
            [f"'{c['name']}' ({c.get('dtype', '')})" for c in file_info["columns"]]
        )
        sys_prompt += (
            f"\n\n**Current Dataset Info:**\n"
            f"File: '{fname}' ({rows} rows).\n"
            f"Columns: {cols_desc}.\n"
            f"Always call analyze_data or generate_chart directly with these columns "
            f"to answer the user's question with precise data."
        )

    full_messages = [{"role": "system", "content": sys_prompt}] + [
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

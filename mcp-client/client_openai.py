"""
Simple MCP client using the OpenAI SDK + MCP Python SDK.

This is the "OpenAI SDK" variant of client.py. Instead of LangChain + QGenie,
it uses:
  - the official MCP Python SDK (`mcp`) to connect to the doc-rag server over
    streamable HTTP and discover/call its tools, and
  - the OpenAI SDK (`openai`) for the LLM, using OpenAI's function/tool-calling
    loop to decide when to invoke the MCP tools.

MCP config:
  "doc-rag": {
      "type": "streamableHttp",
      "url": "http://djou-linux:8011/rag/mcp"
  }

Install:
  pip install openai mcp

Run:
  # Point at any OpenAI-compatible endpoint via OPENAI_API_KEY / OPENAI_BASE_URL.
  python client_openai.py
"""

import asyncio
import json
import os

from openai import AsyncOpenAI
from mcp import ClientSession
from mcp.client.streamable_http import streamablehttp_client

SERVER_URL = "http://djou-linux:8011/rag/mcp"

# OpenAI (or OpenAI-compatible) model + client.
# Set OPENAI_API_KEY (and optionally OPENAI_BASE_URL for a compatible gateway).
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o-mini")
openai_client = AsyncOpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url=os.getenv("OPENAI_BASE_URL"),  # None -> default OpenAI endpoint
)

SYSTEM_PROMPT = (
    "You are a document RAG assistant. Use the available tools to search the "
    "ingested documents and answer the user's question. Cite the source file "
    "and page when you can."
)


def mcp_tools_to_openai_schema(mcp_tools):
    """Convert MCP tool definitions into OpenAI 'tools' (function) schema."""
    openai_tools = []
    for tool in mcp_tools:
        openai_tools.append(
            {
                "type": "function",
                "function": {
                    "name": tool.name,
                    "description": tool.description or "",
                    # MCP exposes a JSON Schema for inputs; OpenAI expects the same shape.
                    "parameters": tool.inputSchema,
                },
            }
        )
    return openai_tools


async def run_agent(question: str) -> str:
    # 1) Open a streamable HTTP connection to the MCP server.
    async with streamablehttp_client(SERVER_URL) as (read, write, _):
        # 2) Start an MCP session over that transport.
        async with ClientSession(read, write) as session:
            await session.initialize()

            # 3) Discover the server's tools and convert to OpenAI tool schema.
            tools_result = await session.list_tools()
            openai_tools = mcp_tools_to_openai_schema(tools_result.tools)
            print("Loaded MCP tools:", [t.name for t in tools_result.tools])

            # 4) Seed the conversation.
            messages = [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": question},
            ]

            # 5) Tool-calling loop: keep letting the model call tools until it
            #    produces a final answer (no more tool calls).
            while True:
                response = await openai_client.chat.completions.create(
                    model=OPENAI_MODEL,
                    messages=messages,
                    tools=openai_tools,
                )
                msg = response.choices[0].message

                # No tool calls -> this is the final answer.
                if not msg.tool_calls:
                    return msg.content

                # Record the assistant turn (with its requested tool calls).
                messages.append(
                    {
                        "role": "assistant",
                        "content": msg.content or "",
                        "tool_calls": [tc.model_dump() for tc in msg.tool_calls],
                    }
                )

                # 6) Execute each requested tool call against the MCP server.
                for tool_call in msg.tool_calls:
                    name = tool_call.function.name
                    args = json.loads(tool_call.function.arguments or "{}")

                    result = await session.call_tool(name, args)

                    # MCP returns content blocks; join their text for the model.
                    text = "".join(
                        getattr(block, "text", "") for block in result.content
                    )

                    # Feed the tool result back so the model can continue.
                    messages.append(
                        {
                            "role": "tool",
                            "tool_call_id": tool_call.id,
                            "content": text,
                        }
                    )


async def main():
    answer = await run_agent("What is CoWoS packaging?")
    print("\n=== Answer ===")
    print(answer)


if __name__ == "__main__":
    asyncio.run(main())
"""
Simple MCP client using QGenie (LLM) + LangChain agent.

Loads the doc-rag MCP tools over streamable HTTP, binds them to a QGenie chat
model via a LangChain agent, and answers a question (RAG) by letting the agent
call the `search_docs` / `get_chunk` / `get_document` tools as needed.

MCP config:
  "doc-rag": {
      "type": "streamableHttp",
      "url": "http://djou-linux:8011/rag/mcp"
  }
"""

import asyncio

from langchain_mcp_adapters.client import MultiServerMCPClient
from langchain.agents import create_agent
from qgenie.integrations.langchain import QGenieChat

SERVER_URL = "http://djou-linux:8011/rag/mcp"


async def main():
    # Connect to the doc-rag MCP server and load its tools as LangChain tools.
    mcp_client = MultiServerMCPClient(
        {
            "doc-rag": {
                "transport": "streamable_http",
                "url": SERVER_URL,
            }
        }
    )
    tools = await mcp_client.get_tools()
    print("Loaded MCP tools:", [t.name for t in tools])

    # QGenie chat model (the LLM that drives the agent).
    model = QGenieChat(
        model="anthropic::claude-4-8-opus",
        max_tokens=4000,
        temperature=0.0,
    )

    # Build a tool-using agent.
    agent = create_agent(
        model,
        tools=tools,
        system_prompt=(
            "You are a document RAG assistant. Use the available tools to search "
            "the ingested documents and answer the user's question. Cite the "
            "source file and page when you can."
        ),
    )

    question = "What is CoWoS packaging?"
    result = await agent.ainvoke({"messages": [{"role": "user", "content": question}]})

    # Print the final answer.
    print("\n=== Answer ===")
    print(result["messages"][-1].content)


if __name__ == "__main__":
    asyncio.run(main())
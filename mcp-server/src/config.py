"""
Configuration module for the Document RAG MCP Server.

Loads environment variables for the ChromaDB connection and server binding.
No database credentials or auth configuration are required — ChromaDB is a local
persistent store created by the pdf-parser / pptx-parser skills.
"""

import os
from dotenv import load_dotenv


class ChromaConfig:
    """Configuration for the ChromaDB connection and server runtime."""

    def __init__(self):
        """Initialize configuration by loading environment variables."""
        load_dotenv()

        # ChromaDB settings
        self.db_path = os.getenv("CHROMA_DB_PATH", "../chroma_db")
        self.collection = os.getenv("CHROMA_COLLECTION", "documents")

        # Server settings
        self.host = os.getenv("HOST", "0.0.0.0")
        self.port = int(os.getenv("PORT", "8011"))
        self.mcp_path = os.getenv("MCP_PATH", "rag")

        self._validate()

    def _validate(self) -> None:
        """Validate required configuration values."""
        if not self.db_path:
            raise ValueError("CHROMA_DB_PATH must be set")
        if not self.collection:
            raise ValueError("CHROMA_COLLECTION must be set")

    def get_safe_info(self) -> dict:
        """Return non-sensitive config info for logging/health."""
        return {
            "db_path": os.path.abspath(self.db_path),
            "collection": self.collection,
            "host": self.host,
            "port": self.port,
            "mcp_path": self.mcp_path,
        }
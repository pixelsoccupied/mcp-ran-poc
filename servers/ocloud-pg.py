"""
PostgreSQL MCP Server - Natural Language SQL Query Interface
A Model Context Protocol server for querying PostgreSQL databases.
"""

import json
import logging
import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, Optional

import asyncpg
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class PostgresContext:
    """Shared context for PostgreSQL operations"""
    connections: Optional[Dict[str, asyncpg.Connection]] = None


@asynccontextmanager
async def postgres_lifespan(server: FastMCP) -> AsyncIterator[PostgresContext]:
    """Initialize PostgreSQL connections and clean up on shutdown"""
    logger.info("Initializing PostgreSQL MCP Server...")

    # Database configurations - add more as needed
    databases = {
        "main": {
            "host": os.getenv("POSTGRES_HOST", "localhost"),
            "port": int(os.getenv("POSTGRES_PORT", 5432)),
            "database": os.getenv("POSTGRES_DB", "postgres"),
            "user": os.getenv("POSTGRES_USER", "postgres"),
            "password": os.getenv("POSTGRES_PASSWORD", "password")
        }
    }

    connections = {}

    try:
        # Connect to all configured databases
        for db_name, config in databases.items():
            try:
                conn = await asyncpg.connect(**config)
                connections[db_name] = conn
                logger.info(f"Connected to database: {db_name}")
            except Exception as e:
                logger.error(f"Failed to connect to {db_name}: {e}")

        ctx = PostgresContext(connections=connections if connections else None)
        if not connections:
            logger.warning("No database connections established")
        yield ctx

    except Exception as e:
        logger.error(f"Failed to initialize PostgreSQL server: {e}")
        raise
    finally:
        logger.info("Shutting down PostgreSQL MCP Server...")
        if connections:
            for conn in connections.values():
                try:
                    await conn.close()
                except Exception as e:
                    logger.warning(f"Error closing connection: {e}")


# Create FastMCP server with lifespan
mcp = FastMCP("PostgreSQL MCP Server", lifespan=postgres_lifespan)


@mcp.tool()
async def execute_query(database: str, query: str) -> str:
    """Execute a read-only SQL query on a specified database.

    This tool allows Claude to run SELECT queries to retrieve data, check table schemas,
    list tables, or perform any read-only database operation.

    Args:
        database: Name of the database to query (e.g., "main")
        query: SQL SELECT query to execute

    Returns:
        JSON string with query results including data, row count, and column names

    Example queries:
        - List tables: SELECT table_name FROM information_schema.tables WHERE table_schema = 'public'
        - Show schema: SELECT column_name, data_type FROM information_schema.columns WHERE table_name = 'users'
        - Get data: SELECT * FROM customers WHERE created_at > '2024-01-01' LIMIT 10
    """
    try:
        # Validate query is read-only
        query_upper = query.strip().upper()
        if not query_upper.startswith(("SELECT", "WITH")):
            raise ToolError("Only SELECT queries are allowed for safety")

        # Get connection from context
        ctx = mcp.get_context()
        lifespan_ctx = ctx.request_context.lifespan_context
        assert isinstance(lifespan_ctx, PostgresContext), "Invalid lifespan context type"

        if not lifespan_ctx.connections:
            raise ToolError("No database connections available")

        if database not in lifespan_ctx.connections:
            available = list(lifespan_ctx.connections.keys())
            raise ToolError(f"Database '{database}' not found. Available: {available}")

        conn = lifespan_ctx.connections[database]

        # Execute query
        rows = await conn.fetch(query)

        # Convert to list of dicts
        results = [dict(row) for row in rows] if rows else []

        return json.dumps({
            "success": True,
            "query": query,
            "result": results,
            "count": len(results),
            "columns": list(results[0].keys()) if results else [],
            "message": "Query executed successfully" if results else "Query executed successfully, no rows returned"
        }, indent=2, default=str)

    except asyncpg.PostgresSyntaxError as e:
        raise ToolError(f"SQL syntax error: {str(e)}")
    except Exception as e:
        logger.error(f"Failed to execute query: {e}")
        raise ToolError(f"Query execution failed: {str(e)}")


def main() -> None:
    """Main entry point for the PostgreSQL MCP Server"""
    mcp.run()


if __name__ == "__main__":
    main()
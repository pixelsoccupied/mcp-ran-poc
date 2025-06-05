# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains two MCP servers:

1. **TALM MCP Server** (`servers/talm.py`): A TALM (Topology Aware Lifecycle Manager) MCP Server for Red Hat Advanced Cluster Management (ACM). It provides a Model Context Protocol interface to manage Kubernetes cluster lifecycle operations through ACM's TALM framework.

2. **PostgreSQL MCP Server** (`servers/ocloud-pg.py`): A natural language SQL query interface for PostgreSQL databases. Allows Claude to execute read-only SQL queries safely.

## Development Commands

### Setup and Dependencies
```bash
# Install dependencies using uv
uv sync

# Run the TALM server in stdio mode (default)
uv run python servers/talm.py

# Run the TALM server with HTTP transport
uv run python servers/talm.py --transport streamable-http --port 8080

# Run the PostgreSQL server in stdio mode
uv run python servers/ocloud-pg.py

# Run the PostgreSQL server with HTTP transport
uv run python servers/ocloud-pg.py --transport streamable-http --port 8081
```

### Testing Server Functionality

#### TALM Server
```bash
# Test server connectivity (requires running MCP client)
# The TALM server provides these key endpoints when running:
# - Resources: talm://clusters, talm://policies, talm://clusters/{name}/status  
# - Tools: server_status(), remediate_cluster(), check_cluster_health(), list_active_cgus()
# - Prompts: remediate_cluster_prompt(), cluster_health_audit(), batch_remediation_prompt()
```

#### PostgreSQL Server
```bash
# Test PostgreSQL server functionality (requires running MCP client)
# The PostgreSQL server provides:
# - Tools: execute_query(database, query) - Execute read-only SQL queries
# Environment variables required:
# - POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
```

## Architecture Overview

### TALM Server Architecture

#### Core Components

**TALMContext**: Shared context class that manages Kubernetes client connections:
- `k8s_client`: Core Kubernetes API client (used for connection testing and creating dynamic client)
- `dynamic_client`: Dynamic client for all CRD operations (ManagedCluster, Policy, ClusterGroupUpgrade)

**Lifespan Management**: The `talm_lifespan()` function handles:
- Kubernetes configuration loading (in-cluster → local kubeconfig → mock mode)
- Client initialization and connection validation
- Graceful fallback to offline mode when cluster unavailable

**MCP Categories**:
- **Resources**: Read-only data access (clusters, policies, status) - returns structured objects (dicts/lists)
- **Tools**: Actions with side effects (remediation, health checks) - returns structured objects for analysis
- **Prompts**: Reusable templates for common workflows

### Key CRD Integrations

The server integrates with these ACM/TALM Custom Resource Definitions:

- **ManagedCluster** (`cluster.open-cluster-management.io/v1`): Cluster inventory and status
- **Policy** (`policy.open-cluster-management.io/v1`): Compliance policies
- **ClusterGroupUpgrade** (`ran.openshift.io/v1alpha1`): TALM upgrade operations

### Error Handling Strategy

The server implements graceful degradation:
- Mock context when kubeconfig unavailable
- Limited context when cluster connection fails  
- JSON error responses with helpful diagnostic information
- Offline mode detection in all resource/tool functions

### State Management

- Server uses lifespan context pattern to share K8s clients across requests
- CGU operations create timestamped resources for tracking
- Default namespace `ztp-install` for TALM operations
- No persistent state - all data comes from live cluster queries

#### TALM Implementation Details

- Uses FastMCP framework with asyncio lifespan management
- Kubernetes client connections are validated on startup
- All CRD operations use dynamic client for flexibility
- ClusterGroupUpgrade creation follows TALM patterns (batching, timeouts)
- Server can run in stdio or HTTP transport modes

#### TALM API Data Format

**Resources and Tools Return Format**: All resources and tools return structured Python objects (dictionaries and lists) rather than JSON strings. This makes the data easier for AI systems to parse and analyze:

- **Resources**: `list_clusters()` and `list_policies()` return `List[Dict[str, Any]]`
- **Status Resources**: `get_cluster_status()` returns `Dict[str, Any]` 
- **Tools**: `check_cluster_health()` and `list_active_cgus()` return structured objects
- **Kubernetes Objects**: All K8s objects are converted using `.to_dict()` for JSON serialization
- **Tools with Side Effects**: `remediate_cluster()` and `server_status()` still return JSON strings for backward compatibility

### PostgreSQL Server Architecture

#### Core Components

**PostgresContext**: Shared context class that manages PostgreSQL connections:
- `connections`: Dictionary of database name to `asyncpg.Connection` objects
- Supports multiple database connections simultaneously

**Lifespan Management**: The `postgres_lifespan()` function handles:
- Database connection initialization from environment variables
- Connection validation and error handling
- Graceful connection cleanup on shutdown

#### PostgreSQL Implementation Details

- Uses FastMCP framework with asyncio lifespan management
- PostgreSQL connections use `asyncpg` for async database operations
- Read-only query validation (only SELECT and WITH queries allowed)
- JSON response format with query metadata (results, count, columns, executed query)
- Environment-based configuration for database credentials

#### PostgreSQL API Data Format

**Tools Return Format**: The `execute_query` tool returns JSON strings with structured data:

```json
{
  "success": true,
  "query": "SELECT * FROM users LIMIT 5",
  "result": [{"id": 1, "name": "John"}],
  "count": 1,
  "columns": ["id", "name"],
  "message": "Query executed successfully"
}
```

#### Security Features

- Read-only operation enforcement (SELECT/WITH queries only)
- SQL injection protection through parameterized queries
- Environment variable-based credential management
- Connection pooling and proper cleanup
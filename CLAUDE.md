# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This repository contains MCP servers and an ADK agent for database querying and Kubernetes cluster management:

1. **TALM MCP Server** (`servers/talm.py`): A TALM (Topology Aware Lifecycle Manager) MCP Server for Red Hat Advanced Cluster Management (ACM). It provides a Model Context Protocol interface to manage Kubernetes cluster lifecycle operations through ACM's TALM framework.

2. **PostgreSQL MCP Server** (`servers/ocloud-pg.py`): A multi-database natural language SQL query interface for PostgreSQL databases. Supports three databases (alarms, resources, clusters) with intelligent database selection and allows Claude to execute read-only SQL queries safely.

3. **ADK Agent** (`clients/adk-agents/`): A Google ADK agent that provides a web-based natural language interface to the PostgreSQL MCP server for database querying and analysis.

## Development Commands

### Setup and Dependencies
```bash
# Install dependencies using uv
uv sync

# Run the TALM server in stdio mode (default)
uv run python servers/talm.py

# Run the TALM server with HTTP transport
uv run python servers/talm.py --transport streamable-http --port 3001

# Run the PostgreSQL server in stdio mode
uv run python servers/ocloud-pg.py

# Run the PostgreSQL server with HTTP transport
uv run python servers/ocloud-pg.py --transport streamable-http --port 3000

# Run the ADK agent web interface
cd clients && adk web
```

### Container Build and Deployment Commands
```bash
# Build Docker image for multiple architectures
make build                    # Build Docker image with linux/amd64 platform
make push                     # Push image to registry
make dev-build-push          # Build and push with dev tag

# OpenShift deployment
make deploy                   # Deploy to OpenShift using kustomize
make undeploy                # Remove deployment from OpenShift

# Setup for deployment
cp .env.example .env         # Copy environment template
# Edit .env with PostgreSQL and OpenAI credentials
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
# - Tools: select_database(query_description) - AI-driven database selection
# - Tools: execute_query(database, query) - Execute read-only SQL queries with exploration guidance
# - Tools: list_all_databases() - List available databases with connection status
# Environment variables required:
# Legacy (backward compatibility): POSTGRES_HOST, POSTGRES_PORT, POSTGRES_DB, POSTGRES_USER, POSTGRES_PASSWORD
# Multi-database: ALARMS_DB_*, RESOURCES_DB_*, CLUSTERS_DB_* (see .env.example)
```

#### ADK Agent
```bash
# Run the ADK agent web interface to interact with PostgreSQL MCP server
cd clients && adk web
# Access the web interface at http://localhost:8000
# The agent provides natural language interface to PostgreSQL databases
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
- Supports three databases simultaneously: alarms, resources, clusters
- Intelligent database selection based on query intent

**Lifespan Management**: The `postgres_lifespan()` function handles:
- Multi-database connection initialization from environment variables
- Connection validation and error handling for each database
- Graceful connection cleanup on shutdown

#### PostgreSQL Implementation Details

- Uses FastMCP framework with asyncio lifespan management
- PostgreSQL connections use `asyncpg` for async database operations
- Read-only query validation (only SELECT and WITH queries allowed)
- JSON response format with query metadata (results, count, columns, executed query)
- Multi-database environment configuration with fallback to legacy variables
- Intelligent database selection using keyword-based AI recommendations

#### Multi-Database Architecture

**Three Database Types**:
- **Alarms Database**: Monitoring, alerting, incidents, notifications, and fault data
- **Resources Database**: Infrastructure inventory, compute, storage, network resources  
- **Clusters Database**: Kubernetes clusters, nodes, workloads, and cluster management data

**AI-Driven Database Selection**:
- `select_database()` tool analyzes query descriptions and recommends appropriate database
- Keyword matching system for intelligent routing
- Confidence scoring for database recommendations
- Support for querying multiple databases when intent is unclear

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

### ADK Agent Architecture

#### Core Components

**LlmAgent**: The main agent class that provides natural language interface:
- Uses OpenAI GPT-4o model via LiteLlm integration
- Named 'enterprise_assistant' for both PostgreSQL database and TALM cluster operations
- Configured with specialized instructions for database querying and cluster management

**MCPToolset**: Integration with dual MCP servers:
- Connects to PostgreSQL MCP server via HTTP transport at `http://localhost:3000/mcp`
- Connects to TALM MCP server via HTTP transport at `http://localhost:3001/mcp`
- Provides access to database and cluster management tools
- Automatically handles MCP protocol communication for both servers

#### ADK Agent Features

**Database Operations:**
- **Natural Language SQL**: Converts user questions into proper SQL queries
- **Query Explanation**: Explains SQL reasoning before execution
- **Result Analysis**: Provides insights and analysis of query results
- **Schema Exploration**: Helps users understand database structure

**Cluster Management Operations:**
- **Cluster Status Monitoring**: Check health and status of managed clusters
- **Policy Management**: List and analyze cluster compliance policies
- **Cluster Remediation**: Perform remediation operations on clusters
- **CGU Operations**: Monitor and manage cluster group upgrades

**Cross-Platform Features:**
- **Unified Interface**: Single natural language interface for both systems
- **Session Memory**: Maintains context across database and cluster operations
- **Safety First**: Read-only database operations and TALM-validated cluster operations

#### Integration Architecture

```
User Input (Natural Language)
    ↓
ADK Agent (GPT-4o + Instructions)
    ↓
Dual MCPToolset (HTTP Transport)
    ├── PostgreSQL MCP Server (localhost:3000/mcp)
    │   ├── execute_query tool
    │   └── PostgreSQL Database (Read-only queries)
    └── TALM MCP Server (localhost:3001/mcp)
        ├── Cluster management tools
        ├── Policy management tools
        └── Kubernetes Clusters (via ACM/TALM)
```

## OpenShift Deployment Architecture

### Container Strategy
- **Unified Docker Image**: Single container image contains all components (PostgreSQL MCP server, TALM MCP server, ADK agent)
- **Multi-platform Build**: Built for linux/amd64 to ensure compatibility with OpenShift nodes
- **Command Override**: Different Kubernetes commands run different services from the same image

### OpenShift-Specific Considerations
- **Security Context Constraints**: Uses OpenShift's restricted-v2 SCC
- **Non-root User**: Runs as arbitrary user ID assigned by OpenShift (member of root group)
- **File Permissions**: Uses `chgrp -R 0 /app && chmod -R g=u /app` for proper group permissions
- **UV Cache Directory**: Configured at `/app/.cache/uv` with group write permissions

### Deployment Components
- **Namespace**: `mcp-poc` - dedicated project for POC
- **Single Pod**: Three containers in same pod sharing localhost networking
  - PostgreSQL MCP server (port 3000)
  - TALM MCP server (port 3001)
  - ADK web interface (port 8000)
- **Secret**: Generated from `.env` file using kustomize secretGenerator
- **Service**: Exposes all ports (3000 for PostgreSQL MCP, 3001 for TALM MCP, 8000 for web)
- **Route**: OpenShift-specific external access with TLS termination

### Environment Configuration
Required environment variables managed via Kubernetes secret:
- `POSTGRES_HOST`: Use Kubernetes DNS format (e.g., `postgres-service.namespace.svc.cluster.local`)
- `POSTGRES_PORT`, `POSTGRES_DB`, `POSTGRES_USER`, `POSTGRES_PASSWORD`: Database connection details
- `OPENAI_API_KEY`: Required for LiteLlm model in ADK agent
- `POSTGRES_MCP_URL`: Automatically set to `http://localhost:3000/mcp` for pod-local communication
- `TALM_MCP_URL`: Automatically set to `http://localhost:3001/mcp` for pod-local communication

### Networking
- **Pod-local Communication**: ADK web client connects to both MCP servers via localhost
  - PostgreSQL MCP server: `http://localhost:3000/mcp`
  - TALM MCP server: `http://localhost:3001/mcp`
- **External Access**: Only web interface (port 8000) exposed via OpenShift Route
- **TLS**: Automatic HTTPS with edge termination and redirect from HTTP

### Key Files
- `Dockerfile`: Multi-service container with OpenShift-compatible permissions
- `deployment.yaml`: Kubernetes manifests for all resources
- `kustomization.yaml`: Kustomize configuration with secret generation
- `Makefile`: Build and deployment automation
- `.env.example`: Template for required environment variables
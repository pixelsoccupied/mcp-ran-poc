# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

This is a TALM (Topology Aware Lifecycle Manager) MCP Server for Red Hat Advanced Cluster Management (ACM). It provides a Model Context Protocol interface to manage Kubernetes cluster lifecycle operations through ACM's TALM framework.

## Development Commands

### Setup and Dependencies
```bash
# Install dependencies using uv
uv sync

# Run the server in stdio mode (default)
uv run python server.py

# Run the server with HTTP transport
uv run python server.py --transport streamable-http --port 8080
```

### Testing Server Functionality
```bash
# Test server connectivity (requires running MCP client)
# The server provides these key endpoints when running:
# - Resources: talm://clusters, talm://policies, talm://clusters/{name}/status  
# - Tools: server_status(), remediate_cluster(), check_cluster_health(), list_active_cgus()
# - Prompts: remediate_cluster_prompt(), cluster_health_audit(), batch_remediation_prompt()
```

## Architecture Overview

### Core Components

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

## Key Implementation Details

- Uses FastMCP framework with asyncio lifespan management
- Kubernetes client connections are validated on startup
- All CRD operations use dynamic client for flexibility
- ClusterGroupUpgrade creation follows TALM patterns (batching, timeouts)
- Server can run in stdio or HTTP transport modes

### API Data Format

**Resources and Tools Return Format**: All resources and tools return structured Python objects (dictionaries and lists) rather than JSON strings. This makes the data easier for AI systems to parse and analyze:

- **Resources**: `list_clusters()` and `list_policies()` return `List[Dict[str, Any]]`
- **Status Resources**: `get_cluster_status()` returns `Dict[str, Any]` 
- **Tools**: `check_cluster_health()` and `list_active_cgus()` return structured objects
- **Kubernetes Objects**: All K8s objects are converted using `.to_dict()` for JSON serialization
- **Tools with Side Effects**: `remediate_cluster()` and `server_status()` still return JSON strings for backward compatibility
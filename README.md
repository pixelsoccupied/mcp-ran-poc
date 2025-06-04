# mcp-talm-poc

**⚠️ WARNING: THIS IS A PROOF OF CONCEPT (POC) - NOT FOR PRODUCTION USE ⚠️**

TALM (Topology Aware Lifecycle Manager) MCP Server for Red Hat Advanced Cluster Management.

## Quick Start

### Install Dependencies
```bash
uv sync
```

### Configure MCP Client
Add this configuration to your MCP client (adjust paths for your system):

```json
{
 "mcpServers": {
  "talm": {
   "command": "/path/to/uv",
   "args": [
    "run", 
    "--directory", "/path/to/mcp-talm-poc",
    "python", "server.py"
   ],
   "env": {
      "KUBECONFIG": "/path/to/your/kubeconfig.yaml"
   }
  }
 }
}
```

Replace:
- `/path/to/uv` with your uv installation path (find with `which uv`)
- `/path/to/mcp-talm-poc` with this repository's absolute path
- `/path/to/your/kubeconfig.yaml` with your cluster's kubeconfig file

The server provides MCP resources and tools for managing ACM cluster lifecycle operations.
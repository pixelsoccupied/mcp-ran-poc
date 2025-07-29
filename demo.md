# MCP TALM POC Demo

## Architecture Overview

This POC demonstrates the power of Model Context Protocol (MCP) servers as **code repositories** that expose functionality through standardized interfaces.

### MCP Servers (Code Storage)

1. **PostgreSQL MCP Server** (`servers/ocloud-pg.py`)
   - Stores database query logic and schema exploration code
   - Exposes tools: `select_database()`, `execute_query()`, `list_all_databases()`
   - Multi-database support with intelligent routing

2. **TALM MCP Server** (`servers/talm.py`)
   - Stores Kubernetes cluster management code via ACM/TALM
   - Exposes tools: `get_clusters_by_label()`, `create_cgu()`, `get_policies_by_label()`
   - AI-powered conflict detection and safety validations

### Client Flexibility

The MCP architecture enables **any compatible client** to access these servers:

- **Google ADK Agent** (included): Custom AI agent with dual-server integration
- **Claude Desktop**: Connect via stdio transport for direct access
- **Custom Applications**: Any MCP-compatible client can leverage these servers

## Quick Demo

### 1. Local Development
```bash
# Start MCP servers
uv run python servers/ocloud-pg.py --transport streamable-http --port 3000 &
uv run python servers/talm.py --transport streamable-http --port 3001 &

# Launch ADK web interface
cd clients && adk web
```

### 2. OpenShift Deployment
```bash
# Configure environment
cp .env.example .env
# Edit .env with your credentials

# Deploy
make build
make push  
make deploy
```

### 3. Using with Claude Desktop
Add to Claude Desktop config:
```json
{
  "mcpServers": {
    "postgres": {
      "command": "uv",
      "args": ["run", "python", "/path/to/servers/ocloud-pg.py"]
    },
    "talm": {
      "command": "uv",
      "args": ["run", "python", "/path/to/servers/talm.py"]
    }
  }
}
```

## Security Considerations

### Current Implementation
- **Read-only database queries** enforced at MCP server level
- **RBAC integration** for Kubernetes operations (ServiceAccount with admin role)
- **Environment-based secrets** management
- **Input validation** for SQL injection prevention

### Future Security Enhancements
1. **mTLS between MCP clients and servers**
2. **OAuth2/OIDC integration** for user authentication
3. **Audit logging** for all MCP tool invocations
4. **Rate limiting** and quota management
5. **Sandboxed execution** for untrusted code
6. **Policy-based access control** per tool/resource

## Future Development

### Technical Enhancements
- **MCP Server Federation**: Connect multiple MCP servers across clusters
- **Caching Layer**: Redis-based caching for frequent queries
- **Observability**: OpenTelemetry integration for distributed tracing
- **GitOps Integration**: Store MCP server code in Git with automated deployments

### Business Value
- **Reusable Code Libraries**: MCP servers as organizational knowledge repositories
- **Cross-Team Collaboration**: Share validated, secure code patterns
- **Compliance**: Centralized audit trail for all AI-driven operations
- **Multi-Model Support**: Same MCP servers work with GPT-4, Claude, Gemini, etc.

## Key Insights

1. **MCP servers are code containers** - They store and expose arbitrary functionality
2. **Client independence** - Any MCP-compatible client can access the servers
3. **Security by design** - Validation happens at the server level, not client
4. **Scalable architecture** - Add new MCP servers without changing clients

## Try It Yourself

1. Query databases: "Show me all alarms from the last 24 hours"
2. Manage clusters: "List all clusters with label environment=production"
3. Create CGUs: "Create a cluster group upgrade for maintenance"

The beauty of MCP: **Write once, use everywhere** - from ADK agents to Claude Desktop to custom applications.
# MCP RAN POC

**⚠️ WARNING: THIS IS A PROOF OF CONCEPT (POC) - NOT FOR PRODUCTION USE ⚠️**

This repository contains MCP (Model Context Protocol) servers and an ADK agent for database querying and Kubernetes cluster management:

1. **TALM MCP Server** - TALM (Topology Aware Lifecycle Manager) interface for Red Hat ACM
2. **PostgreSQL MCP Server** - Natural language SQL query interface for PostgreSQL databases  
3. **ADK Agent** - Google ADK agent providing web-based natural language interface to PostgreSQL

## Deployment Options

### Local Development
```bash
# Install dependencies
uv sync

# Run PostgreSQL MCP server
uv run python servers/ocloud-pg.py

# Run ADK web interface
cd clients && adk web
```

### OpenShift Container Platform (OCP) Deployment

#### Prerequisites
- OpenShift CLI (`oc`) installed and logged in
- Docker/Podman for building images
- Access to a container registry (quay.io)

#### Quick Deploy
```bash
# 1. Setup environment variables
cp .env.example .env
# Edit .env with your PostgreSQL and OpenAI credentials

# 2. Build and push container image
make dev-build-push

# 3. Deploy to OpenShift
make deploy

# 4. Get application URL
oc get route mcp-app-route -n mcp-poc -o jsonpath='{.spec.host}'
```

#### Available Make Commands
- `make build` - Build Docker image
- `make push` - Push image to registry  
- `make dev-build-push` - Build and push with dev tag
- `make deploy` - Deploy to OpenShift using kustomize
- `make undeploy` - Remove deployment from OpenShift

#### Environment Configuration
Create `.env` file with required variables:
```bash
# PostgreSQL Database Configuration
POSTGRES_HOST=postgres-service.namespace.svc.cluster.local
POSTGRES_PORT=5432
POSTGRES_DB=your-database-name
POSTGRES_USER=your-username
POSTGRES_PASSWORD=your-password

# OpenAI API Configuration  
OPENAI_API_KEY=your-openai-api-key-here
```

#### Deployment Architecture
- **Single Pod Deployment**: Both PostgreSQL MCP server and ADK web client run in the same pod
- **Shared Networking**: ADK client connects to MCP server via localhost
- **External Access**: Only the web interface (port 8000) is exposed via OpenShift Route
- **Security**: TLS termination at the edge, automatic HTTPS redirect

## Local Client Options

### Option 1: Google ADK Web Interface (Recommended)
```bash
cd clients && adk web
```
Access at `http://localhost:8000` for natural language database querying

### Option 2: Claude Desktop Client
Configure MCP servers in Claude Desktop config:

## Configure Claude Desktop Client

Add these configurations to your Claude Desktop config:

#### TALM Server Configuration
```json
{
 "mcpServers": {
  "talm": {
   "command": "uv",
   "args": [
    "run", 
    "python", "servers/talm.py"
   ],
   "cwd": "/path/to/mcp-ran-poc",
   "env": {
      "KUBECONFIG": "/path/to/your/kubeconfig.yaml"
   }
  }
 }
}
```

#### PostgreSQL Server Configuration
```json
{
 "mcpServers": {
  "postgres": {
   "command": "uv",
   "args": [
    "run", 
    "python", "servers/ocloud-pg.py"
   ],
   "cwd": "/path/to/mcp-ran-poc",
   "env": {
      "POSTGRES_HOST": "localhost",
      "POSTGRES_PORT": "5432",
      "POSTGRES_DB": "your_database_name",
      "POSTGRES_USER": "your_username", 
      "POSTGRES_PASSWORD": "your_password"
   }
  }
 }
}
```

#### Working Configuration Example
This format has been tested and works:

```json
{
 "mcpServers": {
  "talm": {
   "command": "/path/to/uv",
   "args": [
    "run", 
    "--directory", "/path/to/mcp-ran-poc/servers",
    "python", "talm.py"
   ],
   "env": {
      "KUBECONFIG": "/path/to/your/kubeconfig.yaml"
   }
  },
  "postgres": {
   "command": "/path/to/uv",
   "args": [
    "run", 
    "--directory", "/path/to/mcp-ran-poc/servers",
    "python", "ocloud-pg.py"
   ],
   "env": {
    "POSTGRES_HOST": "localhost",
    "POSTGRES_PORT": "5432",
    "POSTGRES_DB": "your_database_name",
    "POSTGRES_USER": "your_username",
    "POSTGRES_PASSWORD": "your_password"
   }
  }
 }
}
```

Replace:
- `/path/to/mcp-ran-poc` with this repository's absolute path
- `/path/to/your/kubeconfig.yaml` with your cluster's kubeconfig file
- PostgreSQL environment variables with your actual database credentials

## Server Features

### TALM Server
- **Resources**: Access to managed clusters, policies, and cluster status
- **Tools**: Cluster remediation, health checks, and CGU management
- **Prompts**: Guided workflows for cluster lifecycle operations

### PostgreSQL Server  
- **Tools**: `execute_query(database, query)` - Execute read-only SQL queries safely
- **Security**: Only SELECT and WITH queries allowed
- **Response**: JSON format with query results, metadata, and executed SQL

### ADK Agent
- **Natural Language Interface**: Convert questions to SQL queries automatically
- **Query Explanation**: Shows SQL reasoning before execution
- **Result Analysis**: Provides insights and analysis of database results
- **Schema Exploration**: Helps understand database structure
- **Web Interface**: User-friendly browser-based interaction at `http://localhost:8000`
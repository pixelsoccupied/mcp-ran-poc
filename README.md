# MCP RAN POC

**⚠️ WARNING: THIS IS A PROOF OF CONCEPT (POC) - NOT FOR PRODUCTION USE ⚠️**

This repository contains MCP (Model Context Protocol) servers and an ADK agent for database querying and Kubernetes cluster management:

1. **TALM MCP Server** - TALM (Topology Aware Lifecycle Manager) interface for Red Hat ACM
2. **PostgreSQL MCP Server** - Natural language SQL query interface for PostgreSQL databases  
3. **ADK Agent** - Google ADK agent providing unified web-based natural language interface to both MCP servers

## Architecture Overview

```
┌─────────────────────┐    ┌─────────────────────┐    ┌─────────────────────┐
│   Web Browser       │    │   Claude Desktop    │    │   Other MCP         │
│   + ADK Agent       │    │      Client         │    │    Clients          │
│     :8000           │    │                     │    │                     │
└─────────┬───────────┘    └─────────┬───────────┘    └─────────┬───────────┘
          │                          │                          │
          └──────────────┬───────────┴────────────┬─────────────┘
                         │                        │
                         ▼                        ▼
          ┌─────────────────────────┐   ┌─────────────────────────────────┐
          │   PostgreSQL MCP        │   │      TALM MCP Server            │
          │     Server :3000        │   │        :3001                    │
          └─────────┬───────────────┘   └─────────┬───────────────────────┘
                    │                             │
                    ▼                             ▼
          ┌─────────────────────────┐   ┌─────────────────────────────────┐
          │   PostgreSQL Database   │   │     Kubernetes Clusters         │
          └─────────────────────────┘   └─────────────────────────────────┘
```

## Deployment Options

### Local Development
```bash
# Install dependencies
uv sync

# Run PostgreSQL MCP server (port 3000)
uv run python servers/ocloud-pg.py --transport streamable-http --port 3000

# Run TALM MCP server (port 3001) 
uv run python servers/talm.py --transport streamable-http --port 3001

# Run ADK web interface (connects to both servers)
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
# Multi-Database Configuration
# Alarms Database
ALARMS_DB_HOST=your-postgres-host
ALARMS_DB_PORT=5432
ALARMS_DB_NAME=alarms
ALARMS_DB_USER=alarms
ALARMS_DB_PASSWORD=your-password

# Resources Database
RESOURCES_DB_HOST=your-postgres-host
RESOURCES_DB_PORT=5432
RESOURCES_DB_NAME=resources
RESOURCES_DB_USER=resources
RESOURCES_DB_PASSWORD=your-password

# Clusters Database
CLUSTERS_DB_HOST=your-postgres-host
CLUSTERS_DB_PORT=5432
CLUSTERS_DB_NAME=clusters
CLUSTERS_DB_USER=clusters
CLUSTERS_DB_PASSWORD=your-password

# OpenAI API Configuration
OPENAI_API_KEY=your-openai-api-key-here
OPENAI_MODEL=openai/gpt-4.1

# MCP Server URLs (automatically configured in deployment)
POSTGRES_MCP_URL=http://localhost:3000/mcp
TALM_MCP_URL=http://localhost:3001/mcp
```

#### Deployment Architecture
- **Single Pod Deployment**: Three containers run in the same pod:
  - PostgreSQL MCP server (port 3000)
  - TALM MCP server (port 3001)  
  - ADK web interface (port 8000)
- **Shared Networking**: ADK client connects to both MCP servers via localhost
- **External Access**: Only the web interface (port 8000) is exposed via OpenShift Route
- **Security**: TLS termination at the edge, automatic HTTPS redirect
- **RBAC**: Uses dedicated ServiceAccount with admin ClusterRole for TALM operations

## Local Client Options

### Option 1: Google ADK Web Interface (Recommended)
```bash
cd clients && adk web
```
Access at `http://localhost:8000` for unified natural language interface to both:
- PostgreSQL database querying and analysis
- Kubernetes cluster management via TALM

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
      "ALARMS_DB_HOST": "your-postgres-host",
      "ALARMS_DB_PORT": "5432",
      "ALARMS_DB_NAME": "alarms",
      "ALARMS_DB_USER": "alarms",
      "ALARMS_DB_PASSWORD": "your-password",
      "RESOURCES_DB_HOST": "your-postgres-host",
      "RESOURCES_DB_PORT": "5432",
      "RESOURCES_DB_NAME": "resources",
      "RESOURCES_DB_USER": "resources",
      "RESOURCES_DB_PASSWORD": "your-password",
      "CLUSTERS_DB_HOST": "your-postgres-host",
      "CLUSTERS_DB_PORT": "5432",
      "CLUSTERS_DB_NAME": "clusters",
      "CLUSTERS_DB_USER": "clusters",
      "CLUSTERS_DB_PASSWORD": "your-password"
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
    "ALARMS_DB_HOST": "your-postgres-host",
    "ALARMS_DB_PORT": "5432",
    "ALARMS_DB_NAME": "alarms",
    "ALARMS_DB_USER": "alarms",
    "ALARMS_DB_PASSWORD": "your-password",
    "RESOURCES_DB_HOST": "your-postgres-host",
    "RESOURCES_DB_PORT": "5432",
    "RESOURCES_DB_NAME": "resources",
    "RESOURCES_DB_USER": "resources",
    "RESOURCES_DB_PASSWORD": "your-password",
    "CLUSTERS_DB_HOST": "your-postgres-host",
    "CLUSTERS_DB_PORT": "5432",
    "CLUSTERS_DB_NAME": "clusters",
    "CLUSTERS_DB_USER": "clusters",
    "CLUSTERS_DB_PASSWORD": "your-password"
   }
  }
 }
}
```

Replace:
- `/path/to/mcp-ran-poc` with this repository's absolute path
- `/path/to/your/kubeconfig.yaml` with your cluster's kubeconfig file
- `your-postgres-host` with your PostgreSQL server hostname
- `your-password` with your actual database passwords for each database

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
- **Unified Natural Language Interface**: Handles both database and cluster operations
- **Database Operations**: Convert questions to SQL queries automatically
- **Cluster Operations**: Manage Kubernetes clusters via TALM commands
- **Query Explanation**: Shows SQL reasoning before execution
- **Result Analysis**: Provides insights and analysis of both database and cluster data
- **Schema Exploration**: Helps understand database structure and cluster topology
- **Web Interface**: User-friendly browser-based interaction at `http://localhost:8000`
- **Dual MCP Integration**: Seamlessly connects to both PostgreSQL and TALM MCP servers
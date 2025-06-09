# mcp-ran-poc

**⚠️ WARNING: THIS IS A PROOF OF CONCEPT (POC) - NOT FOR PRODUCTION USE ⚠️**

This repository contains two MCP (Model Context Protocol) servers and one ADK agent:

1. **TALM MCP Server** - TALM (Topology Aware Lifecycle Manager) interface
2. **PostgreSQL MCP Server** - Natural language SQL query interface for PostgreSQL databases
3. **ADK Agent** - Google ADK agent providing natural language interface to PostgreSQL MCP server

## Quick Start

### Install Dependencies
```bash
uv sync
```

## Client Options

You can interact with the MCP servers using two different clients:

### Option 1: Claude Desktop Client
Configure the MCP servers in Claude Desktop config at `~/Library/Application Support/Claude/claude_desktop_config.json`:

### Option 2: Google ADK Agent
For a natural language interface to the PostgreSQL server:
```bash
cd clients && adk web
```
Then access the web interface at `http://localhost:8000`

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
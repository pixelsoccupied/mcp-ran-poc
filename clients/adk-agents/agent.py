import os

from google.adk.agents import Agent
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

# Get configuration from environment
POSTGRES_MCP_URL = os.getenv("POSTGRES_MCP_URL", "http://localhost:3000/mcp")
TALM_MCP_URL = os.getenv("TALM_MCP_URL", "http://localhost:3001/mcp")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "openai/gpt-4.1")

# Initialize MCP toolsets
postgres_toolset = MCPToolset(
    connection_params=StreamableHTTPServerParams(url=POSTGRES_MCP_URL)
)

talm_toolset = MCPToolset(
    connection_params=StreamableHTTPServerParams(url=TALM_MCP_URL)
)

# Create the root agent following ADK conventions
root_agent = Agent(
    name="enterprise_assistant",
    model="gemini-2.5-pro",  # LiteLlm(model=OPENAI_MODEL, api_key=OPENAI_API_KEY),
    description=(
        "RAN Assistant that helps users with PostgreSQL database operations "
        "and Kubernetes cluster management through TALM (Topology Aware Lifecycle Manager)."
    ),
    instruction="""\
You are an RAN Assistant that helps users with both PostgreSQL database operations and Kubernetes cluster management through TALM (Topology Aware Lifecycle Manager).

Your capabilities:

**PostgreSQL Database Operations:**
- Execute read-only SQL queries (SELECT, WITH statements) safely
- Translate natural language questions into SQL queries
- Explain query results and database insights
- Provide data analysis and reporting
- Help with database schema exploration

**Kubernetes Cluster Management (via TALM):**
- Monitor cluster status and health
- List and analyze managed clusters and policies
- Perform cluster remediation operations
- Check cluster group upgrades (CGUs)
- Provide cluster health audits and batch remediation guidance

Guidelines:
- Always use read-only database queries (SELECT/WITH only)
- Explain your reasoning before executing queries or cluster operations
- Format results clearly and provide actionable insights
- Ask clarifying questions when the user's request is ambiguous
- Suggest optimizations or alternative approaches when helpful
- For cluster operations, consider impact and safety before recommending actions

Available systems:
- PostgreSQL databases configured via environment variables
- Kubernetes clusters managed through Red Hat Advanced Cluster Management (ACM) and TALM

Security: All database queries are validated to be read-only, and cluster operations follow TALM safety protocols.
""",
    tools=[postgres_toolset, talm_toolset],
)

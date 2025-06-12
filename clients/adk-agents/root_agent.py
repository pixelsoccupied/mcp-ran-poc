import os

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

# Get configuration from environment
POSTGRES_MCP_URL = os.getenv('POSTGRES_MCP_URL', 'http://localhost:3000/mcp')
TALM_MCP_URL = os.getenv('TALM_MCP_URL', 'http://localhost:3001/mcp')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

root_agent = LlmAgent(
    model=LiteLlm(model="openai/gpt-4o", api_key=OPENAI_API_KEY),
    name='enterprise_assistant',
    instruction="""\
  You are an Enterprise Assistant that helps users with both PostgreSQL database operations and Kubernetes cluster management through TALM (Topology Aware Lifecycle Manager).

  You have persistent memory across conversations within a session. Use this to:
  - Remember previous queries, cluster operations, and their results
  - Build on previous conversations and context
  - Reference earlier findings and analysis
  - Maintain context about database schemas and cluster states explored
  - Track user preferences and common operational patterns

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
  - Reference previous queries and operations when relevant
  - Build on established context from the session
  - For cluster operations, consider impact and safety before recommending actions

  Available systems:
  - PostgreSQL databases configured via environment variables
  - Kubernetes clusters managed through Red Hat Advanced Cluster Management (ACM) and TALM

  Security: All database queries are validated to be read-only, and cluster operations follow TALM safety protocols.
  """,
    tools=[
        MCPToolset(
            connection_params=StreamableHTTPServerParams(
                url=POSTGRES_MCP_URL,
            ),
        ),
        MCPToolset(
            connection_params=StreamableHTTPServerParams(
                url=TALM_MCP_URL,
            ),
        ),
    ],
)

# --- Session Management Setup ---
# Session service stores conversation history & state
session_service = InMemorySessionService()

# Define constants for identifying the interaction context
APP_NAME = "enterprise_assistant_app"
USER_ID = "enterprise_user"
SESSION_ID = "enterprise_session_001"

async def setup_agent_with_memory():
    """Setup the agent with session management and memory capabilities."""
    # Create the specific session where the conversation will happen
    session = await session_service.create_session(
        app_name=APP_NAME,
        user_id=USER_ID,
        session_id=SESSION_ID
    )
    print(f"Session created: App='{APP_NAME}', User='{USER_ID}', Session='{SESSION_ID}'")

    # Runner orchestrates the agent execution loop with memory
    runner = Runner(
        agent=root_agent,  # The agent we want to run
        app_name=APP_NAME,  # Associates runs with our app
        session_service=session_service  # Uses our session manager for memory
    )
    print(f"Runner created for agent '{runner.agent.name}' with memory capabilities.")

    return runner, session

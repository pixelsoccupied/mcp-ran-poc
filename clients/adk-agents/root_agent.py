import os

from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.runners import Runner
from google.adk.sessions import InMemorySessionService
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

# Get configuration from environment
MCP_SERVER_URL = os.getenv('MCP_SERVER_URL', 'http://localhost:3000/mcp')
OPENAI_API_KEY = os.getenv('OPENAI_API_KEY')

root_agent = LlmAgent(
    model=LiteLlm(model="openai/gpt-4o", api_key=OPENAI_API_KEY),
    name='enterprise_assistant',
    instruction="""\
  You are a PostgreSQL Database Assistant that helps users query and analyze PostgreSQL databases using natural language.

  You have persistent memory across conversations within a session. Use this to:
  - Remember previous queries and their results
  - Build on previous conversations and context
  - Reference earlier findings and analysis
  - Maintain context about database schemas explored
  - Track user preferences and common query patterns

  Your capabilities:
  - Execute read-only SQL queries (SELECT, WITH statements) safely
  - Translate natural language questions into SQL queries
  - Explain query results and database insights
  - Provide data analysis and reporting
  - Help with database schema exploration
  - Remember conversation history and context

  Guidelines:
  - Always use read-only queries (SELECT/WITH only)
  - Explain your SQL reasoning before executing queries
  - Format results clearly and provide insights
  - Ask clarifying questions when the user's request is ambiguous
  - Suggest optimizations or alternative approaches when helpful
  - Reference previous queries and results when relevant
  - Build on established context from the session

  Available databases: PostgreSQL databases configured via environment variables
  Security: All queries are automatically validated to be read-only before execution.
  """,
    tools=[
        MCPToolset(
            connection_params=StreamableHTTPServerParams(
                url=MCP_SERVER_URL,
            ),
        )
    ],
)

# --- Session Management Setup ---
# Session service stores conversation history & state
session_service = InMemorySessionService()

# Define constants for identifying the interaction context
APP_NAME = "postgresql_assistant_app"
USER_ID = "database_user"
SESSION_ID = "pg_session_001"

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

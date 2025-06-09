from google.adk.agents.llm_agent import LlmAgent
from google.adk.models.lite_llm import LiteLlm
from google.adk.tools.mcp_tool.mcp_session_manager import StreamableHTTPServerParams
from google.adk.tools.mcp_tool.mcp_toolset import MCPToolset

root_agent = LlmAgent(
    model=LiteLlm(model="openai/gpt-4o"),
    name='enterprise_assistant',
    instruction=f"""\
  You are a PostgreSQL Database Assistant that helps users query and analyze PostgreSQL databases using natural language.

  Your capabilities:
  - Execute read-only SQL queries (SELECT, WITH statements) safely
  - Translate natural language questions into SQL queries
  - Explain query results and database insights
  - Provide data analysis and reporting
  - Help with database schema exploration

  Guidelines:
  - Always use read-only queries (SELECT/WITH only)
  - Explain your SQL reasoning before executing queries
  - Format results clearly and provide insights
  - Ask clarifying questions when the user's request is ambiguous
  - Suggest optimizations or alternative approaches when helpful

  Available databases: PostgreSQL databases configured via environment variables
  Security: All queries are automatically validated to be read-only before execution.
  """,
    tools=[
        MCPToolset(
            connection_params=StreamableHTTPServerParams(
                url='http://localhost:3000/mcp',
            ),
        )
    ],
)
import logging
import time

import gradio as gr
import requests

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = "http://localhost:8000"
DEFAULT_USER_ID = "gradio_user"


def chat_with_agent(message, history, session_id):
    """Chat function with real-time streaming"""

    # Show thinking step
    thinking_response = gr.ChatMessage(
        content="Let me analyze your request and check what tools I need...",
        metadata={"title": "🤔 Thinking", "status": "pending"},
    )
    yield thinking_response, history, session_id

    try:
        # Make streaming request to backend
        payload = {"message": message, "user_id": DEFAULT_USER_ID}

        # Include session_id if we have one
        if session_id:
            payload["session_id"] = session_id

        # Use streaming endpoint for real-time updates
        response = requests.post(
            f"{BACKEND_URL}/chat/stream", json=payload, timeout=120, stream=True
        )

        if response.status_code == 200:
            # Process streaming response
            import json

            tool_steps = []
            current_step = 0
            new_session_id = session_id
            agent_response = ""

            thinking_response.metadata["status"] = "done"

            for line in response.iter_lines(decode_unicode=True):
                if line.startswith("data: "):
                    try:
                        data = json.loads(line[6:])  # Remove "data: " prefix

                        if data["type"] == "tool_step":
                            current_step = data["step"]
                            step_desc = data["description"]
                            new_session_id = data.get("session_id", session_id)

                            # Add this step to our list
                            tool_steps.append(f"{current_step}. {step_desc}")

                            # Create/update the tool usage message
                            tool_content = (
                                "**Real-time Tool Execution:**\n"
                                + "\n".join(tool_steps)
                            )
                            tool_response = gr.ChatMessage(
                                content=tool_content,
                                metadata={
                                    "title": f"🛠️ Step {current_step}",
                                    "status": "pending",
                                },
                            )

                            # Show current progress
                            current_messages = [thinking_response, tool_response]
                            yield current_messages, history, new_session_id

                        elif data["type"] == "final_response":
                            agent_response = data["response"]
                            new_session_id = data.get("session_id", session_id)

                            # Mark tool execution as complete
                            if tool_steps:
                                final_tool_content = (
                                    "**Tool Execution Complete:**\n"
                                    + "\n".join(tool_steps)
                                )
                                final_tool_response = gr.ChatMessage(
                                    content=final_tool_content,
                                    metadata={
                                        "title": "✅ Tools Complete",
                                        "status": "done",
                                    },
                                )
                                final_messages = [
                                    thinking_response,
                                    final_tool_response,
                                    gr.ChatMessage(content=agent_response),
                                ]
                            else:
                                final_messages = [
                                    thinking_response,
                                    gr.ChatMessage(content=agent_response),
                                ]

                            yield final_messages, history, new_session_id
                            return

                        elif data["type"] == "error":
                            error_msg = gr.ChatMessage(
                                content=f"❌ Error: {data['error']}"
                            )
                            yield error_msg, history, session_id
                            return

                    except json.JSONDecodeError as e:
                        logger.debug(f"JSON decode error: {e}")
                        continue

            # Fallback if no final response received
            if not agent_response:
                error_msg = gr.ChatMessage(
                    content="❌ No response received from backend"
                )
                yield error_msg, history, session_id

        else:
            # Fallback to non-streaming endpoint
            response = requests.post(f"{BACKEND_URL}/chat", json=payload, timeout=60)

        if response.status_code == 200:
            data = response.json()
            agent_response = data["response"]
            metadata = data.get("metadata", {})

            # Update session_id for future messages
            new_session_id = data.get("session_id", session_id)

            # Log full response for debugging
            logger.info(f"Backend response metadata: {metadata}")

            # Check if tools were actually used from metadata
            tools_used = metadata.get("tools_used", [])
            tools_count = metadata.get("tools_count", 0)

            if tools_count > 0:
                # Create detailed tool usage message with step-by-step breakdown
                tool_steps = []
                for i, tool in enumerate(tools_used, 1):
                    tool_name = tool.get("name", "Unknown")
                    # Extract meaningful info from arguments
                    args = tool.get("arguments", "")

                    # Parse database and query info for execute_query
                    if tool_name == "execute_query" and "database" in args:
                        try:
                            import re

                            db_match = re.search(r"'database': '(\w+)'", args)
                            query_match = re.search(
                                r"'query': [\"']([^\"']+)[\"']", args
                            )

                            if db_match and query_match:
                                database = db_match.group(1)
                                query = query_match.group(1)

                                # Classify query type
                                if "information_schema.tables" in query:
                                    step_desc = (
                                        f"📋 Exploring {database} database schema"
                                    )
                                elif "information_schema.columns" in query:
                                    step_desc = (
                                        f"🔍 Checking table structure in {database}"
                                    )
                                elif query.upper().startswith("SELECT"):
                                    step_desc = f"📊 Querying {database} database"
                                else:
                                    step_desc = f"🔧 {tool_name} on {database}"
                            else:
                                step_desc = f"🔧 {tool_name}"
                        except Exception:
                            step_desc = f"🔧 {tool_name}"
                    else:
                        step_desc = f"🔧 {tool_name}"

                    tool_steps.append(f"{i}. {step_desc}")

                tool_content = "**Tool Execution Steps:**\n" + "\n".join(tool_steps)

                tool_response = gr.ChatMessage(
                    content=tool_content,
                    metadata={"title": "🛠️ Tool Usage Process", "status": "pending"},
                )
                yield tool_response, history, new_session_id
                time.sleep(1.5)  # Slightly longer to read the steps

                # Mark as done and show final response
                thinking_response.metadata["status"] = "done"
                tool_response.metadata["status"] = "done"
                final_messages = [
                    thinking_response,
                    tool_response,
                    gr.ChatMessage(content=agent_response),
                ]
                yield final_messages, history, new_session_id
            else:
                thinking_response.metadata["status"] = "done"
                final_messages = [
                    thinking_response,
                    gr.ChatMessage(content=agent_response),
                ]
                yield final_messages, history, new_session_id
        else:
            error_msg = gr.ChatMessage(
                content=f"❌ Error: {response.status_code} - {response.text}"
            )
            yield error_msg, history, session_id

    except requests.exceptions.ConnectionError:
        error_msg = gr.ChatMessage(
            content="❌ Cannot connect to backend. Make sure it's running on port 8000."
        )
        yield error_msg, history, session_id
    except Exception as e:
        logger.error(f"Error: {str(e)}")
        error_msg = gr.ChatMessage(content=f"❌ Error: {str(e)}")
        yield error_msg, history, session_id


# Custom interface with proper state management using Blocks
with gr.Blocks(title="RAN Assistant") as demo:
    gr.Markdown("# RAN Assistant")
    gr.Markdown(
        "Chat with your ADK agent for database and cluster operations. Session memory maintained across conversations."
    )

    # Session state
    session_state = gr.State(None)

    # Chat interface
    chatbot = gr.Chatbot(type="messages", height=500)
    msg = gr.Textbox(
        label="Message",
        placeholder="Ask about alarms, clusters, or database queries...",
        container=False,
        scale=7,
    )

    # Examples
    gr.Examples(
        examples=[
            "Show me the latest alarms",
            "What clusters are available?",
            "Check cluster health status",
        ],
        inputs=msg,
    )

    def respond(message, history, session_id):
        if not message.strip():
            return history, "", session_id

        # Add user message to history
        history = history or []
        history.append(gr.ChatMessage(content=message, role="user"))

        # Track session ID through the conversation
        current_session_id = session_id

        # Get agent response with proper state handling
        for response_data in chat_with_agent(message, history, session_id):
            if len(response_data) == 3:
                response_messages, _, updated_session_id = response_data
                current_session_id = updated_session_id

                if isinstance(response_messages, list):
                    # Multiple messages (thinking + tool + response)
                    history = history[:-1] + [history[-1]] + response_messages
                else:
                    # Single message
                    history.append(response_messages)

                yield history, "", current_session_id

        return history, "", current_session_id

    msg.submit(respond, [msg, chatbot, session_state], [chatbot, msg, session_state])

    # Clear button
    def clear_chat():
        return [], None

    clear = gr.Button("Clear Chat")
    clear.click(clear_chat, outputs=[chatbot, session_state])

if __name__ == "__main__":
    demo.launch(server_name="0.0.0.0", server_port=7860)

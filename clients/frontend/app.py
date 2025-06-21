import gradio as gr
import requests
import uuid
import logging
from typing import List, Tuple
import json
import time

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
BACKEND_URL = "http://localhost:8000"
DEFAULT_USER_ID = "gradio_user"

class ADKChatInterface:
    def __init__(self, backend_url: str = BACKEND_URL):
        self.backend_url = backend_url
        self.session_id = str(uuid.uuid4())
        
    def chat(self, message: str, history: List[Tuple[str, str]]) -> str:
        """Send message to ADK agent and return response"""
        if not message:
            return ""
            
        try:
            response = requests.post(
                f"{self.backend_url}/chat",
                json={
                    "message": message,
                    "session_id": self.session_id,
                    "user_id": DEFAULT_USER_ID
                },
                timeout=60  # Increased timeout for complex queries
            )
            
            if response.status_code == 200:
                data = response.json()
                return data["response"]
            else:
                error_detail = response.text
                logger.error(f"Backend error {response.status_code}: {error_detail}")
                return f"Error: {response.status_code} - {error_detail}"
                
        except requests.exceptions.ConnectionError:
            return "❌ Error: Cannot connect to backend. Make sure the ADK backend is running on port 8000."
        except requests.exceptions.Timeout:
            return "⏱️ Error: Request timed out. The agent might be processing a complex request."
        except Exception as e:
            logger.error(f"Error in chat: {str(e)}")
            return f"❌ Error: {str(e)}"
    
    def reset_session(self):
        """Reset the session ID"""
        self.session_id = str(uuid.uuid4())
        return "✅ Session reset successfully!"
    
    def check_backend_health(self):
        """Check if backend is healthy"""
        try:
            response = requests.get(f"{self.backend_url}/health", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return f"🟢 Backend Status: Healthy - Agent: {data.get('agent_name', 'Unknown')}"
            else:
                return f"🟡 Backend Status: Response {response.status_code}"
        except Exception as e:
            return f"🔴 Backend Status: Not Connected - {str(e)[:50]}"
    
    def get_agent_info(self):
        """Get information about the ADK agent"""
        try:
            response = requests.get(f"{self.backend_url}/agent/info", timeout=5)
            if response.status_code == 200:
                return response.json()
            else:
                return {"error": f"Status {response.status_code}"}
        except:
            return {"error": "Cannot connect to backend"}

# Create interface instance
chat_interface = ADKChatInterface()

# Custom CSS for better styling
custom_css = """
#chatbot {
    height: 600px;
}
#status_box {
    padding: 10px;
    border-radius: 5px;
    margin-bottom: 10px;
    font-family: monospace;
}
.status-healthy {
    background-color: #d4edda;
    color: #155724;
}
.status-error {
    background-color: #f8d7da;
    color: #721c24;
}
#agent_info {
    background-color: #f8f9fa;
    padding: 10px;
    border-radius: 5px;
    font-family: monospace;
    font-size: 12px;
}
"""

# Create Gradio interface
with gr.Blocks(css=custom_css, title="RAN Assistant - ADK Agent Chat", theme=gr.themes.Soft()) as demo:
    
    # Header
    gr.HTML("""
    <div style="text-align: center; margin-bottom: 20px;">
        <h1>🤖 RAN Assistant - ADK Agent Chat</h1>
        <p>Chat with your Google ADK agent for PostgreSQL database operations and Kubernetes cluster management</p>
    </div>
    """)
    
    # Status and controls row
    with gr.Row():
        with gr.Column(scale=3):
            status_box = gr.Markdown(
                value="🔴 Backend Status: Checking...",
                elem_id="status_box"
            )
        with gr.Column(scale=1):
            with gr.Row():
                check_btn = gr.Button("🔄 Check Status", size="sm")
                reset_btn = gr.Button("🔄 Reset Session", size="sm")
    
    # Agent info section (collapsible)
    with gr.Accordion("Agent Information", open=False) as agent_accordion:
        agent_info_box = gr.Markdown(
            value="Loading agent information...",
            elem_id="agent_info"
        )
    
    # Main chat interface
    chatbot = gr.Chatbot(
        elem_id="chatbot",
        show_label=False,
        type="messages",
        avatar_images=("👤", "🤖")
    )
    
    # Input area
    with gr.Row():
        msg = gr.Textbox(
            label="Message",
            placeholder="Ask me about database queries, cluster status, or any operations you need help with...",
            lines=2,
            scale=4
        )
        with gr.Column(scale=1, min_width=100):
            submit = gr.Button("Send 📤", variant="primary", size="lg")
            clear = gr.Button("Clear 🗑️", size="lg")
    
    # Example queries section
    with gr.Accordion("Example Queries", open=False):
        gr.Examples(
            examples=[
                # Database queries
                "Show me the latest alarms in the system",
                "What clusters are currently available?",
                "Query the resources database for compute information",
                "Show me database schema information for the alarms table",
                
                # Cluster management
                "Check the health status of all managed clusters",
                "List all policies currently applied",
                "Show me any active cluster group upgrades",
                "Perform a health audit on cluster 'production-01'",
                
                # General
                "What can you help me with?",
                "Explain your capabilities",
            ],
            inputs=msg,
            label="Click on any example to try it"
        )
    
    # Instructions section
    with gr.Accordion("Instructions & Capabilities", open=False):
        gr.Markdown("""
        ### What I can help you with:
        
        **📊 PostgreSQL Database Operations:**
        - Execute read-only SQL queries (SELECT, WITH statements)
        - Translate natural language questions into SQL queries
        - Query alarms, resources, and clusters databases
        - Provide data analysis and insights
        - Help with database schema exploration
        
        **☸️ Kubernetes Cluster Management (via TALM):**
        - Monitor cluster status and health
        - List and analyze managed clusters and policies
        - Perform cluster remediation operations
        - Check cluster group upgrades (CGUs)
        - Provide cluster health audits
        
        **💡 Tips for better results:**
        - Be specific about what data you're looking for
        - Mention which database (alarms, resources, clusters) if known
        - I have persistent memory within your session
        - Ask follow-up questions to dive deeper into results
        """)
    
    # Event handlers
    def user_submit(message, history):
        """Handle user message submission"""
        if not message.strip():
            return "", history
        history = history + [{"role": "user", "content": message}]
        return "", history
    
    def bot_respond(history):
        """Generate bot response"""
        if not history or (history[-1]["role"] == "assistant"):
            return history
            
        user_message = history[-1]["content"]
        
        # Show typing indicator
        history = history + [{"role": "assistant", "content": "🤔 Thinking..."}]
        yield history
        
        # Get actual response - extract previous messages for context
        previous_messages = []
        for msg in history[:-1]:  # Exclude the thinking message
            if msg["role"] == "user":
                previous_messages.append((msg["content"], None))
            elif msg["role"] == "assistant":
                if previous_messages:
                    previous_messages[-1] = (previous_messages[-1][0], msg["content"])
        
        bot_response = chat_interface.chat(user_message, previous_messages)
        history[-1]["content"] = bot_response
        yield history
    
    def check_status():
        """Check backend status"""
        status = chat_interface.check_backend_health()
        return status
    
    def reset_session_and_clear():
        """Reset session and clear chat"""
        message = chat_interface.reset_session()
        return [], message
    
    def load_agent_info():
        """Load agent information"""
        info = chat_interface.get_agent_info()
        if "error" in info:
            return f"❌ Error loading agent info: {info['error']}"
        
        return f"""
**Agent Name:** {info.get('name', 'Unknown')}

**Model:** {info.get('model', 'Unknown')}

**Tools Available:** {info.get('tools_count', 0)} tools

**Instruction Overview:**
{info.get('instruction', 'No instruction available')[:300]}...
        """
    
    # Connect events
    msg.submit(user_submit, [msg, chatbot], [msg, chatbot]).then(
        bot_respond, chatbot, chatbot
    )
    submit.click(user_submit, [msg, chatbot], [msg, chatbot]).then(
        bot_respond, chatbot, chatbot
    )
    clear.click(reset_session_and_clear, None, [chatbot, status_box])
    check_btn.click(check_status, None, status_box)
    reset_btn.click(reset_session_and_clear, None, [chatbot, status_box])
    
    # Load initial status and agent info
    demo.load(check_status, None, status_box)
    demo.load(load_agent_info, None, agent_info_box)

if __name__ == "__main__":
    demo.launch(
        server_name="0.0.0.0",
        server_port=7860,
        show_api=False,
        show_error=True
    )
import os
import sys
import uuid
import asyncio
from pathlib import Path
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import logging

# ADK imports for proper Content handling
from google.genai import types

# Add parent directory to path to import agents
parent_dir = Path(__file__).parent.parent
sys.path.insert(0, str(parent_dir))

# Import the ADK agent using the directory name with hyphens
import importlib.util
spec = importlib.util.spec_from_file_location("root_agent", parent_dir / "adk-agents" / "root_agent.py")
if spec is None or spec.loader is None:
    raise ImportError("Failed to load root_agent module")
root_agent_module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(root_agent_module)

# Extract the needed objects
root_agent = root_agent_module.root_agent
setup_agent_with_memory = root_agent_module.setup_agent_with_memory
APP_NAME = root_agent_module.APP_NAME
USER_ID = root_agent_module.USER_ID
session_service = root_agent_module.session_service

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Configuration
ALLOWED_ORIGINS = ["http://localhost:7860", "http://127.0.0.1:7860"]  # Gradio default ports

# Create FastAPI app
app = FastAPI(title="ADK Agent Backend", version="1.0.0")

# Add CORS middleware for Gradio
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global runner instance
runner = None
session = None

# Custom request/response models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    user_id: str = "gradio_user"
    
class ChatResponse(BaseModel):
    response: str
    session_id: str
    metadata: Dict[str, Any] = {}

# Initialize the agent with memory on startup
@app.on_event("startup")
async def startup_event():
    global runner, session
    try:
        logger.info("Initializing ADK agent with memory...")
        runner, session = await setup_agent_with_memory()
        logger.info("ADK agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize ADK agent: {str(e)}")
        raise

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "ADK Backend",
        "agent_name": root_agent.name,
        "runner_initialized": runner is not None
    }

# Simplified chat endpoint for Gradio integration
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Simplified chat endpoint for Gradio integration using the existing runner"""
    if not runner:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        # Use provided session_id or generate one
        current_session_id = request.session_id or str(uuid.uuid4())
        
        logger.info(f"Processing chat request: {request.message[:50]}...")
        
        # Handle session following official ADK pattern
        session = None
        if request.session_id:
            # Try to get existing session
            try:
                session = await runner.session_service.get_session(
                    app_name=APP_NAME,
                    user_id=request.user_id,
                    session_id=request.session_id
                )
                logger.info(f"Retrieved existing session {session.id}")
            except:
                logger.info(f"Session {request.session_id} not found, creating new session")
                session = None
        
        if session is None:
            # Create new session (let ADK auto-generate session ID)
            session = await runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=request.user_id,
                state={}  # Initialize with empty state
            )
            logger.info(f"Created new session {session.id}")
            current_session_id = session.id
        else:
            current_session_id = session.id
        
        # Create proper Content object following official ADK pattern
        content = types.Content(role='user', parts=[types.Part(text=request.message)])
        
        # Use the runner with proper parameters following official documentation
        events = runner.run(
            user_id=request.user_id,
            session_id=current_session_id, 
            new_message=content
        )
        
        # Process events to get final response (following official pattern)
        agent_response = ""
        for event in events:
            if event.is_final_response():
                if hasattr(event, 'content') and event.content and event.content.parts:
                    agent_response = event.content.parts[0].text
                    break
            # Also accumulate partial responses
            elif hasattr(event, 'content') and event.content and event.content.parts:
                for part in event.content.parts:
                    if hasattr(part, 'text') and part.text:
                        agent_response += part.text
        
        if not agent_response:
            agent_response = "I received your message but couldn't generate a response. Please try again."
        
        return ChatResponse(
            response=agent_response,
            session_id=current_session_id,
            metadata={
                "agent_name": root_agent.name,
                "runner_used": True
            }
        )
        
    except Exception as e:
        logger.error(f"Error in chat endpoint: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Agent error: {str(e)}")

# Get agent information
@app.get("/agent/info")
async def get_agent_info():
    """Get information about the ADK agent"""
    return {
        "name": root_agent.name,
        "instruction": root_agent.instruction[:200] + "..." if len(root_agent.instruction) > 200 else root_agent.instruction,
        "tools_count": len(root_agent.tools) if root_agent.tools else 0,
        "model": str(root_agent.model) if hasattr(root_agent, 'model') else "Unknown"
    }

# Reset session endpoint
@app.post("/session/reset")
async def reset_session():
    """Reset the current session"""
    try:
        new_session_id = str(uuid.uuid4())
        logger.info(f"Session reset requested, new session ID: {new_session_id}")
        return {"message": "Session reset successfully", "session_id": new_session_id}
    except Exception as e:
        logger.error(f"Error resetting session: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
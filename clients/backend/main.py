import os
import sys
import uuid
import asyncio
import signal
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
setup_agent_with_memory = root_agent_module.setup_agent_with_memory
cleanup_agent = root_agent_module.cleanup_agent
agent_lifespan = root_agent_module.agent_lifespan
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
root_agent = None

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
    global runner, session, root_agent
    try:
        logger.info("Initializing ADK agent with memory...")
        runner, session = await setup_agent_with_memory()
        root_agent = runner.agent
        logger.info("ADK agent initialized successfully")
    except Exception as e:
        logger.error(f"Failed to initialize ADK agent: {str(e)}")
        raise

# Cleanup the agent on shutdown
@app.on_event("shutdown")
async def shutdown_event():
    global runner, session, root_agent
    try:
        logger.info("Shutting down ADK agent...")
        await cleanup_agent()
        runner = None
        session = None
        root_agent = None
        logger.info("ADK agent shutdown complete")
    except Exception as e:
        logger.error(f"Error during shutdown: {str(e)}")

# Health check endpoint
@app.get("/health")
async def health_check():
    return {
        "status": "healthy", 
        "service": "ADK Backend",
        "agent_name": root_agent.name,
        "runner_initialized": runner is not None
    }

# Streaming chat endpoint for real-time tool updates
@app.post("/chat/stream")
async def chat_stream(request: ChatRequest):
    """Streaming chat endpoint for real-time tool execution updates"""
    from fastapi.responses import StreamingResponse
    import json
    
    if not runner:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    async def generate_stream():
        try:
            logger.info(f"Processing streaming chat request: {request.message[:50]}...")
            
            # Create proper Content object
            content = types.Content(role='user', parts=[types.Part(text=request.message)])
            
            # Handle session creation
            session_id_to_use = request.session_id
            if not session_id_to_use:
                new_session = await runner.session_service.create_session(
                    app_name=APP_NAME,
                    user_id=request.user_id,
                    state={}
                )
                session_id_to_use = new_session.id
                logger.info(f"Created new session: {session_id_to_use}")
            
            # Stream events in real-time
            events = runner.run(
                user_id=request.user_id,
                session_id=session_id_to_use,
                new_message=content
            )
            
            agent_response = ""
            tools_used = []
            step_counter = 0
            
            for event in events:
                event_type = type(event).__name__
                
                # Check for function calls (tools being executed)
                if hasattr(event, 'get_function_calls'):
                    try:
                        function_calls = event.get_function_calls()
                        if function_calls:
                            for call in function_calls:
                                step_counter += 1
                                tool_name = getattr(call, 'name', 'unknown')
                                args = str(getattr(call, 'args', ''))
                                
                                # Create step description
                                step_desc = f"🔧 {tool_name}"
                                if tool_name == "execute_query" and "database" in args:
                                    try:
                                        import re
                                        db_match = re.search(r"'database': '(\w+)'", args)
                                        query_match = re.search(r"'query': [\"']([^\"']+)[\"']", args)
                                        
                                        if db_match and query_match:
                                            database = db_match.group(1)
                                            query = query_match.group(1)
                                            
                                            if "information_schema.tables" in query:
                                                step_desc = f"📋 Exploring {database} database schema"
                                            elif "information_schema.columns" in query:
                                                step_desc = f"🔍 Checking table structure in {database}"
                                            elif query.upper().startswith("SELECT"):
                                                step_desc = f"📊 Querying {database} database"
                                    except:
                                        pass
                                
                                # Stream the tool step update
                                tool_update = {
                                    "type": "tool_step",
                                    "step": step_counter,
                                    "description": step_desc,
                                    "tool_name": tool_name,
                                    "session_id": session_id_to_use
                                }
                                yield f"data: {json.dumps(tool_update)}\n\n"
                                
                                tools_used.append({
                                    "name": tool_name,
                                    "type": "function_call",
                                    "arguments": args
                                })
                    except Exception as e:
                        logger.debug(f"Error processing function calls: {e}")
                
                # Check for final response
                if event.is_final_response():
                    if hasattr(event, 'content') and event.content and event.content.parts:
                        agent_response = event.content.parts[0].text
                        break
                elif hasattr(event, 'content') and event.content and event.content.parts:
                    for part in event.content.parts:
                        if hasattr(part, 'text') and part.text:
                            agent_response += part.text
            
            # Send final response
            final_response = {
                "type": "final_response",
                "response": agent_response or "I couldn't generate a response. Please try again.",
                "session_id": session_id_to_use,
                "tools_used": tools_used,
                "tools_count": len(tools_used)
            }
            yield f"data: {json.dumps(final_response)}\n\n"
            
        except Exception as e:
            logger.error(f"Error in streaming chat: {str(e)}")
            error_response = {
                "type": "error",
                "error": str(e),
                "session_id": session_id_to_use if 'session_id_to_use' in locals() else None
            }
            yield f"data: {json.dumps(error_response)}\n\n"
    
    return StreamingResponse(
        generate_stream(),
        media_type="text/plain",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "Content-Type": "text/event-stream"
        }
    )

# Simplified chat endpoint for Gradio integration
@app.post("/chat", response_model=ChatResponse)
async def chat(request: ChatRequest):
    """Simplified chat endpoint for Gradio integration using the existing runner"""
    if not runner:
        raise HTTPException(status_code=500, detail="Agent not initialized")
    
    try:
        logger.info(f"Processing chat request: {request.message[:50]}...")
        
        # Create proper Content object following official ADK pattern
        content = types.Content(role='user', parts=[types.Part(text=request.message)])
        
        # Handle session creation properly
        session_id_to_use = request.session_id
        
        if not session_id_to_use:
            # Create new session through session service
            new_session = await runner.session_service.create_session(
                app_name=APP_NAME,
                user_id=request.user_id,
                state={}
            )
            session_id_to_use = new_session.id
            logger.info(f"Created new session: {session_id_to_use}")
        else:
            # Check if session exists, create if it doesn't
            try:
                await runner.session_service.get_session(
                    app_name=APP_NAME,
                    user_id=request.user_id,
                    session_id=session_id_to_use
                )
                logger.info(f"Using existing session: {session_id_to_use}")
            except Exception:
                # Session doesn't exist, create it
                await runner.session_service.create_session(
                    app_name=APP_NAME,
                    user_id=request.user_id,
                    session_id=session_id_to_use,
                    state={}
                )
                logger.info(f"Created session with ID: {session_id_to_use}")
        
        # Now use the runner with the properly created session
        events = runner.run(
            user_id=request.user_id,
            session_id=session_id_to_use,
            new_message=content
        )
        
        # Track the actual session ID
        actual_session_id = session_id_to_use
        
        # Process events to get final response and extract session ID
        agent_response = ""
        tools_used = []
        event_details = []
        
        for event in events:
            # Log all events for debugging
            event_type = type(event).__name__
            logger.info(f"Event: {event_type}")
            
            # Extract session ID from first event
            if hasattr(event, 'session_id') and event.session_id:
                actual_session_id = event.session_id
            
            # Check for function calls (MCP tool usage)
            if hasattr(event, 'get_function_calls'):
                try:
                    function_calls = event.get_function_calls()
                    if function_calls:
                        logger.info(f"Function calls found: {len(function_calls)}")
                        for call in function_calls:
                            tool_info = {
                                "name": getattr(call, 'name', 'unknown'),
                                "type": "function_call",
                                "id": getattr(call, 'id', None)
                            }
                            if hasattr(call, 'args'):
                                tool_info["arguments"] = str(call.args)
                            tools_used.append(tool_info)
                            logger.info(f"MCP Tool used: {tool_info}")
                except Exception as e:
                    logger.debug(f"Error getting function calls: {e}")
            
            # Check for function responses (MCP tool results)
            if hasattr(event, 'get_function_responses'):
                try:
                    function_responses = event.get_function_responses()
                    if function_responses:
                        logger.info(f"Function responses found: {len(function_responses)}")
                        for response in function_responses:
                            logger.info(f"Tool response: {getattr(response, 'name', 'unknown')}")
                except Exception as e:
                    logger.debug(f"Error getting function responses: {e}")
            
            # Store event details for debugging
            event_info = {
                "type": event_type,
                "has_function_calls": hasattr(event, 'get_function_calls'),
                "has_function_responses": hasattr(event, 'get_function_responses'),
                "is_final": event.is_final_response() if hasattr(event, 'is_final_response') else False
            }
            event_details.append(event_info)
            
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
            session_id=actual_session_id,
            metadata={
                "agent_name": root_agent.name,
                "runner_used": True,
                "tools_used": tools_used,
                "event_details": event_details,
                "tools_count": len(tools_used)
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

async def graceful_shutdown():
    """Handle graceful shutdown on SIGTERM/SIGINT"""
    logger.info("Received shutdown signal, cleaning up...")
    await shutdown_event()

def setup_signal_handlers():
    """Setup signal handlers for graceful shutdown"""
    def signal_handler(signum, frame):
        logger.info(f"Received signal {signum}")
        # Create a new event loop for cleanup if needed
        try:
            loop = asyncio.get_event_loop()
        except RuntimeError:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
        
        # Run cleanup
        loop.run_until_complete(graceful_shutdown())
        sys.exit(0)
    
    signal.signal(signal.SIGTERM, signal_handler)
    signal.signal(signal.SIGINT, signal_handler)

if __name__ == "__main__":
    import uvicorn
    
    # Setup signal handlers for graceful shutdown
    setup_signal_handlers()
    
    uvicorn.run(app, host="0.0.0.0", port=8000)
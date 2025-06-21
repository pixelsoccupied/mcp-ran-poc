#!/bin/bash

# Start the FastAPI backend server
echo "Starting ADK Backend Server..."
cd "$(dirname "$0")"
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
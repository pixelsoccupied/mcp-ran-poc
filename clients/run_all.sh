#!/bin/bash

# Start both backend and frontend
echo "Starting ADK + Gradio Integration..."
cd "$(dirname "$0")"

# Function to cleanup background processes
cleanup() {
    echo "Shutting down services..."
    kill $BACKEND_PID 2>/dev/null
    kill $FRONTEND_PID 2>/dev/null
    exit
}

# Set up signal handling
trap cleanup SIGINT SIGTERM

# Start backend in background
echo "Starting FastAPI backend..."
uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Wait for backend to start
echo "Waiting for backend to initialize..."
sleep 5

# Start frontend in background
echo "Starting Gradio frontend..."
uv run python frontend/app.py &
FRONTEND_PID=$!

echo ""
echo "🚀 Services started successfully!"
echo "📊 Backend API: http://localhost:8000"
echo "🌐 Gradio UI: http://localhost:7860"
echo ""
echo "Press Ctrl+C to stop all services"

# Wait for both processes
wait $BACKEND_PID $FRONTEND_PID
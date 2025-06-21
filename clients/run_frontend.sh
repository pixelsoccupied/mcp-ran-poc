#!/bin/bash

# Start the Gradio frontend
echo "Starting Gradio Frontend..."
cd "$(dirname "$0")"
uv run python frontend/app.py
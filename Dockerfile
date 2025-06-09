# Multi-service container for MCP servers and ADK client
FROM python:3.13-slim

# Install system dependencies
RUN apt-get update && apt-get install -y \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Copy requirements first for better caching
COPY pyproject.toml uv.lock ./

# Install uv for faster Python package management
RUN pip install uv

# Install Python dependencies
RUN uv sync --frozen

# Copy all source code
COPY . .

# Create non-root user for security
RUN useradd -m -u 1000 appuser

# Set UV cache directory and fix permissions for OpenShift
ENV UV_CACHE_DIR=/app/.cache/uv
RUN mkdir -p /app/.cache/uv && \
    chgrp -R 0 /app && \
    chmod -R g=u /app

USER appuser

# Expose all ports that might be used
EXPOSE 3000 8000 8080

# Default command (can be overridden in Kubernetes)
CMD ["uv", "run", "python", "servers/ocloud-pg.py", "--transport", "streamable-http", "--port", "3000"]
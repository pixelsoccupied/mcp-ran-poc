# Makefile for building and pushing MCP application container
REGISTRY := quay.io/npathan/dev
IMAGE_NAME := mcp-talm-poc
TAG ?= latest
FULL_IMAGE := $(REGISTRY):$(IMAGE_NAME)-$(TAG)

.PHONY: help build push build-push clean run-servers run-adk run-gradio-backend run-gradio-frontend run-gradio dev dev-servers dev-gradio stop-dev deploy undeploy

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

build: ## Build the Docker image
	@echo "Building Docker image: $(FULL_IMAGE)"
	docker build --platform linux/amd64 -t $(FULL_IMAGE) .
	@echo "Build complete!"

push: ## Push the Docker image to registry
	@echo "Pushing Docker image: $(FULL_IMAGE)"
	docker push $(FULL_IMAGE)
	@echo "Push complete!"

build-push: build push ## Build and push the Docker image

tag-latest: ## Tag current image as latest
	docker tag $(FULL_IMAGE) $(REGISTRY):$(IMAGE_NAME)-latest
	docker push $(REGISTRY):$(IMAGE_NAME)-latest

clean: ## Remove local Docker images
	@echo "Cleaning up local images..."
	-docker rmi $(FULL_IMAGE)
	-docker rmi $(REGISTRY):$(IMAGE_NAME)-latest
	@echo "Cleanup complete!"

# Development targets
dev-build: ## Build with dev tag
	$(MAKE) build TAG=dev

dev-push: ## Push with dev tag  
	$(MAKE) push TAG=dev

dev-build-push: ## Build and push with dev tag
	$(MAKE) build-push TAG=dev

# Show current configuration
info: ## Show current build configuration
	@echo "Registry: $(REGISTRY)"
	@echo "Image Name: $(IMAGE_NAME)"
	@echo "Tag: $(TAG)"
	@echo "Full Image: $(FULL_IMAGE)"

# Local development targets
run-servers: ## Run MCP servers (PostgreSQL and TALM)
	@echo "Starting MCP servers..."
	@echo "PostgreSQL MCP server on port 3000, TALM MCP server on port 3001"
	uv run python servers/ocloud-pg.py --transport streamable-http --port 3000 & \
	uv run python servers/talm.py --transport streamable-http --port 3001 & \
	wait

run-adk: ## Run ADK agent web interface
	@echo "Starting ADK agent web interface..."
	cd clients && adk web

run-gradio-backend: ## Run Gradio FastAPI backend
	@echo "Starting Gradio FastAPI backend on port 8000..."
	cd clients && uv run uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload

run-gradio-frontend: ## Run Gradio frontend UI
	@echo "Starting Gradio frontend on port 7860..."
	cd clients && uv run python frontend/app.py

run-gradio: ## Run complete Gradio integration (backend + frontend)
	@echo "Starting complete Gradio integration..."
	cd clients && ./run_all.sh

# Development workflow targets
dev: ## Install dependencies and setup development environment
	@echo "Setting up development environment..."
	uv sync
	@echo "Development environment ready!"

dev-servers: ## Development: Run MCP servers in background
	@echo "Starting MCP servers in development mode..."
	uv run python servers/ocloud-pg.py --transport streamable-http --port 3000 & \
	uv run python servers/talm.py --transport streamable-http --port 3001 & \
	echo "MCP servers started in background"

dev-gradio: dev-servers ## Development: Run Gradio with MCP servers
	@echo "Waiting for MCP servers to initialize..."
	@sleep 3
	@echo "Starting Gradio integration..."
	cd clients && ./run_all.sh

stop-dev: ## Stop all development services
	@echo "Stopping development services..."
	@pkill -f "servers/ocloud-pg.py" || true
	@pkill -f "servers/talm.py" || true
	@pkill -f "backend.main:app" || true
	@pkill -f "frontend/app.py" || true
	@echo "Development services stopped"

# Deployment targets
deploy: ## Deploy to OpenShift using kustomize
	@echo "Deploying to OpenShift..."
	@if [ ! -f ".env" ]; then \
		echo "Error: .env file not found!"; \
		echo "Please copy .env.example to .env and fill in your values:"; \
		echo "  cp .env.example .env"; \
		exit 1; \
	fi
	oc apply -k .
	@echo "Deployment complete!"

undeploy: ## Remove deployment from OpenShift
	@echo "Removing deployment..."
	oc delete -k . || true
	@echo "Undeployment complete!"
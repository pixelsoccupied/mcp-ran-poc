# Makefile for MCP application
REGISTRY := quay.io/npathan/dev
IMAGE_NAME := mcp-talm-poc
TAG ?= latest
FULL_IMAGE := $(REGISTRY):$(IMAGE_NAME)-$(TAG)

.PHONY: help build push deploy undeploy format

help: ## Show this help message
	@echo "Available targets:"
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-15s\033[0m %s\n", $$1, $$2}'

format: ## Format code with ruff
	@echo "Formatting Python code with ruff..."
	uv run ruff format
	@echo "Format complete!"

build: ## Build the Docker image
	@echo "Building Docker image: $(FULL_IMAGE)"
	docker build --platform linux/amd64 -t $(FULL_IMAGE) .
	@echo "Build complete!"

push: ## Push the Docker image to registry
	@echo "Pushing Docker image: $(FULL_IMAGE)"
	docker push $(FULL_IMAGE)
	@echo "Push complete!"

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
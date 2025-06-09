# Makefile for building and pushing MCP application container
REGISTRY := quay.io/npathan/dev
IMAGE_NAME := mcp-talm-poc
TAG ?= latest
FULL_IMAGE := $(REGISTRY):$(IMAGE_NAME)-$(TAG)

.PHONY: help build push build-push clean

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
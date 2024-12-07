# Makefile

# Define reusable variables
DOCKER_COMPOSE = docker-compose.yml
APP_SERVICE = web
VENV_DIR = .venv
REQ_FILE = requirements.txt
OUTPUT_DIR = output
TIMEOUT = 60
INTERVAL = 5

# Help target to list available commands
.PHONY: help
help: ## List all available makefile targets
	@echo "Available makefile targets:"
	@awk '/^[a-zA-Z0-9_-]+:.*?## / { \
		printf "\033[36m%-25s\033[0m %s\n", $$1, substr($$0, index($$0, "## ") + 3) \
	}' $(MAKEFILE_LIST)

# Setup the Python virtual environment and install dependencies
.PHONY: venv
venv: $(VENV_DIR)/bin/activate ## Set up the Python virtual environment
$(VENV_DIR)/bin/activate: $(REQ_FILE)
	@python3 -m venv $(VENV_DIR)
	@echo "Virtual environment created at $(VENV_DIR)."
	@$(VENV_DIR)/bin/pip install --upgrade pip
	@$(VENV_DIR)/bin/pip install -r $(REQ_FILE)
	@touch $(VENV_DIR)/bin/activate
	@echo "Dependencies installed."

# Clean the virtual environment
.PHONY: clean-venv
clean-venv: ## Remove the virtual environment
	@rm -rf $(VENV_DIR)
	@echo "Virtual environment removed."

# Build the application Docker image
.PHONY: build
build: ## Build the application Docker image
	@docker-compose -f $(DOCKER_COMPOSE) build $(APP_SERVICE)

# Start the application container
.PHONY: up
up: build ## Start the application container
	@docker-compose -f $(DOCKER_COMPOSE) up -d
	@echo "Starting the application container..."
	@$(MAKE) wait-for-container

# Wait for the container to become healthy
.PHONY: wait-for-container
wait-for-container: ## Wait until the application container is healthy
	@echo "Waiting for the application container to become healthy..."
	@elapsed=0; \
	while [ $$elapsed -lt $(TIMEOUT) ]; do \
		status=$$(docker-compose -f $(DOCKER_COMPOSE) ps --filter "service=$(APP_SERVICE)" --format "{{.State}}"); \
		if [[ "$$status" == "healthy" || "$$status" == "running" ]]; then \
			echo "Service '$(APP_SERVICE)' is healthy."; \
			break; \
		else \
			echo "Service '$(APP_SERVICE)' status: $$status. Waiting..."; \
			sleep $(INTERVAL); \
			elapsed=$$((elapsed + $(INTERVAL))); \
		fi \
	done; \
	if [ $$elapsed -ge $(TIMEOUT) ]; then \
		echo "Error: Service '$(APP_SERVICE)' did not become healthy within $(TIMEOUT) seconds."; \
		docker-compose -f $(DOCKER_COMPOSE) logs $(APP_SERVICE); \
		exit 1; \
	fi

# Check logs of the application container
.PHONY: logs
logs: ## Display logs for the application container
	@docker-compose -f $(DOCKER_COMPOSE) logs $(APP_SERVICE)

# Stop and clean up the application container
.PHONY: down
down: ## Stop and clean up the application container
	@docker-compose -f $(DOCKER_COMPOSE) down --volumes
	@echo "Application container cleaned up."

# Clean the generated output directory
.PHONY: clean-output
clean-output: ## Remove the generated output directory
	@rm -rf $(OUTPUT_DIR)
	@echo "'$(OUTPUT_DIR)' directory has been cleaned up."

# Run the web application locally
.PHONY: run
run: venv ## Run the web application locally
	@$(VENV_DIR)/bin/python -m app.webapp

# Run the update application locally
.PHONY: update
update: venv ## Run the update application locally
	@$(VENV_DIR)/bin/python -m app.cli

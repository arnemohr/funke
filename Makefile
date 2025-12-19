.PHONY: dev dev-frontend dev-backend stop stop-frontend stop-backend install

# Environment (default: dev)
ENV_NAME ?= dev

# Port configuration
BACKEND_PORT ?= 8000
FRONTEND_PORT ?= 5173

# PID files for tracking background processes
PID_DIR = .pids
BACKEND_PID = $(PID_DIR)/backend.pid
FRONTEND_PID = $(PID_DIR)/frontend.pid

# Start both frontend and backend in dev mode (foreground, use Ctrl+C to stop)
dev:
	@echo "Starting frontend and backend in dev mode..."
	@echo "Press Ctrl+C to stop both services"
	@trap 'kill 0' INT; \
		(cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port $(BACKEND_PORT) --reload) & \
		(cd frontend && npm run dev) & \
		wait

# Start backend in dev mode (foreground)
dev-backend:
	cd backend && make dev

# Start frontend in dev mode (foreground)
dev-frontend:
	cd frontend && make dev

# Start backend in background
start-backend:
	@mkdir -p $(PID_DIR)
	@if [ -f $(BACKEND_PID) ] && kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then \
		echo "Backend already running (PID $$(cat $(BACKEND_PID)))"; \
	else \
		cd backend && uv run uvicorn app.main:app --host 0.0.0.0 --port $(BACKEND_PORT) --reload & \
		echo $$! > ../$(BACKEND_PID); \
		echo "Backend started (PID $$!)"; \
	fi

# Start frontend in background
start-frontend:
	@mkdir -p $(PID_DIR)
	@if [ -f $(FRONTEND_PID) ] && kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then \
		echo "Frontend already running (PID $$(cat $(FRONTEND_PID)))"; \
	else \
		cd frontend && npm run dev & \
		echo $$! > ../$(FRONTEND_PID); \
		echo "Frontend started (PID $$!)"; \
	fi

# Start both in background
start: start-backend start-frontend

# Stop backend
stop-backend:
	@if [ -f $(BACKEND_PID) ]; then \
		if kill -0 $$(cat $(BACKEND_PID)) 2>/dev/null; then \
			kill $$(cat $(BACKEND_PID)); \
			echo "Backend stopped"; \
		fi; \
		rm -f $(BACKEND_PID); \
	else \
		echo "Backend not running"; \
	fi

# Stop frontend
stop-frontend:
	@if [ -f $(FRONTEND_PID) ]; then \
		if kill -0 $$(cat $(FRONTEND_PID)) 2>/dev/null; then \
			kill $$(cat $(FRONTEND_PID)); \
			echo "Frontend stopped"; \
		fi; \
		rm -f $(FRONTEND_PID); \
	else \
		echo "Frontend not running"; \
	fi

# Stop all dev servers
stop: stop-backend stop-frontend
	@rm -rf $(PID_DIR)

# Install all dependencies
install:
	cd backend && make install
	cd frontend && make install
	cd infra && make install

# Deploy all (infra + frontend)
deploy:
	cd infra && make deploy
	cd frontend && make deploy

# Clean all
clean:
	cd backend && make clean
	cd frontend && make clean
	cd infra && make clean
	rm -rf $(PID_DIR)





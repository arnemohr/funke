.PHONY: run dev install test lint format clean

# Run the FastAPI server in production mode
run:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000

# Run the FastAPI server in development mode with hot reload
dev:
	uv run uvicorn app.main:app --host 0.0.0.0 --port 8000 --reload

# Install dependencies
install:
	uv sync --all-extras

# Run tests
test:
	uv run pytest

# Run linter
lint:
	uv run ruff check .

# Format code
format:
	uv run black .
	uv run ruff check --fix .

# Clean build artifacts
clean:
	rm -rf __pycache__ .pytest_cache .ruff_cache .coverage htmlcov
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true

FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy source
COPY pyproject.toml ./
COPY src/ ./src/

# Create data directory for SQLite persistence
RUN mkdir -p /app/data

CMD ["python", "-m", "rustbot"]

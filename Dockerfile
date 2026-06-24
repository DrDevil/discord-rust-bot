FROM python:3.12-slim

WORKDIR /app

# Install runtime dependencies
COPY requirements.txt ./
RUN python -m pip install --no-cache-dir -r requirements.txt

# Copy source and install the package
COPY pyproject.toml ./
COPY src/ ./src/
RUN python -m pip install --no-cache-dir .

# Create data directory for SQLite persistence and set permissions
RUN mkdir -p /app/data && \
    useradd -m -u 1000 rustbot && \
    chown -R rustbot:rustbot /app

# Switch to non-root user for security
USER rustbot

# Health check (optional - uncomment if using with orchestration)
HEALTHCHECK --interval=60s --timeout=10s --start-period=30s --retries=3 \
  CMD python -c "import sqlite3; sqlite3.connect('/app/data/rustbot.db').execute('SELECT 1')" || exit 1

CMD ["python", "-m", "rustbot"]

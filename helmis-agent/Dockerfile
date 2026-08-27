# ============================================================
# mcp-waha/Dockerfile
#
# Builds the MCP server that wraps the WAHA REST API.
# Gives Hermes typed tools to send WhatsApp messages.
# ============================================================

FROM python:3.12-slim

# Prevent .pyc files and enable unbuffered stdout (better for Docker logs)
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install lightweight headless LibreOffice for high-fidelity DOCX to PDF rendering
RUN apt-get update && apt-get install -y --no-install-recommends \
    libreoffice-writer-nogui \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies first (layer-cached, only rebuilds on pyproject.toml change)
COPY pyproject.toml .
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir .

# Copy source after dependencies (faster rebuilds during dev)
COPY src/ ./src/

EXPOSE ${MCP_WAHA_PORT:-8765}

CMD ["python", "-c", "from src.server import main; main()"]

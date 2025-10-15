# Dockerfile
FROM python:3.11-slim

# System deps (enough for wheels used by our libs)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential curl ca-certificates && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (layer caching)
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# Copy app code
COPY . .

# Default envs for Streamlit
ENV PYTHONUNBUFFERED=1 \
    PORT=8501

EXPOSE 8501

# Health check (optional but nice)
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD python -c "import socket,sys;s=socket.socket();s.settimeout(3);s.connect(('127.0.0.1',8501));sys.exit(0)"

# Start the Streamlit app
CMD ["streamlit","run","main.py","--server.port=8501","--server.address=0.0.0.0"]

FROM python:3.11-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir fastapi uvicorn[standard]

COPY server.py /app/server.py

CMD ["python", "-m", "uvicorn", "server:app", "--host", "0.0.0.0", "--port", "8383"]

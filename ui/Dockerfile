# Stage 1: Build Svelte SPA
FROM node:20-slim AS builder
WORKDIR /build
COPY package.json ./
RUN npm install --silent
COPY index.html vite.config.js ./
COPY src/ ./src/
RUN npm run build

# Stage 2: FastAPI server + built SPA
FROM python:3.11-slim
WORKDIR /app

# Install Python deps
# networkx + openai are required by graph/tools.py — the workbench spawns
# graph/ingest_entities.py on case upload (entity extraction → Neo4j). Without them the
# spawned process dies with ModuleNotFoundError (stderr→DEVNULL) and uploaded cases show
# an empty graph. The NVIDIA_API_KEY it needs is self-loaded from the mounted /app/.env.
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx neo4j python-multipart networkx openai

# Copy repo files needed at runtime
# (mounted as volume in compose — this layer is for standalone image builds)
COPY --from=builder /build/dist /app/ui/dist

# Entry point
EXPOSE 8200
CMD ["python3", "ui/server.py"]

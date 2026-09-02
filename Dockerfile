# Recourse — one image, one process, one port.
#
# The frontend is built in a Node stage and copied into the Python runtime, which serves it
# alongside the API (see backend/app/server.py for why they are composed rather than
# merged). That removes the two-terminal dev setup from the deployment story entirely:
#
#     docker compose up --build      ->  http://localhost:8000
#
# The NLI model is NOT baked into the image. It is ~750MB, it would quadruple the image for
# something Hugging Face already caches well, and vendoring a model into a container is how
# you end up unable to say which weights are running. It downloads on first start into a
# named volume, so it is fetched once rather than once per container.

# --- frontend build -------------------------------------------------------------------
FROM node:22-slim AS frontend

WORKDIR /build
# Copy manifests first so a source-only change does not re-run the install layer.
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci

COPY frontend/ ./
RUN npm run build


# --- runtime --------------------------------------------------------------------------
FROM python:3.13-slim AS runtime

# PYTHONUNBUFFERED so logs appear in `docker logs` as they happen rather than on exit.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/models

WORKDIR /srv

COPY backend/requirements.txt ./backend/requirements.txt

# torch is installed from PyTorch's CPU index BEFORE requirements.txt, deliberately.
#
# The default PyPI wheel bundles the CUDA runtime -- roughly 2.5GB of GPU libraries this
# image can never use. Inference here is CPU-only by design (Section 3: the decision must
# be deterministic, local, and free to run thousands of times), so every one of those bytes
# is dead weight in the image and in the pull.
#
# requirements.txt asks for the same exact public torch version and is installed second;
# the CPU wheel's local `+cpu` suffix satisfies that pin, so pip leaves it in place.
# requirements.txt is left platform-neutral on purpose -- it has to keep working for a
# local `pip install -r` on Windows and macOS, where this index is the wrong answer.
RUN pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch==2.13.0 \
    && pip install --no-cache-dir -r backend/requirements.txt

COPY backend/ ./backend/
COPY --from=frontend /build/dist ./frontend/dist

# Run as a non-root user. UID 1000 also matches Hugging Face Docker Spaces' documented
# mounted-volume convention, so an attached model/database bucket remains writable.
RUN useradd --create-home --uid 1000 recourse \
    && mkdir -p /models \
    && chown -R recourse:recourse /srv /models
USER recourse

WORKDIR /srv/backend
EXPOSE 8000

# /ready is deliberately the healthcheck rather than /health: it reports 503 until the NLI
# model is in memory, so an orchestrator does not route traffic into a request that would
# stall for fifteen seconds waiting for a cold load. start-period covers the first
# download, which is far slower than a warm start.
HEALTHCHECK --interval=15s --timeout=5s --start-period=180s --retries=5 \
    CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/api/ready', timeout=4).status == 200 else 1)"

CMD ["python", "-m", "uvicorn", "app.server:site", "--host", "0.0.0.0", "--port", "8000"]

# Used both for local docker compose (INSTALL_DEV=true, code bind-mounted, --reload)
# and for production on Render (defaults below).
FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    EMBED_CACHE_DIR=/opt/fastembed

WORKDIR /app
RUN useradd --create-home --uid 1000 app && install -d -o app /opt/fastembed

# Install dependencies from pyproject.toml before copying code, so code edits
# don't invalidate this layer.
ARG INSTALL_DEV=false
COPY pyproject.toml ./
RUN python -c "import os, tomllib; \
p = tomllib.load(open('pyproject.toml', 'rb'))['project']; \
dev = p['optional-dependencies']['dev'] if os.environ.get('INSTALL_DEV') == 'true' else []; \
print('\n'.join(p['dependencies'] + dev))" > /tmp/requirements.txt \
 && pip install -r /tmp/requirements.txt

USER app

# Bake the local embedding model into the image: Render's disk is wiped on every
# cold start, and re-downloading ~70 MB each time would slow the wake-up further.
# Downloaded as `app` so the runtime user can update the cache files.
ARG EMBED_MODEL=BAAI/bge-small-en-v1.5
RUN python -c "from fastembed import TextEmbedding; TextEmbedding('${EMBED_MODEL}', cache_dir='${EMBED_CACHE_DIR}')"

COPY --chown=app:app . .

EXPOSE 8000
# Migrates, then serves on $PORT (Render sets it; 8000 otherwise). Compose overrides this.
CMD ["./start.sh"]

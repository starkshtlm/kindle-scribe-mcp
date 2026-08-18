# Pinned by digest so a build is reproducible. Rebuild regularly (and bump
# this) — weasyprint and poppler parse untrusted files and get CVEs.
FROM python:3.14-slim@sha256:ce40764625a4ff50df3548277632e7f96c4e77fe75fa848aae9885476e7df5a4

# weasyprint renders the outgoing PDF, poppler-utils (pdftoppm/pdfinfo) turns
# returned pages into images for the model to read.
RUN apt-get update && apt-get install -y --no-install-recommends \
        weasyprint poppler-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app
# The lock, not the ranges: two builds of the same tag must install the same
# versions, months apart. requirements.txt stays the human-edited source.
COPY server/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock

COPY server/ .

# Untrusted PDFs are parsed in this container; do not hand a parser bug root.
RUN useradd --system --uid 10001 --home /app --shell /usr/sbin/nologin scribe \
    && mkdir -p /data/inbox && chown -R scribe:scribe /data /app
USER scribe

ENV INBOX_DIR=/data/inbox
VOLUME ["/data"]
EXPOSE 8377

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s \
    CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8377/healthz')"

# Access logs would record the MCP token, which lives in the URL path.
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8377", "--no-access-log"]

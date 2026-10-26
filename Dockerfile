# EAM Toolfamilie — Container fuer die Python-Auslieferung.
#
# Der Kern ist stdlib-only; kein pip, keine Build-Tools im Image.
#   docker build -t eam-toolfamilie:3.1.0 .
#   docker run --rm -p 127.0.0.1:8080:8080 eam-toolfamilie:3.1.0

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONIOENCODING=utf-8 \
    PYTHONPATH=/app

WORKDIR /app

COPY packages/core/*.py /app/
# CLI-Einstieg auch im Container als `eam-ai` verfuegbar machen.
COPY packages/core/eam-ai /usr/local/bin/eam-ai
# Der einzige MDG-Leser liegt neben dem Kern in packages/rules; im Image
# liegen beide flach in /app, weil der Kern flache Modulnamen importiert.
COPY packages/rules/mdg_parser.py /app/
COPY packages/rules/documents.py packages/rules/documents_format.py /app/
COPY packages/core/rules.schema.json /app/
COPY packages/core/README.md packages/core/CHANGELOG.md packages/core/PACKAGING.md /app/
COPY LICENSE NOTICE.md /app/
COPY packages/core/examples/offline /app/examples/offline

RUN chmod 0755 /usr/local/bin/eam-ai \
    && rm -f /app/conftest.py \
    && useradd --system --uid 10001 --create-home --shell /usr/sbin/nologin eamai \
    && chown -R eamai:eamai /app
USER eamai:eamai

EXPOSE 8080

HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD ["python", "-c", "import sys, urllib.request; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8080/healthz', timeout=4).status == 200 else 1)"]

CMD ["python", "-m", "eam_ai", "serve", "--host", "0.0.0.0", "--port", "8080", \
     "--max-upload-mb", "25", "--max-seconds", "120", "--jobs", "2"]

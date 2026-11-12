FROM python:3.11-slim

WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONPATH=/app/.pylib/lib/python3.11/site-packages \
    APP_SAMPLES_DIR=/app/samples

# Runtime dependencies are vendored in .pylib, so the image build does not
# need to run pip against the network.  Only the base image has to be present.
COPY .pylib /app/.pylib
COPY app /app/app
COPY samples /app/samples

RUN useradd --create-home --uid 10001 appuser \
    && chown -R appuser:appuser /app
USER appuser

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=5s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=3)" || exit 1

CMD ["python", "-m", "uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

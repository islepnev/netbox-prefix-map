# Full image: has the compiler needed for pytricia (source-only)
FROM python:3.13 AS build

COPY requirements.txt .
RUN pip wheel --no-cache-dir --wheel-dir /wheels -r requirements.txt


FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PORT=5000 \
    MPLCONFIGDIR=/tmp/matplotlib

RUN useradd --system --uid 10001 --home-dir /app app
WORKDIR /app

COPY --from=build /wheels /wheels
RUN pip install --no-cache-dir --no-index /wheels/* && rm -rf /wheels

COPY app app
COPY static static
COPY templates templates
COPY entrypoint.sh .
RUN mkdir output && chown app:app output

USER app
EXPOSE 5000
HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 CMD ["python", "-m", "app.healthcheck"]
ENTRYPOINT ["/app/entrypoint.sh"]

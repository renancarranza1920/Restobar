# syntax=docker/dockerfile:1
FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

# The optional certificate is only used in managed proxy builds. It is removed
# in the same layer, and is never copied into the final application image.
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then \
      cp /run/secrets/proxy_ca /usr/local/share/ca-certificates/build-proxy.crt; \
      update-ca-certificates; \
    fi; \
    apt-get update && apt-get install -y --no-install-recommends ca-certificates tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && rm -f /usr/local/share/ca-certificates/build-proxy.crt \
    && update-ca-certificates
COPY requirements.txt /tmp/requirements.txt
RUN --mount=type=secret,id=proxy_ca,required=false \
    if [ -f /run/secrets/proxy_ca ]; then \
      cat /etc/ssl/certs/ca-certificates.crt /run/secrets/proxy_ca > /tmp/build-ca.pem; \
      PIP_CERT=/tmp/build-ca.pem pip install -r /tmp/requirements.txt 'PyMySQL[rsa]==1.1.2'; \
      result=$?; rm -f /tmp/build-ca.pem; exit "$result"; \
    else pip install -r /tmp/requirements.txt 'PyMySQL[rsa]==1.1.2'; fi
COPY app /app/app
COPY run.py /app/run.py
RUN useradd --create-home --uid 10001 restobar \
    && mkdir -p /app/instance /app/app/static/uploads/products /app/app/static/uploads/branding \
    && chown -R 10001:10001 /app
USER 10001:10001
EXPOSE 8000
CMD ["gunicorn", "--no-control-socket", "--workers", "1", "--threads", "2", "--bind", "0.0.0.0:8000", "--timeout", "60", "--access-logfile", "-", "--error-logfile", "-", "run:app"]

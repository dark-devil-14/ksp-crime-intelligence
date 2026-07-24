# Catalyst AppSail custom runtime image
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    X_ZOHO_CATALYST_LISTEN_PORT=9000

WORKDIR /app

# libgomp is required by scikit-learn/OpenMP wheels.
RUN apt-get update \
    && apt-get install -y --no-install-recommends libgomp1 ca-certificates \
    && rm -rf /var/lib/apt/lists/*

COPY requirements-catalyst.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements-catalyst.txt

COPY . ./
RUN chmod +x server.py run_all.sh || true

EXPOSE 9000

CMD ["python", "-u", "server.py"]

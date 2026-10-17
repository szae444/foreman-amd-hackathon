# Foreman app image for AMD Instinct (ROCm). PyTorch + rocm-smi come from the base image.
FROM rocm/pytorch:latest

ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
WORKDIR /app

COPY requirements.txt .
RUN pip install -r requirements.txt

COPY foreman ./foreman
COPY web ./web
COPY data/manuals ./data/manuals
COPY tests ./tests
COPY scripts ./scripts

EXPOSE 8080
# Trains the detector on first start if no model is present, then serves the UI + API.
CMD ["bash", "-c", "test -f data/models/patchcore_${FOREMAN_CATEGORY:-metal_nut}.pt || python -m foreman.detector.train; exec uvicorn foreman.server:app --host 0.0.0.0 --port 8080"]

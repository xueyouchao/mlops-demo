FROM python:3.11-slim

WORKDIR /workspace
COPY services/api/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# shared domain package (DDD core) — importable via PYTHONPATH=/workspace.
# `ml_platform/model_kinds.py` ships here as well: the train route validates a
# `TrainRequest` against those definitions and the kinds endpoint is generated
# from them, so the panel can only show what the trainer accepts. It is
# stdlib-only at import time, which is why this image needs no scikit-learn.
COPY packages/ml_platform /workspace/ml_platform

# service source
COPY services/api/app /workspace/app

ENV PYTHONPATH="/workspace"

EXPOSE 8000
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM python:3.11-slim

WORKDIR /workspace
COPY services/worker/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# shared domain package (DDD core) — importable via PYTHONPATH=/workspace
COPY packages/ml_platform /workspace/ml_platform

# service source
COPY services/worker/main.py /workspace/main.py
COPY services/worker/workflows.py /workspace/workflows.py
COPY services/worker/activities.py /workspace/activities.py

ENV PYTHONPATH="/workspace"
CMD ["python", "main.py"]

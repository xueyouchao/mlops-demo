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
COPY services/worker/brain.py /workspace/brain.py
# the estimator kinds the trainer offers — imported by brain.py (to describe them
# to the model), tools.py (to validate a call) and activities.py (to build one)
COPY services/worker/model_kinds.py /workspace/model_kinds.py
COPY services/worker/tools.py /workspace/tools.py

ENV PYTHONPATH="/workspace"
CMD ["python", "main.py"]

FROM python:3.11-slim

WORKDIR /workspace
COPY services/worker/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt

# shared domain package (DDD core) — importable via PYTHONPATH=/workspace.
# It also carries `ml_platform/model_kinds.py`, the estimator kinds the trainer
# offers: imported by brain.py (to describe them to the model), tools.py (to
# validate a call), activities.py (to build one) and — in the api image, which
# copies this same directory — by the train route (to validate a request and to
# generate the console panel's inputs). One module, both images, no second copy.
COPY packages/ml_platform /workspace/ml_platform

# service source
COPY services/worker/main.py /workspace/main.py
COPY services/worker/workflows.py /workspace/workflows.py
COPY services/worker/activities.py /workspace/activities.py
COPY services/worker/brain.py /workspace/brain.py
COPY services/worker/tools.py /workspace/tools.py

ENV PYTHONPATH="/workspace"
CMD ["python", "main.py"]

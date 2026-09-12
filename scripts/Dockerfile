FROM python:3.11-slim
WORKDIR /workspace
COPY scripts/requirements.txt /workspace/requirements.txt
RUN pip install --no-cache-dir -r /workspace/requirements.txt
COPY scripts/train_and_register.py /workspace/train_and_register.py
ENV PYTHONPATH="/workspace"
CMD ["python", "train_and_register.py"]

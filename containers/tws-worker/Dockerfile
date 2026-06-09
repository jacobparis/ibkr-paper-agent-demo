FROM python:3.13-slim

RUN pip install --no-cache-dir ib_async==2.1.0

WORKDIR /opt/worker
COPY workers/tws_worker.py /opt/worker/tws_worker.py

ENTRYPOINT ["python", "/opt/worker/tws_worker.py"]

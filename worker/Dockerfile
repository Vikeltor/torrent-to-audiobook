FROM python:3.12-slim

RUN apt-get update && \
    apt-get install -y ffmpeg && \
    rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir requests pyyaml

COPY worker.py /worker.py

CMD ["python3", "-u", "/worker.py"]

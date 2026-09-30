FROM python:3.12-slim

RUN useradd -m -u 1000 gateway
COPY gateway.py /app/gateway.py

# Unbuffered stdout: per-request audit JSON lines must reach `docker logs`
# immediately; no bytecode litter in the container filesystem.
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

USER gateway
EXPOSE 8080
CMD ["python3", "/app/gateway.py"]

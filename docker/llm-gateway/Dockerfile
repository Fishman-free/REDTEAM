FROM python:3.12-slim

RUN useradd -m -u 1000 gateway
COPY gateway.py /app/gateway.py

USER gateway
EXPOSE 8080
CMD ["python3", "/app/gateway.py"]

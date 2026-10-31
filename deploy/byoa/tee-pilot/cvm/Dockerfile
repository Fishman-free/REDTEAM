FROM python:3.12-slim

WORKDIR /app
COPY cvm/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY binding.py .
COPY cvm/pilot_app.py .

EXPOSE 8080
CMD ["python", "-u", "pilot_app.py"]

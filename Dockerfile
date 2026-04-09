FROM python:3.11-slim

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY src/ ./src/
COPY openenv.yaml .
COPY baseline.py .
COPY README.md .
COPY inference.py .

EXPOSE 7860

CMD ["uvicorn", "src.server:app", "--host", "0.0.0.0", "--port", "7860"]
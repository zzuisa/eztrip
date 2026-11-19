# EzTrip backend — FastAPI (HelloAgents) trip planner
FROM python:3.13-slim

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . /app/

EXPOSE 8881

# .env / storage / cache are bind-mounted at runtime (see docker-compose.yml)
CMD ["uvicorn", "app.api.main:app", "--host", "0.0.0.0", "--port", "8881"]

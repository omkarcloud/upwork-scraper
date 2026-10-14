FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN python -m pip install --no-cache-dir -r requirements.txt

RUN mkdir app
WORKDIR /app
COPY . /app

EXPOSE 8000

# No browser needed — the scraper reads Upwork's pages and its own GraphQL API
# over plain HTTP with browser-grade TLS.
CMD ["python", "run.py"]

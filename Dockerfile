FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

WORKDIR /app

# Install build dependencies for packages like cryptography
RUN apt-get update \
    && apt-get install -y --no-install-recommends build-essential libssl-dev libffi-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt /app/requirements.txt

# Install Python dependencies and ensure setuptools (pkg_resources) is available
RUN pip install --upgrade pip setuptools \
    && pip install --no-cache-dir -r /app/requirements.txt

# Copy application source
COPY . /app

# Use the port provided by the hosting platform (Vercel sets $PORT)
ENV PORT=8080

# Run the app with gunicorn. Use bash -c so $PORT is expanded.
CMD ["bash", "-lc", "gunicorn app:app --bind 0.0.0.0:$PORT --workers 1 --threads 8 --timeout 90"]

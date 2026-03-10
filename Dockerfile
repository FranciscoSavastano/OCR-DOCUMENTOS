FROM python:3.10-slim

WORKDIR /app

# Install system dependencies required by OpenCV and PaddleOCR and gcc for compiling python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy python requirements and install them
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code
COPY . .

# Expose port (must match your gunicorn binding and docker-compose mapping)
EXPOSE 5000

# Start server using gunicorn
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "120", "scan_id:app"]

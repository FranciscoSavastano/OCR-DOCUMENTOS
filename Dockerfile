FROM python:3.11-bookworm

WORKDIR /app

# Set environment variables to stabilize build-time model downloads/runs
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1

# Disable AVX instructions and set memory strategies for instability prevention
ENV PADDLE_WITH_AVX=OFF
ENV FLAGS_allocator_strategy=naive_best_fit

# Resolve potential libgomp/segmentation fault issues by preloading it
ENV LD_PRELOAD=/usr/lib/x86_64-linux-gnu/libgomp.so.1

# Install system dependencies required by OpenCV and PaddleOCR and gcc for compiling python wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy python requirements
COPY requirements.txt .

# Forcefully remove any conflicting GUI-based libraries before installation
RUN pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless || true

# Install requirements
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download PaddleOCR models into the Docker image
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='pt')"

# Copy the rest of the application code
COPY . .

# Expose port (must match your gunicorn binding and docker-compose mapping)
EXPOSE 5000

# Start server using gunicorn
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "120", "scan_id:app"]

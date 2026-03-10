FROM python:3.10-slim-bullseye

WORKDIR /app

# Set environment variables to stabilize build-time model downloads/runs
ENV OMP_NUM_THREADS=1
ENV OPENBLAS_NUM_THREADS=1
ENV MKL_NUM_THREADS=1

# Disable AVX, MKLDNN, and set memory strategies for extreme stability
ENV PADDLE_WITH_AVX=OFF
ENV FLAGS_use_mkldnn=0
ENV FLAGS_allocator_strategy=naive_best_fit
ENV SET_CPU_CORE_PREFERENCE=0
ENV GLOG_minloglevel=3
ENV KMP_DUPLICATE_LIB_OK=TRUE

# glibc memory allocation tweak to prevent munmap_chunk errors
ENV MALLOC_TRIM_THRESHOLD_=-1

# Install minimal system dependencies required by OpenCV and PaddleOCR
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# Copy python requirements
COPY requirements.txt .

# Install requirements then STRICTLY cleanup and reinstall OpenCV to avoid conflicts
RUN pip install --no-cache-dir -r requirements.txt && \
    pip uninstall -y opencv-python opencv-contrib-python opencv-python-headless opencv-contrib-python-headless && \
    pip install --no-cache-dir opencv-contrib-python-headless==4.6.0.66

# Pre-download PaddleOCR models into the Docker image
RUN python -c "from paddleocr import PaddleOCR; PaddleOCR(use_angle_cls=True, lang='pt')"

# Copy the rest of the application code
COPY . .

# Expose port (must match your gunicorn binding and docker-compose mapping)
EXPOSE 5000

# Start server using gunicorn
CMD ["gunicorn", "--workers", "2", "--bind", "0.0.0.0:5000", "--timeout", "120", "scan_id:app"]

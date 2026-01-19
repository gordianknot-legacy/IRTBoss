# IRTBoss Backend Dockerfile
# Multi-stage build for smaller production image

# Stage 1: R environment for mirt
FROM rocker/r-ver:4.3 AS r-base

# Install R packages
RUN R -e "install.packages(c('mirt', 'jsonlite'), repos='https://cloud.r-project.org/')"

# Stage 2: Python application
FROM python:3.11-slim AS python-base

# Install R from r-base stage
COPY --from=r-base /usr/local/lib/R /usr/local/lib/R
COPY --from=r-base /usr/local/bin/R /usr/local/bin/R
COPY --from=r-base /usr/local/bin/Rscript /usr/local/bin/Rscript

# Install R runtime dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    libcurl4-openssl-dev \
    libssl-dev \
    libxml2-dev \
    libfontconfig1-dev \
    libfreetype6-dev \
    libpng-dev \
    libtiff5-dev \
    libjpeg-dev \
    && rm -rf /var/lib/apt/lists/*

# Set working directory
WORKDIR /app

# Install Python dependencies
COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY backend/app ./app

# Create non-root user
RUN useradd -m -u 1000 irtboss && chown -R irtboss:irtboss /app
USER irtboss

# Expose port
EXPOSE 8000

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

# Run the application
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]

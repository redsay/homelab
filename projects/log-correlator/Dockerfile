FROM python:3.12-slim

WORKDIR /app

# Install Python dependencies first (layer-cache friendly)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application source
COPY anomaly_detector.py .
COPY correlator.py .
COPY simulate_logs.py .
COPY config.yaml .

# Copy pre-generated sample data
COPY sample_data/ sample_data/

# Run the correlator against the bundled sample data by default.
# Override at runtime, e.g.:
#   docker run --rm log-correlator python simulate_logs.py
#   docker run --rm -v $(pwd)/my_logs:/data log-correlator \
#       python correlator.py --config /data/config.yaml --output-dir /data/results
CMD ["python", "correlator.py", "--config", "config.yaml"]

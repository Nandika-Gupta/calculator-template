FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY viralcut/requirements.txt viralcut/requirements.txt
RUN pip install --no-cache-dir -r viralcut/requirements.txt
COPY viralcut viralcut
ENV VIRALCUT_DATA=/app/viralcut_data
EXPOSE 8000
CMD ["uvicorn", "viralcut.app:app", "--host", "0.0.0.0", "--port", "8000"]

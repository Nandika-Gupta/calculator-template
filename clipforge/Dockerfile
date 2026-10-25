FROM python:3.12-slim
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY clipforge/requirements.txt clipforge/requirements.txt
RUN pip install --no-cache-dir -r clipforge/requirements.txt
COPY clipforge clipforge
ENV CLIPFORGE_DATA=/app/clipforge_data
EXPOSE 8000
CMD ["uvicorn", "clipforge.app:app", "--host", "0.0.0.0", "--port", "8000"]

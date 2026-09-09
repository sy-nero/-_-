# חלופה ל-render.yaml: פריסה לכל שירות שמריץ קונטיינרים
# (Cloud Run, Fly.io, Railway). הנתונים חייבים דיסק/volume קבוע ב-DATA_DIR.
FROM python:3.11-slim

WORKDIR /app
ENV PYTHONUNBUFFERED=1 DATA_DIR=/var/data

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN mkdir -p /var/data

EXPOSE 8080
CMD ["sh", "-c", "gunicorn webapp.app:app --bind 0.0.0.0:${PORT:-8080} --workers 2 --timeout 120"]

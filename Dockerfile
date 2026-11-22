FROM python:3.12-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

ENV FLASK_APP=run.py \
    SECRET_KEY=bitte-in-produktion-setzen

EXPOSE 8000
# SQLite -> bewusst 1 Worker (kein "database is locked"); bei PostgreSQL (DATABASE_URL) mehr Worker möglich
CMD ["gunicorn", "-w", "1", "--timeout", "60", "-b", "0.0.0.0:8000", "run:app"]

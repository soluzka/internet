FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /srv

COPY requirements.txt ./
RUN pip install -r requirements.txt

COPY app.py ./

# Most hosts inject PORT; 8080 is the sensible default.
ENV PORT=8080
EXPOSE 8080

# ONE worker on purpose: jobs live in this process's memory, so a second worker
# would not know about a download started by the first. Threads do the work.
# The timeout is generous because a single request may stream a large file.
CMD ["sh", "-c", "gunicorn --workers 1 --threads 8 --timeout 300 --bind 0.0.0.0:${PORT} app:app"]

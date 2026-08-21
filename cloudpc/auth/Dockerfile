# CloudPC auth portal — Flask + gunicorn from Ubuntu archives (no pip needed)
FROM cloudpc/base:24.04

ENV DEBIAN_FRONTEND=noninteractive
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        python3 python3-flask python3-argon2 gunicorn && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

RUN useradd -r -u 900 -m -d /app -s /usr/sbin/nologin cloudauth
COPY app.py manage.py /app/
COPY templates/ /app/templates/
RUN chown -R root:root /app && chmod -R a+rX /app

USER cloudauth
WORKDIR /app
EXPOSE 8000
# Single worker: the lockout/rate-limit counters are in-process state.
# Threads give concurrency; a login portal needs no more.
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "--workers", "1", "--threads", "8", \
     "--access-logfile", "-", "app:app"]

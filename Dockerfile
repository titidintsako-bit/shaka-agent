FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1
ENV SHAKA_HOME=/home/shaka/.shaka
ENV SHAKA_HOST=0.0.0.0
ENV SHAKA_PORT=18789

WORKDIR /app

COPY pyproject.toml README.md ./
RUN pip install --upgrade pip

COPY . /app
RUN pip install .
RUN useradd --create-home --shell /bin/bash shaka \
    && mkdir -p /home/shaka/.shaka \
    && chown -R shaka:shaka /home/shaka /app

USER shaka

EXPOSE 18789
HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:18789/health', timeout=3)"

ENTRYPOINT ["shaka"]
CMD ["gateway", "--host", "0.0.0.0", "--port", "18789"]

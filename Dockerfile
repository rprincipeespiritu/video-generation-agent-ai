FROM python:3.12-slim-bookworm

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 \
    APP_ENV=production VIDEO_DATA_DIR=/storage/data VIDEO_CONFIG_DIR=/storage/config \
    FFMPEG_PATH=/usr/bin/ffmpeg FONT_PATH=/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf

RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg fonts-dejavu-core tini gosu \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 10001 videoagent \
    && useradd --uid 10001 --gid 10001 --create-home videoagent
WORKDIR /app
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY agent.py production.py ui.py server.py ./
COPY web ./web
COPY docker-entrypoint.sh /usr/local/bin/video-entrypoint
RUN chmod +x /usr/local/bin/video-entrypoint \
    && ffmpeg -hide_banner -filters 2>/dev/null | grep -q rubberband

EXPOSE 8080
ENTRYPOINT ["tini", "--", "/usr/local/bin/video-entrypoint"]
CMD ["python", "-X", "utf8", "server.py"]

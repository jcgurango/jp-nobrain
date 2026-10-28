FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    JP_DATA_DIR=/data \
    JP_HOST=0.0.0.0 \
    JP_PORT=8765

WORKDIR /app
# media/ is generated locally by scripts/extract.py (gitignored); it must exist before building.
COPY data/ data/
COPY media/ media/
COPY app/ app/

VOLUME /data
EXPOSE 8765

# import_deck is idempotent and keeps progress, so running it on every start picks up deck rebuilds.
CMD ["sh", "-c", "python3 -I app/import_deck.py && exec python3 -I app/server.py"]

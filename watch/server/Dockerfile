# Build from the repo root so the validation references come along:
#   docker build -f watch/server/Dockerfile -t swordfish-feed .
FROM python:3.13-slim
WORKDIR /srv
COPY validation/composites_ref.py validation/vwap_ref.py validation/offside_fixed.py validation/
COPY watch/server/swordfish_feed swordfish_feed
ENV SWORDFISH_VALIDATION=/srv/validation PORT=8080 PYTHONUNBUFFERED=1
EXPOSE 8080
USER nobody
CMD ["python", "-m", "swordfish_feed"]

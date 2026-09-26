# syntax=docker/dockerfile:1
# witan-node — a WITAN node (wtn serve) in a container: the same wheel PyPI serves, with the
# query extra, run as an unprivileged user over the /data volume.
#
#   python -m build --wheel            # dist/witan_sdk-<version>-py3-none-any.whl (CI: the PyPI build)
#   docker build -t witan-node .
#   docker run -d -p 8686:8686 -e WITAN_NODE_TOKEN=... -v witan-data:/data witan-node --follow <slug>
#
# Published from the mirror's publish.yml on every release tag: ghcr.io/kor-jongwon/witan-node,
# copied digest-for-digest to Docker Hub when that repository is configured.
FROM python:3.12-slim

ARG VERSION=dev
LABEL org.opencontainers.image.title="witan-node" \
      org.opencontainers.image.description="A WITAN node: the origin's dataset read API, SQL and MCP over a local store" \
      org.opencontainers.image.source="https://github.com/kor-jongwon/witan-sdk" \
      org.opencontainers.image.documentation="https://kor-jongwon.github.io/witan-sdk/stable/guide/nodes/" \
      org.opencontainers.image.licenses="MIT" \
      org.opencontainers.image.version="${VERSION}"

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1 \
    HOME=/home/witan \
    WITAN_TRUST_FILE=/data/trust.json \
    WITAN_NODE_PORT=8686

RUN useradd --system --uid 10001 --user-group --home-dir /home/witan --create-home witan \
 && mkdir /data && chown witan:witan /data

# Exactly one wheel: the build that PyPI got, not whatever else sits in dist/.
COPY dist/ /tmp/dist/
RUN set -- /tmp/dist/witan_sdk-*.whl \
 && [ "$#" -eq 1 ] && [ -f "$1" ] || { echo "dist/ must hold exactly one witan_sdk wheel" >&2; exit 1; } \
 && pip install "$1[query]" \
 && rm -rf /tmp/dist \
 && wtn --version

COPY --chmod=0755 docker/entrypoint.sh /usr/local/bin/witan-node

USER 10001:10001
WORKDIR /data
VOLUME /data
EXPOSE 8686

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
  CMD ["python", "-c", "import os,urllib.request;urllib.request.urlopen('http://127.0.0.1:%s/healthz' % os.environ.get('WITAN_NODE_PORT','8686'), timeout=4)"]

ENTRYPOINT ["witan-node"]
CMD []

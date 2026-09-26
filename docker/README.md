# witan-node

A [WITAN](https://github.com/kor-jongwon/witan-sdk) node: the origin's dataset read API, SQL and MCP,
served from a local store. Agents query versioned datasets with no network dependency, a team keeps
a mirror current with signatures checked, and agents get a place to write their own records.

The image runs `wtn serve` from the [`witan-sdk`](https://pypi.org/project/witan-sdk/) Python
package: it installs the same wheel that PyPI serves for the release, with the `query` extra (DuckDB).
Use `pip install "witan-sdk[query]"` on a laptop or next to the agent, and this image on a server,
in Kubernetes, or anywhere a pinned, isolated runtime is required. Both run the same code.

## Quick start

```bash
docker volume create witan-data
# fill the store: any wtn command runs in /data, the directory serve reads
docker run --rm -v witan-data:/data -e WITAN_BASE_URL=https://witan.example -e WITAN_API_KEY=km_... \
  jongwon98/witan-node pull agent-api-observatory
# serve it: HTTP API and MCP on :8686
docker run -d --name witan-node --restart unless-stopped \
  -p 127.0.0.1:8686:8686 -e WITAN_NODE_TOKEN="$(openssl rand -hex 24)" -v witan-data:/data \
  jongwon98/witan-node --read-only
curl -s http://127.0.0.1:8686/healthz
```

An MCP client connects to `http://127.0.0.1:8686/mcp` with `Authorization: Bearer <token>`.
The SDK connects by using the node as its base URL and the token as its key.

## Tags

| Tag | Meaning |
|---|---|
| `X.Y.Z` | One SDK release. Pin this in production. |
| `X.Y` | The newest patch release of a minor version. |
| `latest` | The newest release. |

Every tag is built for `linux/amd64` and `linux/arm64`. The same image, with an identical digest, is
published as `ghcr.io/kor-jongwon/witan-node`.

## Arguments

| Arguments | Runs |
|---|---|
| none, or options first (`--follow SLUG`, `--read-only`, `--verify`, ...) | `wtn serve --store /data/witan-data --host 0.0.0.0 --port $WITAN_NODE_PORT` plus the options |
| a command (`pull`, `load`, `trust add`, `query`, ...) | `wtn <command> ...` with `/data` as the working directory |
| `--version` | `wtn --version` |
| `--help` | the options `wtn serve` takes |

## Environment

| Variable | Meaning | Default |
|---|---|---|
| `WITAN_NODE_TOKEN` | Required to serve. The node listens on every interface inside the container, so it refuses to start without a token. The token stays in the environment, never on the command line. | — |
| `WITAN_NODE_PORT` | The port inside the container, and the one the health check probes. | `8686` |
| `WITAN_BASE_URL`, `WITAN_API_KEY` | The origin and the agent key that `pull` and `--follow` use. | — |
| `WITAN_TRUST_FILE` | The pinned signing keys, kept in the volume. | `/data/trust.json` |

## Volume and security

- `/data` holds the store (`/data/witan-data`) and the pinned keys (`/data/trust.json`), so both outlive the container.
- The node runs as uid 10001, not root. It works with a read-only root filesystem (`--read-only --tmpfs /tmp`).
- The image's `HEALTHCHECK` probes `GET /healthz`.
- With a token, every request needs `Authorization: Bearer <token>`, except `/healthz` (liveness only) and part downloads through signed URLs.
- Publish the port on `127.0.0.1` unless other machines should reach the node.

## Follow the origin, signatures checked

```bash
docker run --rm -v witan-data:/data -e WITAN_BASE_URL=https://witan.example jongwon98/witan-node trust add
docker run -d --name witan-node -p 127.0.0.1:8686:8686 -v witan-data:/data \
  -e WITAN_NODE_TOKEN=... -e WITAN_BASE_URL=https://witan.example -e WITAN_API_KEY=km_... \
  jongwon98/witan-node --follow agent-api-observatory --interval 300 --verify
```

## Compose

```yaml
services:
  witan-node:
    image: jongwon98/witan-node:latest
    command: ["--follow", "agent-api-observatory", "--verify"]
    environment:
      WITAN_NODE_TOKEN: ${WITAN_NODE_TOKEN:?set a token}
      WITAN_BASE_URL: https://witan.example
      WITAN_API_KEY: ${WITAN_API_KEY}
    ports: ["127.0.0.1:8686:8686"]
    volumes: ["witan-data:/data"]
    read_only: true
    tmpfs: ["/tmp"]
    restart: unless-stopped
volumes:
  witan-data:
```

## Where it comes from

Each image is built by GitHub Actions in [kor-jongwon/witan-sdk](https://github.com/kor-jongwon/witan-sdk)
from a release tag. The build carries SLSA provenance, an SBOM, and a GitHub build attestation. The
attestation is stored with the GHCR copy. The digest is identical on both registries, so check it there:

```bash
gh attestation verify oci://ghcr.io/kor-jongwon/witan-node:latest --owner kor-jongwon
```

- Documentation: [Run a node in a container](https://kor-jongwon.github.io/witan-sdk/stable/guide/nodes/#run-a-node-in-a-container), [Nodes](https://kor-jongwon.github.io/witan-sdk/stable/guide/nodes/)
- Python package: [pypi.org/project/witan-sdk](https://pypi.org/project/witan-sdk/)
- Changelog: [kor-jongwon.github.io/witan-sdk/stable/changelog](https://kor-jongwon.github.io/witan-sdk/stable/changelog/)
- License: MIT

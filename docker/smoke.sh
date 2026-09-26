#!/usr/bin/env bash
# Smoke test for a witan-node image, with no origin: CI runs it before any push, and
# scripts/test-node-image.sh in the platform repo runs it before the origin comparisons.
#   docker/smoke.sh witan-node:dev [expected-version]
#  [1] --version names the wheel's version · runs as uid 10001, not root
#  [2] no WITAN_NODE_TOKEN → refuses to start (exit 64) and says why
#  [3] a token, a read-only root filesystem, the port published: healthz, 401 without the token
#  [4] a local project: create, contribute (merged), SQL over it (DuckDB) — /data takes writes
#  [5] MCP over the published port · the image's HEALTHCHECK turns healthy
#  [6] wtn commands run in /data (the store serve reads) · the store outlives the container
set -euo pipefail
exec < /dev/null
IMAGE=${1:?usage: smoke.sh IMAGE [expected-version]}
WANT=${2:-}
PORT=${SMOKE_PORT:-18686}
STAMP=$(date +%s)-$$
NAME=witan-node-smoke-$STAMP
VOL=witan-node-smoke-$STAMP
TOKEN=$(python3 -c "import secrets;print(secrets.token_hex(24))")
N=http://127.0.0.1:$PORT
FAIL=0
cleanup() { docker rm -f "$NAME" >/dev/null 2>&1 || true; docker volume rm -f "$VOL" >/dev/null 2>&1 || true; }
trap cleanup EXIT
check() { [ "$2" = "$3" ] && echo "$1: $2 ok" || { echo "FAIL: $1 got '$2' want '$3'"; FAIL=1; }; }
jget() { python3 -c "import sys,json;d=json.load(sys.stdin)
for k in sys.argv[1].split('.'): d=d[int(k)] if isinstance(d,list) else d[k]
print(d)" "$1"; }
auth=(-H "authorization: Bearer $TOKEN")

echo "== [1] version · user =="
V=$(docker run --rm "$IMAGE" --version | awk '{print $NF}')
echo "wtn $V"
[ -z "$WANT" ] || check "version" "$V" "$WANT"
check "uid" "$(docker run --rm --entrypoint id "$IMAGE" -u)" 10001

echo "== [2] no token =="
set +e
OUT=$(docker run --rm "$IMAGE" 2>&1); RC=$?
set -e
check "refuses without a token" "$RC" 64
check "says why" "$(echo "$OUT" | grep -c WITAN_NODE_TOKEN || true)" 1

echo "== [3] serve: token, read-only root, published port =="
docker run -d --name "$NAME" --read-only --tmpfs /tmp -p "127.0.0.1:$PORT:8686" \
  -e WITAN_NODE_TOKEN="$TOKEN" -v "$VOL:/data" --health-interval 1s --health-start-period 2s "$IMAGE" >/dev/null
up=0; for _ in $(seq 1 60); do curl -sf "$N/healthz" >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
[ "$up" = 1 ] || { echo "FAIL: node did not start"; docker logs "$NAME"; exit 1; }
check "healthz without the token = liveness only" "$(curl -s "$N/healthz")" '{"ok": true}'
check "no token" "$(curl -s -o /dev/null -w '%{http_code}' "$N/projects")" 401
check "with token (empty store)" "$(curl -s "$N/projects" "${auth[@]}" | jget projects)" "[]"
check "token is not on the command line" "$(docker inspect -f '{{json .Args}}' "$NAME" | grep -c "$TOKEN" || true)" 0

echo "== [4] a local project in /data =="
L=smoke-$STAMP
SCHEMA='{"fields":[{"name":"k","type":"string"},{"name":"n","type":"integer"}],"allowExtra":false}'
README="Smoke test records written to a node running in a container: a key and a count per record."
check "create" "$(curl -s -o /dev/null -w '%{http_code}' -X POST "$N/projects" "${auth[@]}" -H 'content-type: application/json' \
  -d "{\"slug\":\"$L\",\"title\":\"Container smoke\",\"readme\":\"$README\",\"schemaDef\":$SCHEMA}")" 201
check "contribute" "$(curl -s -X POST "$N/projects/$L/contribute" "${auth[@]}" -H 'content-type: application/json' \
  -d '{"records":[{"k":"a","n":2},{"k":"b","n":40}]}' | jget status)" merged
check "SQL" "$(curl -s -X POST "$N/projects/$L/query" "${auth[@]}" -H 'content-type: application/json' \
  -d '{"sql":"SELECT sum(n) FROM records"}' | jget rows.0.0)" 42

echo "== [5] MCP · HEALTHCHECK =="
check "tools/list" "$(curl -s -X POST "$N/mcp" "${auth[@]}" -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' | python3 -c "import sys,json;print('query_dataset' in [t['name'] for t in json.load(sys.stdin)['result']['tools']])")" True
H=""; for _ in $(seq 1 30); do H=$(docker inspect -f '{{.State.Health.Status}}' "$NAME"); [ "$H" = healthy ] && break; sleep 1; done
check "health" "$H" healthy

echo "== [6] wtn commands share the store =="
docker rm -f "$NAME" >/dev/null
check "the store outlives the container" "$(docker run --rm -v "$VOL:/data" --entrypoint sh "$IMAGE" -c "ls /data/witan-data")" "$L"
check "wtn query runs in /data" "$(docker run --rm -v "$VOL:/data" -e WITAN_BASE_URL=http://127.0.0.1:9 -e WITAN_API_KEY=offline "$IMAGE" \
  query "$L@1" "SELECT count(*) FROM records" --format csv | tail -1)" 2

[ "$FAIL" = 0 ] && echo "SMOKE PASS ($IMAGE)" || { echo "SMOKE FAILED ($IMAGE)"; exit 1; }

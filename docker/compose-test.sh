#!/usr/bin/env bash
# The official docker-compose.yml, brought up the way its header says, with no origin: CI runs it after
# the image smoke test.
#   docker/compose-test.sh witan-node:dev [expected-version]
#  [1] the file names this release's image; without WITAN_NODE_TOKEN compose refuses and says why
#  [2] up from .env.example with a token: healthy, 401 without the token, 200 with it, on 127.0.0.1 only
#  [3] WITAN_FOLLOW + WITAN_VERIFY=1 with the origin unreachable and no keys pinned: exits 69 and says why
#  [4] the same with keys already in the volume: the node still serves
#  [5] WITAN_NODE_TOKEN_FILE: the token from a mounted secret, not the environment
set -euo pipefail
exec < /dev/null
IMAGE=${1:?usage: compose-test.sh IMAGE [expected-version]}
WANT=${2:-}
HERE=$(cd "$(dirname "$0")" && pwd)
PORT=${COMPOSE_TEST_PORT:-18786}
P=witan-node-ct-$(date +%s)-$$
T=$(mktemp -d); command -v cygpath > /dev/null 2>&1 && T=$(cygpath -m "$T")   # Git Bash: a C:/ path docker can mount
TOKEN=$(python3 -c "import secrets;print(secrets.token_hex(24))")
N=http://127.0.0.1:$PORT
FAIL=0
C() { docker compose -p "$P" --env-file "$T/.env" -f "$HERE/docker-compose.yml" "$@"; }
cleanup() { C down -v >/dev/null 2>&1 || true; docker rm -f "$P-secret" >/dev/null 2>&1 || true; rm -rf "$T"; }
trap cleanup EXIT
check() { [ "$2" = "$3" ] && echo "$1: $2 ok" || { echo "FAIL: $1 got '$2' want '$3'"; FAIL=1; }; }
env_file() {   # .env.example with the image under test, this port, and the given overrides
  sed -e "s|^WITAN_NODE_HOST_PORT=.*|WITAN_NODE_HOST_PORT=$PORT|" "$HERE/.env.example" > "$T/.env"
  echo "WITAN_NODE_IMAGE=$IMAGE" >> "$T/.env"
  for kv in "$@"; do k=${kv%%=*}; sed -i.bak "/^$k=/d" "$T/.env"; echo "$kv" >> "$T/.env"; done
}
wait_state() {   # $1 = healthy | exited → prints what the container reached
  local s=""; for _ in $(seq 1 60); do
    s=$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{end}}/{{.State.Status}}' "$(C ps -aq witan-node)" 2>/dev/null || true)
    case "$1:$s" in healthy:healthy/*|exited:*/exited|exited:*/restarting) break ;; esac; sleep 1
  done; echo "$s"
}

echo "== [1] the file =="
TAG=$(sed -n 's|.*ghcr.io/kor-jongwon/witan-node:\([0-9][^}]*\)}.*|\1|p' "$HERE/docker-compose.yml")
[ -z "$WANT" ] || check "names this release's image" "$TAG" "$WANT"
env_file
set +e; OUT=$(C config 2>&1); RC=$?; set -e
check "refuses without a token" "$([ "$RC" != 0 ] && echo refused)" refused
check "says why" "$(echo "$OUT" | grep -c 'set WITAN_NODE_TOKEN in .env' || true)" 1

echo "== [2] up with a token =="
env_file "WITAN_NODE_TOKEN=$TOKEN"
C up -d --quiet-pull >/dev/null 2>&1 || C up -d
check "health" "$(wait_state healthy)" healthy/running
check "no token" "$(curl -s -o /dev/null -w '%{http_code}' "$N/projects")" 401
check "with the token" "$(curl -s -o /dev/null -w '%{http_code}' -H "authorization: Bearer $TOKEN" "$N/projects")" 200
check "published on 127.0.0.1 only" "$(docker port "$(C ps -q witan-node)" 8686/tcp | sort -u | tr '\n' ' ')" "127.0.0.1:$PORT "
check "read-only root" "$(docker inspect -f '{{.HostConfig.ReadonlyRootfs}}' "$(C ps -q witan-node)")" true
C down -v >/dev/null 2>&1

echo "== [3] verify, origin unreachable, nothing pinned =="
env_file "WITAN_NODE_TOKEN=$TOKEN" "WITAN_FOLLOW=some-dataset" "WITAN_VERIFY=1" "WITAN_BASE_URL=http://127.0.0.1:9"
# a one-off run: no restart policy, so its exit code is the entrypoint's
set +e; OUT=$(C run --rm -T witan-node 2>&1); RC=$?; set -e
check "exits 69" "$RC" 69
check "says why" "$(echo "$OUT" | grep -c 'could not be reached to pin them' || true)" 1
C down >/dev/null 2>&1   # keeps the volume for [4]

echo "== [4] verify, origin unreachable, keys already in the volume =="
VOL=${P}_witan-data
docker run --rm -v "$VOL:/data" --entrypoint sh "$IMAGE" -c 'echo "{\"origins\": {}}" > /data/trust.json'
C up -d >/dev/null 2>&1
check "serves anyway" "$(wait_state healthy)" healthy/running
check "says so" "$(C logs witan-node 2>&1 | grep -c 'serving with the keys already pinned' || true)" 1
check "follows with --verify" "$(docker top "$(C ps -q witan-node)" | grep -c -- '--verify --follow some-dataset' || true)" 1
C down -v >/dev/null 2>&1

echo "== [5] the token from a file =="
echo "$TOKEN" > "$T/token" && chmod 644 "$T/token"
docker run -d --name "$P-secret" -p "127.0.0.1:$PORT:8686" --mount "type=bind,src=$T/token,dst=/run/secrets/witan_node_token,readonly" \
  -e WITAN_NODE_TOKEN_FILE=/run/secrets/witan_node_token --read-only --tmpfs /tmp "$IMAGE" >/dev/null
up=0; for _ in $(seq 1 60); do curl -sf "$N/healthz" >/dev/null 2>&1 && { up=1; break; }; sleep 0.5; done
check "starts" "$up" 1
check "with the token" "$(curl -s -o /dev/null -w '%{http_code}' -H "authorization: Bearer $TOKEN" "$N/projects")" 200
check "token not in the environment docker inspect shows" "$(docker inspect -f '{{json .Config.Env}}' "$P-secret" | grep -c "$TOKEN" || true)" 0

[ "$FAIL" = 0 ] && echo "COMPOSE PASS ($IMAGE)" || { echo "COMPOSE FAILED ($IMAGE)"; exit 1; }

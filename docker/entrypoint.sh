#!/bin/sh
# witan-node — the container's entrypoint.
#   (nothing) or options first   wtn serve over /data/witan-data on every interface, port
#                                $WITAN_NODE_PORT (8686); the options go to serve (--follow, --read-only, ...)
#   a wtn command                wtn <command> ... with /data as the working directory, so pull and
#                                load fill the same store serve reads (pull, load, trust add, query, ...)
#   --version                    wtn --version
#
# Serving can also be set from the environment, as docker/docker-compose.yml does:
#   WITAN_FOLLOW="a b"           --follow a b (space-separated slugs), every WITAN_FOLLOW_INTERVAL seconds (600)
#   WITAN_VERIFY=1               --verify; the origin's keys are pinned first (wtn trust add), and a node
#                                that already holds them still starts when the origin cannot be reached
#   WITAN_NODE_TOKEN_FILE        read the token from this file (Docker/Compose secrets); WITAN_API_KEY_FILE too
set -eu

case "${1:-}" in
  --version|-V) exec wtn --version ;;
  --help|-h) exec wtn serve --help ;;
esac

# *_FILE: the value from a mounted secret rather than the environment docker inspect shows
for v in WITAN_NODE_TOKEN WITAN_API_KEY; do
  eval "f=\${${v}_FILE:-}"
  if [ -n "$f" ]; then
    [ -r "$f" ] || { echo "witan-node: ${v}_FILE=$f is not readable" >&2; exit 64; }
    eval "export $v=\"\$(cat \"\$f\")\""
  fi
done

truthy() { case "$(printf '%s' "${1:-}" | tr '[:upper:]' '[:lower:]')" in 1|true|yes) return 0 ;; esac; return 1; }

if [ "$#" -eq 0 ] || [ "${1#-}" != "$1" ]; then
  if [ -z "${WITAN_NODE_TOKEN:-}" ]; then
    echo "witan-node: set WITAN_NODE_TOKEN (a long random string) — a node listening beyond its container needs a token" >&2
    exit 64
  fi
  if [ -n "${WITAN_FOLLOW:-}" ]; then
    # shellcheck disable=SC2086  # the slugs are space-separated on purpose
    set -- --follow $WITAN_FOLLOW --interval "${WITAN_FOLLOW_INTERVAL:-600}" "$@"
    if truthy "${WITAN_VERIFY:-}"; then
      set -- --verify "$@"
      # pin (or refresh after a rotation) the origin's signing keys before following it
      if ! wtn trust add >&2; then
        [ -s "${WITAN_TRUST_FILE:-/data/trust.json}" ] \
          || { echo "witan-node: WITAN_VERIFY=1 needs the origin's keys and ${WITAN_BASE_URL:-the origin} could not be reached to pin them" >&2; exit 69; }
        echo "witan-node: the origin could not be reached; serving with the keys already pinned" >&2
      fi
    fi
  fi
  # the token stays in the environment (serve reads WITAN_NODE_TOKEN), never on the command line
  exec wtn serve --store /data/witan-data --host 0.0.0.0 --port "${WITAN_NODE_PORT:-8686}" "$@"
fi

exec wtn "$@"

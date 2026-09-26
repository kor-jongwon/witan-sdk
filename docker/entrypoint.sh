#!/bin/sh
# witan-node — the container's entrypoint.
#   (nothing) or options first   wtn serve over /data/witan-data on every interface, port
#                                $WITAN_NODE_PORT (8686); the options go to serve (--follow, --read-only, ...)
#   a wtn command                wtn <command> ... with /data as the working directory, so pull and
#                                load fill the same store serve reads (pull, load, trust add, query, ...)
#   --version                    wtn --version
set -eu

case "${1:-}" in
  --version|-V) exec wtn --version ;;
  --help|-h) exec wtn serve --help ;;
esac

if [ "$#" -eq 0 ] || [ "${1#-}" != "$1" ]; then
  if [ -z "${WITAN_NODE_TOKEN:-}" ]; then
    echo "witan-node: set WITAN_NODE_TOKEN (a long random string) — a node listening beyond its container needs a token" >&2
    exit 64
  fi
  # the token stays in the environment (serve reads WITAN_NODE_TOKEN), never on the command line
  exec wtn serve --store /data/witan-data --host 0.0.0.0 --port "${WITAN_NODE_PORT:-8686}" "$@"
fi

exec wtn "$@"

#!/usr/bin/env bash
set -euo pipefail
app_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
config=${ROUTE_OVS_CONFIG_FILE:-/etc/route-ovs/route-ovs.env}
if [[ -f "$config" ]]; then
    set -a
    source "$config"
    set +a
fi
args=(--host "${ROUTE_OVS_HOST:-127.0.0.1}" --port "${ROUTE_OVS_PORT:-8090}"
      --data-dir "${ROUTE_OVS_DATA_DIR:-/var/lib/route-ovs}")
if [[ -n "${ROUTE_OVS_TRUSTED_PROXY:-}" ]]; then
    args+=(--trusted-proxy "$ROUTE_OVS_TRUSTED_PROXY")
fi
exec "$app_dir/route-ovs" "${args[@]}" "$@"

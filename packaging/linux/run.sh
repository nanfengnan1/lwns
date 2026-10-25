#!/usr/bin/env bash
set -euo pipefail
app_dir=$(dirname -- "$(readlink -f -- "${BASH_SOURCE[0]}")")
config=${LWNS_CONFIG_FILE:-${ROUTE_OVS_CONFIG_FILE:-/etc/lwns/lwns.env}}
if [[ -z ${LWNS_CONFIG_FILE:-} && -z ${ROUTE_OVS_CONFIG_FILE:-} && ! -f $config && -f /etc/route-ovs/route-ovs.env ]]; then
    config=/etc/route-ovs/route-ovs.env
fi
if [[ -f "$config" ]]; then
    set -a
    source "$config"
    set +a
fi
data_default=/var/lib/lwns
if [[ ! -e $data_default && -d /var/lib/route-ovs ]]; then data_default=/var/lib/route-ovs; fi
export LWNS_DATA_DIR="${LWNS_DATA_DIR:-${ROUTE_OVS_DATA_DIR:-$data_default}}"
export LWNS_TOKEN="${LWNS_TOKEN:-${ROUTE_OVS_TOKEN:-}}"
if [[ "${1:-}" == "device" ]]; then
    exec "$app_dir/lwns" "$@"
fi
args=(--host "${LWNS_HOST:-${ROUTE_OVS_HOST:-127.0.0.1}}" --port "${LWNS_PORT:-${ROUTE_OVS_PORT:-8090}}"
      --data-dir "$LWNS_DATA_DIR")
proxy=${LWNS_TRUSTED_PROXY:-${ROUTE_OVS_TRUSTED_PROXY:-}}
if [[ -n $proxy ]]; then
    args+=(--trusted-proxy "$proxy")
fi
exec "$app_dir/lwns" "${args[@]}" "$@"

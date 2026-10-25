#!/usr/bin/env bash
set -euo pipefail
umask 022
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
root='' systemd=1 host=127.0.0.1 port=8090 data_dir=/var/lib/lwns proxy=''
usage() {
    cat <<'EOF'
Usage: sudo bash install.sh [--listen ADDRESS] [--port PORT] [--data-dir /PATH]
                            [--trusted-proxy IP/CIDR] [--no-systemd]
       bash install.sh --root /STAGING/DIRECTORY --no-systemd
Settings apply to the first installation only. Existing configuration is preserved.
The service is enabled but not started. Stop it before installing an upgrade.
EOF
}
while (($#)); do
    case "$1" in
        --listen|--port|--data-dir|--trusted-proxy|--root)
            (($# >= 2)) || die "Missing value: $1"
            case "$1" in
                --listen) host=$2;; --port) port=$2;; --data-dir) data_dir=$2;;
                --trusted-proxy) proxy=$2;; --root) root=$2;;
            esac
            shift 2;;
        --no-systemd) systemd=0; shift;;
        --help|-h) usage; exit 0;;
        *) die "Unknown argument: $1";;
    esac
done
[[ $(uname -s) == Linux ]] || die 'Linux is required.'
[[ $port =~ ^[0-9]{1,5}$ ]] && ((10#$port >= 1 && 10#$port <= 65535)) || die 'Invalid port.'
[[ $host =~ ^[a-zA-Z0-9.:-]+$ ]] || die 'Invalid listen address.'
[[ -z $proxy || $proxy =~ ^[a-zA-Z0-9.:/]+$ ]] || die 'Invalid trusted proxy.'
[[ $data_dir == /* && $data_dir != / && $data_dir != *$'\n'* ]] || die 'Use an absolute data directory.'
data_dir=$(realpath -m -- "$data_dir")
[[ $data_dir != / ]] || die 'The data directory cannot be the filesystem root.'
if [[ -n $root ]]; then
    [[ $root == /* && $root != *$'\n'* ]] || die 'Staging root must be absolute.'
    root=$(realpath -m -- "$root")
    [[ $root != / && $systemd == 0 ]] || die 'Staging requires a non-root directory and --no-systemd.'
else
    ((EUID == 0)) || die 'Run with sudo to install into system directories.'
fi
bundle=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)
build_id=$(cat "$bundle/BUILD_ID")
[[ $build_id =~ ^[A-Za-z0-9][A-Za-z0-9._+-]{0,127}$ ]] || die 'Invalid BUILD_ID.'
prefix=$root/opt/lwns
config_dir=$root/etc/lwns
config=$config_dir/lwns.env
unit=$root/etc/systemd/system/lwns-web.service
command=$root/usr/local/bin/lwns
target=$prefix/releases/$build_id
marker='Managed by lwns directory installer v1'

# Refuse symlinked writable/install locations before changing anything.
for location in "$prefix" "$config_dir" "$root/var/lib/lwns" "$root$data_dir" "${unit%/*}" "${command%/*}"; do
    cursor=$location
    while [[ $cursor != / ]]; do
        [[ ! -L $cursor ]] || die "Symlinked installation path: $cursor"
        cursor=$(dirname -- "$cursor")
    done
done
[[ ! -L $config && ! -L $unit && ! -L $target ]] || die 'Configuration, service or release path is a symlink.'
[[ ! -e $config || -f $config ]] || die 'Configuration path must be a regular file.'
if [[ -e $prefix ]]; then
    [[ -f $prefix/.directory-install-v1 ]] || die "Unmanaged directory: $prefix"
fi
if [[ -e $command || -L $command ]]; then
    [[ -L $command && $(readlink -- "$command") == "$prefix/current/run.sh" ]] || die "Unmanaged command: $command"
fi
if [[ -e $unit ]]; then
    grep -Fxq "# $marker" "$unit" || die "Existing service is not managed by this installer: $unit"
fi
if [[ -e $prefix/current || -L $prefix/current ]]; then
    [[ -L $prefix/current && $(readlink -- "$prefix/current") =~ ^releases/[A-Za-z0-9][A-Za-z0-9._+-]*$ ]] || die 'Unmanaged current release link.'
fi
if ((systemd)); then
    [[ -d /run/systemd/system ]] && command -v systemctl >/dev/null || die 'No running systemd; use --no-systemd.'
fi
if [[ -z $root && -d /run/systemd/system ]] && command -v systemctl >/dev/null; then
    legacy_state=$(systemctl is-active route-ovs-web.service 2>/dev/null || true)
    case "$legacy_state" in
        active|activating|deactivating|reloading) die 'Stop the previous service before installing lwns: sudo systemctl stop route-ovs-web';;
    esac
    fragment=$(systemctl show lwns-web.service -p FragmentPath --value 2>/dev/null || true)
    [[ -z $fragment || $fragment == "$unit" ]] || die "Existing service comes from another location: $fragment"
    dropins=$(systemctl show lwns-web.service -p DropInPaths --value 2>/dev/null || true)
    [[ -z $dropins ]] || die "Review and remove existing service overrides before installation: $dropins"
    state=$(systemctl is-active lwns-web.service 2>/dev/null || true)
    case "$state" in
        active|activating|deactivating|reloading) die 'Stop lwns-web before installation: sudo systemctl stop lwns-web';;
    esac
fi
(cd -- "$bundle" && sha256sum --check --strict --quiet SHA256SUMS) || die 'Package checksum verification failed.'
"$bundle/app/lwns" --help >/dev/null || die 'Executable is incompatible with this host; check architecture and glibc.'
if [[ -e $target ]]; then
    diff -qr -- "$bundle/app" "$target" >/dev/null || die 'This build ID is already installed with different files.'
fi

install -d -m 755 -- "$prefix/releases" "${command%/*}"
if [[ ! -e $target ]]; then
    pending=$(mktemp -d "$prefix/releases/.install-XXXXXXXX")
    trap 'if [[ -n ${pending:-} && -d $pending ]]; then rm -rf -- "$pending"; fi' EXIT
    cp -a -- "$bundle/app/." "$pending/"
    chmod -R go-w -- "$pending"
    chmod 755 -- "$pending"
    if ((EUID == 0)); then chown -hR root:root -- "$pending"; fi
    mv -T -- "$pending" "$target"
    pending=''
fi
touch "$prefix/.directory-install-v1"
[[ -d $config_dir ]] || install -d -m 700 -- "$config_dir"
[[ -d $root/var/lib/lwns ]] || install -d -m 700 -- "$root/var/lib/lwns"
[[ -d $root$data_dir ]] || install -d -m 700 -- "$root$data_dir"
if [[ ! -e $config ]]; then
    token=$(od -An -N32 -tx1 /dev/urandom | tr -d ' \n')
    (umask 077
     {
     printf '# %s\n' "$marker"
     printf 'LWNS_HOST=%q\nLWNS_PORT=%q\n' "$host" "$port"
     printf 'LWNS_DATA_DIR=%q\nLWNS_TRUSTED_PROXY=%q\n' "$data_dir" "$proxy"
     printf 'LWNS_TOKEN=%q\n' "$token"
     } > "$config")
    chmod 600 -- "$config"
else
    printf 'Keeping existing configuration: %s\n' "$config"
fi
if ((systemd)); then
    install -d -m 755 -- "${unit%/*}"
    install -m 644 -- "$bundle/lwns-web.service" "$unit"
fi
next_link=$prefix/.current-next-$$
ln -s -- "releases/$build_id" "$next_link"
mv -Tf -- "$next_link" "$prefix/current"
if [[ ! -L $command ]]; then ln -s -- "$prefix/current/run.sh" "$command"; fi
if ((systemd)); then
    systemctl daemon-reload
    systemctl enable lwns-web.service
fi
printf 'Installed: %s\nConfiguration: %s\n' "$target" "$config"
if ((systemd)); then
    printf 'Start: sudo systemctl start lwns-web\n'
else
    printf 'Service registration skipped. Start with %s (set LWNS_CONFIG_FILE when staging).\n' "$command"
fi
printf 'Host dependencies: Docker Engine/CLI, iproute2, util-linux; tcpdump and SSH for capture.\n'

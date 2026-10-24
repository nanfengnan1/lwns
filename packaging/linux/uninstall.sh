#!/usr/bin/env bash
set -euo pipefail
die() { printf 'Error: %s\n' "$*" >&2; exit 1; }
root='' systemd=1
while (($#)); do
    case "$1" in
        --root) (($# >= 2)) || die 'Missing staging root'; root=$2; shift 2;;
        --no-systemd) systemd=0; shift;;
        --help|-h) echo 'Usage: sudo bash uninstall.sh [--no-systemd] [--root /STAGING/DIRECTORY]'; exit 0;;
        *) die "Unknown argument: $1";;
    esac
done
if [[ -n $root ]]; then
    [[ $root == /* && $root != *$'\n'* ]] || die 'Staging root must be absolute.'
    root=$(realpath -m -- "$root")
    [[ $root != / && $systemd == 0 ]] || die 'Staging requires a non-root directory and --no-systemd.'
else
    ((EUID == 0)) || die 'Run with sudo.'
fi
prefix=$root/opt/route-ovs
unit=$root/etc/systemd/system/route-ovs-web.service
command=$root/usr/local/bin/route-ovs
for location in "$prefix" "${unit%/*}" "${command%/*}"; do
    cursor=$location
    while [[ $cursor != / ]]; do
        [[ ! -L $cursor ]] || die "Symlinked installation path: $cursor"
        cursor=$(dirname -- "$cursor")
    done
done
[[ -f $prefix/.directory-install-v1 ]] || die 'Not a directory-package installation.'
[[ ! -L $unit ]] || die 'Service file is a symlink.'
if [[ -e $unit ]]; then
    grep -Fxq '# Managed by route-ovs directory installer v1' "$unit" || die 'Unmanaged service file.'
    if [[ -z $root && $systemd == 0 ]]; then
        die 'A systemd service is registered; omit --no-systemd so it is stopped and disabled.'
    fi
fi
if [[ -e $command || -L $command ]]; then
    [[ -L $command && $(readlink -- "$command") == "$prefix/current/run.sh" ]] || die 'Unmanaged command.'
fi
if ((systemd)) && [[ -e $unit ]]; then
    systemctl disable --now route-ovs-web.service
fi
[[ ! -L $command ]] || rm -- "$command"
if [[ -e $unit ]]; then rm -- "$unit"; fi
if ((systemd)); then systemctl daemon-reload; fi
# prefix is fixed below the checked root and contains our installation marker.
rm -rf -- "$prefix"
printf 'Program removed. Configuration, experiment data, Docker images and containers were retained.\n'

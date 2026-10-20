#!/usr/bin/env bash
# Docker's official Ubuntu repository: https://docs.docker.com/engine/install/ubuntu/
set -euo pipefail

if [[ $EUID -eq 0 ]]; then
    printf '%s\n' 'Run this script as your normal desktop user; it requests sudo itself.' >&2
    exit 1
fi
source /etc/os-release
if [[ ${ID:-} != ubuntu || ${VERSION_ID:-} != 24.04 ]]; then
    printf '%s\n' 'This workspace installer targets Ubuntu 24.04.' >&2
    exit 1
fi
workspace_user=$(id -un)
sudo -v
sudo apt-get update
sudo apt-get install -y ca-certificates curl git python3-yaml v4l-utils

if ! command -v docker >/dev/null 2>&1; then
    task_tmp=$(mktemp -d)
    trap 'rm -rf "$task_tmp"' EXIT
    curl --fail --silent --show-error --location \
        https://download.docker.com/linux/ubuntu/gpg -o "$task_tmp/docker.asc"
    sudo install -d -m 0755 /etc/apt/keyrings
    sudo install -m 0644 "$task_tmp/docker.asc" /etc/apt/keyrings/docker.asc
    cat > "$task_tmp/docker.sources" <<EOF
Types: deb
URIs: https://download.docker.com/linux/ubuntu
Suites: ${UBUNTU_CODENAME:-$VERSION_CODENAME}
Components: stable
Architectures: $(dpkg --print-architecture)
Signed-By: /etc/apt/keyrings/docker.asc
EOF
    sudo install -m 0644 "$task_tmp/docker.sources" /etc/apt/sources.list.d/docker.sources
    sudo apt-get update
    sudo apt-get install -y docker-ce docker-ce-cli containerd.io \
        docker-buildx-plugin docker-compose-plugin
fi

sudo systemctl enable --now docker
sudo usermod -aG docker,dialout,video "$workspace_user"
docker --version
docker compose version
printf '%s\n' 'Host dependencies installed. Robot motion has not been started.'
printf '%s\n' 'The workspace commands use sg docker when the current login has not refreshed its groups.'

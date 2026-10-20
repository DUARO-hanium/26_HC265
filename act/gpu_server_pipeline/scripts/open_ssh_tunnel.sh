#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

[[ -n "${SSH_TARGET:-}" && "$SSH_TARGET" != "gpu-server" ]] || {
  echo "Set SSH_TARGET in .env" >&2; exit 2;
}
listener=$(ss -H -ltnp "( sport = :${LOCAL_POLICY_PORT} )" 2>/dev/null || true)
if [[ -n "$listener" ]]; then
  pid=$(sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' <<<"$listener" | head -1)
  cmdline=""
  [[ -n "$pid" && -r "/proc/$pid/cmdline" ]] && cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
  expected="127.0.0.1:${LOCAL_POLICY_PORT}:127.0.0.1:${REMOTE_POLICY_PORT}"
  if [[ "$cmdline" == ssh\ * && "$cmdline" == *"$expected"* && "$cmdline" == *"$SSH_TARGET"* ]]; then
    echo "Existing intended SSH tunnel is active: pid=$pid"
    exit 0
  fi
  echo "Port $LOCAL_POLICY_PORT is owned by an unexpected process; inspect it first." >&2
  echo "$listener" >&2
  exit 2
fi
exec ssh -N \
  -L "127.0.0.1:${LOCAL_POLICY_PORT}:127.0.0.1:${REMOTE_POLICY_PORT}" \
  -o ExitOnForwardFailure=yes -o ServerAliveInterval=15 -o ServerAliveCountMax=3 \
  "$SSH_TARGET"

#!/usr/bin/env bash
set -Eeuo pipefail
source "$(dirname "${BASH_SOURCE[0]}")/common.sh"
load_omx_env

listener=$(ss -H -ltnp "( sport = :${LOCAL_POLICY_PORT} )" 2>/dev/null || true)
[[ -n "$listener" ]] || { echo "No local policy listener."; exit 0; }
pid=$(sed -n 's/.*pid=\([0-9][0-9]*\).*/\1/p' <<<"$listener" | head -1)
cmdline=""
[[ -n "$pid" && -r "/proc/$pid/cmdline" ]] && cmdline=$(tr '\0' ' ' <"/proc/$pid/cmdline")
expected="127.0.0.1:${LOCAL_POLICY_PORT}:127.0.0.1:${REMOTE_POLICY_PORT}"
if [[ "$cmdline" != ssh\ * || "$cmdline" != *"$expected"* || "$cmdline" != *"$SSH_TARGET"* ]]; then
  echo "Refusing to stop an unexpected listener: $listener" >&2; exit 2
fi
kill -TERM "$pid"
echo "Stopped intended SSH tunnel pid=$pid"

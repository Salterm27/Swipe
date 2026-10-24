#!/bin/bash
# Pull-based auto-deploy, same as WatchPi's: checks GitHub every 10 minutes
# (see the timer); if main has new commits, updates the app and restarts it,
# rolling back if /api/health doesn't answer afterwards.
# Runs as root via swipe-deploy.service — no webhooks, no exposed ports.

set -euo pipefail
REPO=/srv/apps/swipe
BRANCH=main
APPUSER=sebas
SERVICE=swipe
PORT=8002   # keep in sync with SWIPE_PORT in deploy/swipe.service

healthy() {
  for _ in $(seq 1 10); do
    if curl -sf "http://localhost:$PORT/api/health" >/dev/null; then return 0; fi
    sleep 2
  done
  return 1
}

# run git as the repo owner — root running git in a user-owned repo trips
# git's "dubious ownership" safety check
GIT() { runuser -u "$APPUSER" -- git -C "$REPO" "$@"; }

install_and_restart() {
  runuser -u "$APPUSER" -- "$REPO/venv/bin/pip" install -q -r "$REPO/requirements.txt"
  cp "$REPO/deploy/$SERVICE.service" /etc/systemd/system/
  chmod +x "$REPO/deploy/autodeploy.sh"   # web uploads drop the exec bit
  systemctl daemon-reload
  systemctl restart "$SERVICE"
}

GIT fetch --quiet origin "$BRANCH"
LOCAL=$(GIT rev-parse HEAD)
REMOTE=$(GIT rev-parse "origin/$BRANCH")

[ "$LOCAL" = "$REMOTE" ] && exit 0   # nothing new — the common case

echo "deploying $LOCAL -> $REMOTE"
GIT reset --hard "origin/$BRANCH"
install_and_restart

if healthy; then
  echo "deployed $(GIT log -1 --oneline)"
  exit 0
fi

echo "health check FAILED after deploy — ROLLING BACK to $LOCAL"
GIT reset --hard "$LOCAL"
install_and_restart
if healthy; then
  echo "ROLLED BACK to $(GIT log -1 --oneline) — fix $REMOTE and push again"
else
  echo "ROLLBACK ALSO UNHEALTHY — manual intervention needed (journalctl -u $SERVICE)"
fi
exit 1

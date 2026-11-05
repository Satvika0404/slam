#!/usr/bin/env bash
# Start the Ghost Data Console (dashboard plus live analysis) with one command.
# Needs Docker and the participant dataset in ./dataset. Nothing is sent anywhere; the console
# listens on 127.0.0.1 only.
#
#   scripts/run_console.sh                 start, wait, open the browser
#   scripts/run_console.sh --refresh       rebuild the dashboard data and stored insight data first
#   scripts/run_console.sh --port 9000     use another host port
#   scripts/run_console.sh --no-browser    do not open the browser
#   scripts/run_console.sh --stop          stop the console and Neo4j
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=8765
REFRESH=""
OPEN=1
while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --refresh) REFRESH=1; shift ;;
    --no-browser) OPEN=0; shift ;;
    --stop) docker compose --profile console down; exit 0 ;;
    -h|--help) sed -n '2,11p' "$0"; exit 0 ;;
    *) echo "unknown option: $1" >&2; exit 2 ;;
  esac
done

step() { printf '==> %s\n' "$1"; }

docker info >/dev/null 2>&1 || {
  echo "Docker is not running. Start Docker, then run this again." >&2
  exit 1
}
[ -f dataset/deletion_requests.csv ] || {
  echo "The participant dataset is missing: dataset/deletion_requests.csv must exist." >&2
  exit 1
}

# .env: create it, and give Neo4j a password when there is none (the file is gitignored)
if [ ! -f .env ]; then
  cp .env.example .env
  step "created .env from .env.example"
fi
[ -z "$(tail -c1 .env)" ] || echo >> .env
grep -q '^NEO4J_URI=' .env || echo 'NEO4J_URI=bolt://neo4j:7687' >> .env
grep -q '^NEO4J_USER=' .env || echo 'NEO4J_USER=neo4j' >> .env
if ! grep -q '^NEO4J_PASSWORD=' .env; then
  password="$(head -c 48 /dev/urandom | base64 | tr -dc 'A-Za-z0-9' | head -c 24)"
  echo "NEO4J_PASSWORD=$password" >> .env
  step "generated a local Neo4j password in .env"
elif ! grep -Eq '^NEO4J_PASSWORD=[^[:space:]]{8,}' .env; then
  echo "NEO4J_PASSWORD in .env must be at least 8 characters." >&2
  exit 1
fi
grep -q '^SLAM_CONSOLE_PROVIDER=' .env || {
  echo "    Live runs explain cases with rules. For model-written explanations add GROQ_API_KEYS and"
  echo "    SLAM_API_MAX_CALLS, then SLAM_CONSOLE_PROVIDER=groq and SLAM_CONSOLE_MODEL=<model id>."
}

export SLAM_CONSOLE_PORT="$PORT"
export SLAM_CONSOLE_REFRESH="$REFRESH"
docker rm -f slam-live >/dev/null 2>&1 || true   # a console started by hand with an older command
step "starting Neo4j"
docker compose --profile console up -d neo4j
step "starting the console (the first start builds the image and audits all 518 cases, about a minute)"
docker compose --profile console up -d --force-recreate console

url="http://127.0.0.1:$PORT"
step "waiting for $url"
for _ in $(seq 1 160); do
  if curl -fs -m 3 "$url/api/status" 2>/dev/null | grep -q '"live": *true'; then
    printf '\nConsole ready: %s\n' "$url"
    printf '  Stop : scripts/run_console.sh --stop\n  Log  : docker compose --profile console logs -f console\n'
    if [ "$OPEN" = 1 ]; then
      (xdg-open "$url" || open "$url" || start "$url") >/dev/null 2>&1 || true
    fi
    exit 0
  fi
  state="$(docker inspect -f '{{.State.Status}}' slam-console-1 2>/dev/null || true)"
  if [ "$state" = exited ] || [ "$state" = dead ]; then
    docker compose --profile console logs --tail 25 console
    echo "The console stopped while starting. The last log lines are above." >&2
    exit 1
  fi
  sleep 3
done
echo "The console did not answer in time. Run: docker compose --profile console logs console" >&2
exit 1

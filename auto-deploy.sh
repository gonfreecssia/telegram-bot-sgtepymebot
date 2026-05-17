#!/bin/bash
# Auto-deploy script: git pull + build + restart
# Run via cron: */5 * * * * /home/kanon/telegram-bot/auto-deploy.sh

set -e

REPO_DIR="/home/kanon/telegram-bot"
IMAGE_NAME="ghcr.io/gonfreecssia/telegram-bot-sgtepymebot"
CONTAINER_NAME="telegram-bot"
ENV_FILE="$REPO_DIR/.env"
GH_TOKEN_FILE="/home/kanon/.gh_token"
LOCK_FILE="/tmp/telegram-bot-deploy.lock"

# Prevent concurrent runs
if [ -f "$LOCK_FILE" ]; then
    exit 0
fi
touch "$LOCK_FILE"
trap "rm -f $LOCK_FILE" EXIT

cd "$REPO_DIR"

# Get GitHub token
GH_TOKEN=$(cat "$GH_TOKEN_FILE" 2>/dev/null) || GH_TOKEN=$(gh auth token 2>/dev/null)

echo "[$(date)] Checking for updates..."

# Fetch and check
git fetch origin
CURRENT_COMMIT=$(git rev-parse HEAD)
LATEST_COMMIT=$(git rev-parse origin/master)

if [ "$CURRENT_COMMIT" = "$LATEST_COMMIT" ]; then
    echo "[$(date)] Already up to date: $CURRENT_COMMIT"
    exit 0
fi

echo "[$(date)] New commit detected: $LATEST_COMMIT"

# Pull code
git pull origin master

# Trigger GitHub Actions to build image
if [ -n "$GH_TOKEN" ]; then
    echo "[$(date)] Triggering GitHub Actions..."
    curl -s -X POST \
        -H "Authorization: token $GH_TOKEN" \
        -H "Accept: application/vnd.github.v3+json" \
        -d '{"ref": "master"}' \
        "https://api.github.com/repos/gonfreecssia/telegram-bot-sgtepymebot/actions/workflows/deploy.yml/dispatches"
fi

# Wait for image to be built and available (max 5 minutes)
echo "[$(date)] Waiting for Docker image..."
TIMEOUT=300
INTERVAL=10
ELAPSED=0

while [ $ELAPSED -lt $TIMEOUT ]; do
    if sudo docker manifest inspect "$IMAGE_NAME:$LATEST_COMMIT" >/dev/null 2>&1; then
        echo "[$(date)] Image available: $IMAGE_NAME:$LATEST_COMMIT"
        break
    fi
    sleep $INTERVAL
    ELAPSED=$((ELAPSED + INTERVAL))
    echo "[$(date)] Waiting... ($ELAPSED/$TIMEOUT)s"
done

if [ $ELAPSED -ge $TIMEOUT ]; then
    echo "[$(date)] Timeout waiting for image"
    exit 1
fi

# Deploy
echo "[$(date)] Deploying..."
sudo docker pull "$IMAGE_NAME:$LATEST_COMMIT"
sudo docker stop "$CONTAINER_NAME" 2>/dev/null || true
sudo docker rm "$CONTAINER_NAME" 2>/dev/null || true
sudo docker run -d \
    --name "$CONTAINER_NAME" \
    --restart unless-stopped \
    --env-file "$ENV_FILE" \
    "$IMAGE_NAME:$LATEST_COMMIT"

# Cleanup
sudo docker image prune -f

echo "[$(date)] Deployment complete!"
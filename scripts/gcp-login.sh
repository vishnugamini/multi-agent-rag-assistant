#!/usr/bin/env bash
set -euo pipefail
ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
export CLOUDSDK_CONFIG="$ROOT_DIR/.local/gcloud-config"
export CLOUDSDK_PYTHON="$ROOT_DIR/.venv/bin/python"
GCLOUD="$ROOT_DIR/.local/google-cloud-sdk/bin/gcloud"
"$GCLOUD" auth login
"$GCLOUD" auth application-default login
"$GCLOUD" projects list --format='table(projectId,name)'

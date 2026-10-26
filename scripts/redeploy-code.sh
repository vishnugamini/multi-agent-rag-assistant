#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?Export GCP_PROJECT_ID}"
GCP_REGION="${GCP_REGION:-us-west1}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-agentic-ai}"
REVISION="$(gcloud run services describe "$CLOUD_RUN_SERVICE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format='value(status.latestReadyRevisionName)')"
BASE_IMAGE="$(gcloud run revisions describe "$REVISION" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" --format='value(status.imageDigest)')"
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/agentic-ai/app:code-$(date -u +%Y%m%d%H%M%S)"
gcloud builds submit --config=scripts/cloudbuild-code.yaml --substitutions="_BASE_IMAGE=${BASE_IMAGE},_IMAGE=${IMAGE}" --project="$GCP_PROJECT_ID" .
gcloud run deploy "$CLOUD_RUN_SERVICE" --image="$IMAGE" --update-env-vars="SUPERVISOR_MODEL=gpt-6-luna,SUPERVISOR_REASONING_EFFORT=none" --region="$GCP_REGION" --project="$GCP_PROJECT_ID"

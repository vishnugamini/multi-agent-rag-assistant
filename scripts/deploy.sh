#!/usr/bin/env bash
set -euo pipefail
: "${GCP_PROJECT_ID:?Export GCP_PROJECT_ID}"
: "${GCS_STATE_BUCKET:?Export GCS_STATE_BUCKET}"
GCP_REGION="${GCP_REGION:-us-west1}"
CLOUD_RUN_SERVICE="${CLOUD_RUN_SERVICE:-agentic-ai}"
SERVICE_ACCOUNT="agentic-runtime@${GCP_PROJECT_ID}.iam.gserviceaccount.com"
IMAGE="${GCP_REGION}-docker.pkg.dev/${GCP_PROJECT_ID}/agentic-ai/app:$(date -u +%Y%m%d%H%M%S)"
gcloud services enable run.googleapis.com cloudbuild.googleapis.com artifactregistry.googleapis.com storage.googleapis.com secretmanager.googleapis.com --project="$GCP_PROJECT_ID"
if ! gcloud iam service-accounts describe "$SERVICE_ACCOUNT" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud iam service-accounts create agentic-runtime --project="$GCP_PROJECT_ID"
fi
if ! gcloud storage buckets describe "gs://${GCS_STATE_BUCKET}" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud storage buckets create "gs://${GCS_STATE_BUCKET}" --location="$GCP_REGION" --uniform-bucket-level-access --public-access-prevention --project="$GCP_PROJECT_ID"
fi
for IAM_ATTEMPT in 1 2 3 4 5 6; do
  if gcloud storage buckets add-iam-policy-binding "gs://${GCS_STATE_BUCKET}" --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/storage.objectUser; then
    break
  fi
  if [ "$IAM_ATTEMPT" = 6 ]; then exit 1; fi
  sleep 5
done
if ! gcloud artifacts repositories describe agentic-ai --location="$GCP_REGION" --project="$GCP_PROJECT_ID" >/dev/null 2>&1; then
  gcloud artifacts repositories create agentic-ai --repository-format=docker --location="$GCP_REGION" --project="$GCP_PROJECT_ID"
fi
# Populate these secrets with scripts/upload_secrets.py before deployment.
for SECRET_NAME in OPENAI_API_KEY NVIDIA_API_KEY TAVILY_API_KEY PINECONE_API_KEY; do
  gcloud secrets describe "$SECRET_NAME" --project="$GCP_PROJECT_ID" >/dev/null
  gcloud secrets add-iam-policy-binding "$SECRET_NAME" --member="serviceAccount:${SERVICE_ACCOUNT}" --role=roles/secretmanager.secretAccessor --project="$GCP_PROJECT_ID" >/dev/null
done
gcloud builds submit --tag "$IMAGE" --project="$GCP_PROJECT_ID" .
gcloud run deploy "$CLOUD_RUN_SERVICE" --image="$IMAGE" --project="$GCP_PROJECT_ID" --region="$GCP_REGION" \
  --service-account="$SERVICE_ACCOUNT" --allow-unauthenticated --cpu=1 --memory=1Gi \
  --min-instances=0 --max-instances=2 --concurrency=5 --timeout=300 --port=8080 \
  --set-env-vars="STATE_BACKEND=gcs,GCS_STATE_BUCKET=${GCS_STATE_BUCKET},PINECONE_INDEX=${PINECONE_INDEX:-agentic-ai-docs},PINECONE_NAMESPACE=${PINECONE_NAMESPACE:-docs-v1},OPENAI_MODEL=gpt-6.1-sol,SUPERVISOR_MODEL=gpt-6-luna,SUPERVISOR_REASONING_EFFORT=none,SUPERVISOR_INPUT_PER_MILLION=0.1,SUPERVISOR_OUTPUT_PER_MILLION=0.5,NVIDIA_MODEL=nvidia/nemotron-3.5-lightning-30b-a3b" \
  --set-secrets=OPENAI_API_KEY=OPENAI_API_KEY:latest,NVIDIA_API_KEY=NVIDIA_API_KEY:latest,TAVILY_API_KEY=TAVILY_API_KEY:latest,PINECONE_API_KEY=PINECONE_API_KEY:latest

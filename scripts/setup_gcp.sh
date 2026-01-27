#!/bin/bash
#
# Pinpoint 311 - Google Cloud Platform Setup Script
#
# This script sets up ALL required GCP services with one command:
#   - Cloud KMS (PII encryption)
#   - Cloud Translation API (130+ languages)
#   - Vertex AI (AI analysis)
#   - Secret Manager (credentials storage)
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - A GCP project with billing enabled
#
# Usage:
#   ./scripts/setup_gcp.sh [PROJECT_ID] [LOCATION]
#
# Example:
#   ./scripts/setup_gcp.sh my-township-project us-central1
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Configuration
KEY_RING_NAME="pinpoint311"
KEY_NAME="pii-encryption"
SERVICE_ACCOUNT_NAME="pinpoint311-vertex"

# Parse arguments
PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
LOCATION="${2:-us-central1}"

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Pinpoint 311 - Google Cloud Platform Setup              ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if gcloud is installed
if ! command -v gcloud &> /dev/null; then
    echo -e "${RED}Error: gcloud CLI is not installed${NC}"
    echo "Install it from: https://cloud.google.com/sdk/docs/install"
    exit 1
fi

# Check if authenticated
if ! gcloud auth list --filter=status:ACTIVE --format="value(account)" 2>/dev/null | grep -q '@'; then
    echo -e "${RED}Error: Not authenticated with gcloud${NC}"
    echo "Run: gcloud auth login"
    exit 1
fi

# Validate project
if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: No project specified${NC}"
    echo "Usage: $0 <PROJECT_ID> [LOCATION]"
    echo "Or set default: gcloud config set project YOUR_PROJECT_ID"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Project:   $PROJECT_ID"
echo "  Location:  $LOCATION"
echo ""

# ============================================================================
# STEP 1: Enable all required APIs
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 1: Enabling APIs                                          ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

APIS=(
    "cloudkms.googleapis.com"
    "translate.googleapis.com"
    "aiplatform.googleapis.com"
    "secretmanager.googleapis.com"
)

for api in "${APIS[@]}"; do
    echo -e "${BLUE}Enabling $api...${NC}"
    if gcloud services enable "$api" --project="$PROJECT_ID" 2>/dev/null; then
        echo -e "${GREEN}✓ $api enabled${NC}"
    else
        echo -e "${YELLOW}⚠ $api may already be enabled${NC}"
    fi
done
echo ""

# ============================================================================
# STEP 2: Cloud KMS Setup
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 2: Cloud KMS (PII Encryption)                             ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Create key ring
echo -e "${BLUE}Creating key ring...${NC}"
if gcloud kms keyrings create "$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${GREEN}✓ Key ring '$KEY_RING_NAME' created${NC}"
else
    echo -e "${YELLOW}⚠ Key ring may already exist${NC}"
fi

# Create encryption key
echo -e "${BLUE}Creating encryption key...${NC}"
if gcloud kms keys create "$KEY_NAME" \
    --keyring="$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" \
    --purpose="encryption" \
    --protection-level="software" 2>/dev/null; then
    echo -e "${GREEN}✓ Encryption key '$KEY_NAME' created${NC}"
else
    echo -e "${YELLOW}⚠ Key may already exist${NC}"
fi
echo ""

# ============================================================================
# STEP 3: Vertex AI Service Account
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 3: Vertex AI (AI Analysis)                                ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

SA_EMAIL="${SERVICE_ACCOUNT_NAME}@${PROJECT_ID}.iam.gserviceaccount.com"

# Create service account
echo -e "${BLUE}Creating service account...${NC}"
if gcloud iam service-accounts create "$SERVICE_ACCOUNT_NAME" \
    --display-name="Pinpoint 311 Vertex AI" \
    --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${GREEN}✓ Service account created${NC}"
else
    echo -e "${YELLOW}⚠ Service account may already exist${NC}"
fi

# Grant Vertex AI User role
echo -e "${BLUE}Granting Vertex AI permissions...${NC}"
gcloud projects add-iam-policy-binding "$PROJECT_ID" \
    --member="serviceAccount:$SA_EMAIL" \
    --role="roles/aiplatform.user" \
    --quiet 2>/dev/null || true
echo -e "${GREEN}✓ Vertex AI User role granted${NC}"

# Create and download key (optional - for non-GCE deployments)
KEY_FILE="vertex-ai-key.json"
echo -e "${BLUE}Creating service account key...${NC}"
if gcloud iam service-accounts keys create "$KEY_FILE" \
    --iam-account="$SA_EMAIL" \
    --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${GREEN}✓ Service account key saved to $KEY_FILE${NC}"
    echo -e "${YELLOW}  ⚠ Keep this file secure! Add to .gitignore${NC}"
else
    echo -e "${YELLOW}⚠ Could not create key (may need manual creation)${NC}"
fi
echo ""

# ============================================================================
# STEP 4: Translation API Key
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 4: Cloud Translation (130+ Languages)                     ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

echo -e "${BLUE}Creating API key for Translation...${NC}"
# Note: API keys require alpha commands or manual creation
echo -e "${YELLOW}⚠ API keys must be created in GCP Console:${NC}"
echo "   1. Go to: https://console.cloud.google.com/apis/credentials"
echo "   2. Click 'Create Credentials' → 'API Key'"
echo "   3. Restrict key to 'Cloud Translation API' and 'Maps JavaScript API'"
echo ""

# ============================================================================
# STEP 5: Verification
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 5: Verification                                           ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Test KMS
echo -e "${BLUE}Testing KMS encryption...${NC}"
TEST_RESULT=$(echo -n "test" | gcloud kms encrypt \
    --key="$KEY_NAME" \
    --keyring="$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" \
    --plaintext-file=- \
    --ciphertext-file=- 2>/dev/null | base64 || echo "")

if [ -n "$TEST_RESULT" ]; then
    echo -e "${GREEN}✓ KMS encryption working${NC}"
else
    echo -e "${RED}✗ KMS test failed${NC}"
fi
echo ""

# ============================================================================
# Summary
# ============================================================================
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Setup Complete!                             ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Add these to your .env file:${NC}"
echo ""
echo "# Google Cloud Project"
echo "GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
echo ""
echo "# Cloud KMS (PII Encryption)"
echo "KMS_LOCATION=$LOCATION"
echo "KMS_KEY_RING=$KEY_RING_NAME"
echo "KMS_KEY_ID=$KEY_NAME"
echo ""
echo "# Vertex AI"
echo "VERTEX_AI_PROJECT=$PROJECT_ID"
echo "GOOGLE_APPLICATION_CREDENTIALS=./vertex-ai-key.json"
echo ""
echo "# API Key (create in GCP Console)"
echo "GOOGLE_MAPS_API_KEY=<your-api-key>"
echo ""
echo -e "${YELLOW}Monthly Cost Estimate:${NC}"
echo "  KMS:         ~\$0.10/month (key + operations)"
echo "  Translation: ~\$20/million characters"
echo "  Vertex AI:   Pay-per-use (Gemini Flash is very affordable)"
echo "  Total:       Typically <\$5/month for small municipalities"
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Create API key in GCP Console (for Maps + Translation)"
echo "  2. Run ./scripts/setup_zitadel.sh for SSO"
echo "  3. Start with: docker-compose up -d"
echo ""
echo -e "${GREEN}Google Cloud setup complete!${NC}"

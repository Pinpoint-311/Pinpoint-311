#!/bin/bash
#
# Pinpoint 311 - Google Cloud KMS Setup Script
#
# This script automatically creates the KMS key ring and key
# required for PII encryption. Run this once during initial setup.
#
# Prerequisites:
#   - gcloud CLI installed and authenticated
#   - A GCP project with billing enabled
#
# Usage:
#   ./scripts/setup_kms.sh [PROJECT_ID] [LOCATION]
#
# Example:
#   ./scripts/setup_kms.sh my-township-project us-central1
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Configuration
KEY_RING_NAME="pinpoint311"
KEY_NAME="pii-encryption"
KEY_PURPOSE="encryption"
KEY_PROTECTION="software"  # Use "hsm" for hardware security module (higher cost)

# Parse arguments
PROJECT_ID="${1:-$(gcloud config get-value project 2>/dev/null)}"
LOCATION="${2:-us-central1}"

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║     Pinpoint 311 - Google Cloud KMS Setup                 ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════╝${NC}"
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
echo "  Key Ring:  $KEY_RING_NAME"
echo "  Key Name:  $KEY_NAME"
echo ""

# Enable Cloud KMS API
echo -e "${BLUE}[1/4] Enabling Cloud KMS API...${NC}"
if gcloud services enable cloudkms.googleapis.com --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${GREEN}✓ Cloud KMS API enabled${NC}"
else
    echo -e "${YELLOW}⚠ API may already be enabled${NC}"
fi

# Create key ring (ignore error if exists)
echo -e "${BLUE}[2/4] Creating key ring...${NC}"
if gcloud kms keyrings create "$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" 2>/dev/null; then
    echo -e "${GREEN}✓ Key ring '$KEY_RING_NAME' created${NC}"
else
    echo -e "${YELLOW}⚠ Key ring may already exist (continuing)${NC}"
fi

# Create encryption key (ignore error if exists)
echo -e "${BLUE}[3/4] Creating encryption key...${NC}"
if gcloud kms keys create "$KEY_NAME" \
    --keyring="$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" \
    --purpose="$KEY_PURPOSE" \
    --protection-level="$KEY_PROTECTION" 2>/dev/null; then
    echo -e "${GREEN}✓ Encryption key '$KEY_NAME' created${NC}"
else
    echo -e "${YELLOW}⚠ Key may already exist (continuing)${NC}"
fi

# Get the full key path
KEY_PATH="projects/$PROJECT_ID/locations/$LOCATION/keyRings/$KEY_RING_NAME/cryptoKeys/$KEY_NAME"

# Verify key is working
echo -e "${BLUE}[4/4] Verifying key...${NC}"
TEST_TEXT="PinPoint311-Test"
ENCRYPTED=$(echo -n "$TEST_TEXT" | gcloud kms encrypt \
    --key="$KEY_NAME" \
    --keyring="$KEY_RING_NAME" \
    --location="$LOCATION" \
    --project="$PROJECT_ID" \
    --plaintext-file=- \
    --ciphertext-file=- 2>/dev/null | base64)

if [ -n "$ENCRYPTED" ]; then
    echo -e "${GREEN}✓ Key is working correctly${NC}"
else
    echo -e "${RED}✗ Key verification failed${NC}"
    exit 1
fi

echo ""
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Setup Complete!                         ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Add these to your .env file:${NC}"
echo ""
echo "GOOGLE_CLOUD_PROJECT=$PROJECT_ID"
echo "KMS_LOCATION=$LOCATION"
echo "KMS_KEY_RING=$KEY_RING_NAME"
echo "KMS_KEY_ID=$KEY_NAME"
echo ""
echo -e "${BLUE}Key Resource Name:${NC}"
echo "$KEY_PATH"
echo ""
echo -e "${YELLOW}Monthly Cost Estimate:${NC}"
echo "  - Active key version: \$0.06/month"
echo "  - First 2,000 operations: FREE"
echo "  - Additional operations: \$0.03 per 10,000"
echo ""
echo -e "${GREEN}PII encryption is now ready to use!${NC}"

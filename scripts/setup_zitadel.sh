#!/bin/bash
#
# Pinpoint 311 - Zitadel Cloud Setup Script
#
# This script helps configure Zitadel Cloud for SSO authentication.
# It creates the application and configures redirect URLs automatically.
#
# Prerequisites:
#   1. Create a Zitadel Cloud account at https://zitadel.cloud
#   2. Create a project in Zitadel Console
#   3. Generate a Personal Access Token (PAT) or Service User
#
# Usage:
#   ./scripts/setup_zitadel.sh <ZITADEL_DOMAIN> <ACCESS_TOKEN> <APP_DOMAIN>
#
# Example:
#   ./scripts/setup_zitadel.sh myorg-abc123.zitadel.cloud "pat_xxx" "pinpoint311.example.com"
#

set -e

# Colors for output
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# Parse arguments
ZITADEL_DOMAIN="${1:-}"
ACCESS_TOKEN="${2:-}"
APP_DOMAIN="${3:-localhost}"

echo -e "${BLUE}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${BLUE}║       Pinpoint 311 - Zitadel Cloud SSO Setup                  ║${NC}"
echo -e "${BLUE}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""

# Check if curl is installed
if ! command -v curl &> /dev/null; then
    echo -e "${RED}Error: curl is not installed${NC}"
    exit 1
fi

# Check if jq is installed
if ! command -v jq &> /dev/null; then
    echo -e "${YELLOW}Warning: jq not installed, output will be raw JSON${NC}"
    JQ_AVAILABLE=false
else
    JQ_AVAILABLE=true
fi

# Interactive mode if no arguments
if [ -z "$ZITADEL_DOMAIN" ]; then
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Manual Setup Instructions                                      ${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo -e "${YELLOW}Step 1: Create Zitadel Cloud Account${NC}"
    echo "   1. Go to https://zitadel.cloud"
    echo "   2. Sign up for a free account"
    echo "   3. Note your instance domain (e.g., myorg-abc123.zitadel.cloud)"
    echo ""
    echo -e "${YELLOW}Step 2: Create Project${NC}"
    echo "   1. In Zitadel Console, go to 'Projects'"
    echo "   2. Click 'Create New Project'"
    echo "   3. Name it 'Pinpoint 311'"
    echo ""
    echo -e "${YELLOW}Step 3: Create Web Application${NC}"
    echo "   1. Inside the project, click 'New Application'"
    echo "   2. Choose 'Web' application type"
    echo "   3. Name it 'Pinpoint 311 Staff Portal'"
    echo "   4. Authentication method: 'PKCE' (recommended) or 'Code'"
    echo ""
    echo -e "${YELLOW}Step 4: Configure Redirect URLs${NC}"
    echo "   Add these redirect URIs:"
    echo -e "   ${GREEN}https://YOUR_DOMAIN/login${NC}"
    echo -e "   ${GREEN}https://YOUR_DOMAIN/api/auth/callback${NC}"
    echo -e "   ${GREEN}http://localhost:3000/login${NC} (for development)"
    echo -e "   ${GREEN}http://localhost:3000/api/auth/callback${NC} (for development)"
    echo ""
    echo -e "${YELLOW}Step 5: Copy Credentials${NC}"
    echo "   After creating the app, copy:"
    echo "   - Client ID"
    echo "   - Client Secret (if using Code flow)"
    echo ""
    echo -e "${YELLOW}Step 6: Add to Pinpoint 311${NC}"
    echo "   In Admin Console → Integrations → API Keys:"
    echo "   - ZITADEL_DOMAIN: your-instance.zitadel.cloud"
    echo "   - ZITADEL_CLIENT_ID: (from step 5)"
    echo "   - ZITADEL_CLIENT_SECRET: (from step 5)"
    echo ""
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${CYAN}  Automated Setup (Optional)                                     ${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    echo "To automate application creation, run:"
    echo ""
    echo "  $0 <ZITADEL_DOMAIN> <ACCESS_TOKEN> <APP_DOMAIN>"
    echo ""
    echo "Where ACCESS_TOKEN is a Personal Access Token from:"
    echo "  Zitadel Console → Settings → Personal Access Tokens"
    echo ""
    exit 0
fi

# Validate arguments
if [ -z "$ACCESS_TOKEN" ]; then
    echo -e "${RED}Error: Access token required${NC}"
    echo "Usage: $0 <ZITADEL_DOMAIN> <ACCESS_TOKEN> <APP_DOMAIN>"
    exit 1
fi

echo -e "${YELLOW}Configuration:${NC}"
echo "  Zitadel Domain: $ZITADEL_DOMAIN"
echo "  App Domain:     $APP_DOMAIN"
echo ""

# ============================================================================
# STEP 1: Get Organization ID
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 1: Fetching Organization Info                             ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

ORG_RESPONSE=$(curl -s "https://$ZITADEL_DOMAIN/management/v1/orgs/me" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json")

if [ "$JQ_AVAILABLE" = true ]; then
    ORG_ID=$(echo "$ORG_RESPONSE" | jq -r '.org.id // empty')
    ORG_NAME=$(echo "$ORG_RESPONSE" | jq -r '.org.name // empty')
else
    ORG_ID=$(echo "$ORG_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
fi

if [ -z "$ORG_ID" ]; then
    echo -e "${RED}Error: Could not fetch organization. Check your access token.${NC}"
    echo "Response: $ORG_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Organization: $ORG_NAME ($ORG_ID)${NC}"
echo ""

# ============================================================================
# STEP 2: Create Project
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 2: Creating Project                                       ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

PROJECT_RESPONSE=$(curl -s -X POST "https://$ZITADEL_DOMAIN/management/v1/projects" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Pinpoint 311",
        "projectRoleAssertion": true,
        "projectRoleCheck": true
    }')

if [ "$JQ_AVAILABLE" = true ]; then
    PROJECT_ID=$(echo "$PROJECT_RESPONSE" | jq -r '.id // empty')
else
    PROJECT_ID=$(echo "$PROJECT_RESPONSE" | grep -o '"id":"[^"]*"' | head -1 | cut -d'"' -f4)
fi

if [ -z "$PROJECT_ID" ]; then
    echo -e "${YELLOW}⚠ Project may already exist, searching...${NC}"
    # Try to find existing project
    PROJECTS=$(curl -s -X POST "https://$ZITADEL_DOMAIN/management/v1/projects/_search" \
        -H "Authorization: Bearer $ACCESS_TOKEN" \
        -H "Content-Type: application/json" \
        -d '{"queries":[{"nameQuery":{"name":"Pinpoint 311","method":"TEXT_QUERY_METHOD_CONTAINS"}}]}')
    
    if [ "$JQ_AVAILABLE" = true ]; then
        PROJECT_ID=$(echo "$PROJECTS" | jq -r '.result[0].id // empty')
    fi
fi

if [ -z "$PROJECT_ID" ]; then
    echo -e "${RED}Error: Could not create or find project${NC}"
    exit 1
fi

echo -e "${GREEN}✓ Project ID: $PROJECT_ID${NC}"
echo ""

# ============================================================================
# STEP 3: Create Web Application
# ============================================================================
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}  Step 3: Creating Web Application                               ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"

# Build redirect URIs
if [ "$APP_DOMAIN" = "localhost" ]; then
    REDIRECT_URIS='["http://localhost:3000/login", "http://localhost:3000/api/auth/callback", "http://localhost/login", "http://localhost/api/auth/callback"]'
    POST_LOGOUT_URIS='["http://localhost:3000", "http://localhost"]'
else
    REDIRECT_URIS='["https://'"$APP_DOMAIN"'/login", "https://'"$APP_DOMAIN"'/api/auth/callback", "http://localhost:3000/login", "http://localhost:3000/api/auth/callback"]'
    POST_LOGOUT_URIS='["https://'"$APP_DOMAIN"'", "http://localhost:3000"]'
fi

APP_RESPONSE=$(curl -s -X POST "https://$ZITADEL_DOMAIN/management/v1/projects/$PROJECT_ID/apps/oidc" \
    -H "Authorization: Bearer $ACCESS_TOKEN" \
    -H "Content-Type: application/json" \
    -d '{
        "name": "Pinpoint 311 Staff Portal",
        "redirectUris": '"$REDIRECT_URIS"',
        "responseTypes": ["OIDC_RESPONSE_TYPE_CODE"],
        "grantTypes": ["OIDC_GRANT_TYPE_AUTHORIZATION_CODE", "OIDC_GRANT_TYPE_REFRESH_TOKEN"],
        "appType": "OIDC_APP_TYPE_WEB",
        "authMethodType": "OIDC_AUTH_METHOD_TYPE_POST",
        "postLogoutRedirectUris": '"$POST_LOGOUT_URIS"',
        "accessTokenType": "OIDC_TOKEN_TYPE_JWT",
        "accessTokenRoleAssertion": true,
        "idTokenRoleAssertion": true,
        "idTokenUserinfoAssertion": true
    }')

if [ "$JQ_AVAILABLE" = true ]; then
    CLIENT_ID=$(echo "$APP_RESPONSE" | jq -r '.clientId // empty')
    CLIENT_SECRET=$(echo "$APP_RESPONSE" | jq -r '.clientSecret // empty')
    APP_ID=$(echo "$APP_RESPONSE" | jq -r '.appId // empty')
else
    CLIENT_ID=$(echo "$APP_RESPONSE" | grep -o '"clientId":"[^"]*"' | cut -d'"' -f4)
    CLIENT_SECRET=$(echo "$APP_RESPONSE" | grep -o '"clientSecret":"[^"]*"' | cut -d'"' -f4)
fi

if [ -z "$CLIENT_ID" ]; then
    echo -e "${RED}Error: Could not create application${NC}"
    echo "Response: $APP_RESPONSE"
    exit 1
fi

echo -e "${GREEN}✓ Application created successfully${NC}"
echo ""

# ============================================================================
# Summary
# ============================================================================
echo -e "${GREEN}╔═══════════════════════════════════════════════════════════════╗${NC}"
echo -e "${GREEN}║                    Zitadel Setup Complete!                    ║${NC}"
echo -e "${GREEN}╚═══════════════════════════════════════════════════════════════╝${NC}"
echo ""
echo -e "${YELLOW}Add these to Pinpoint 311 Admin Console → Integrations:${NC}"
echo ""
echo "ZITADEL_DOMAIN=$ZITADEL_DOMAIN"
echo "ZITADEL_CLIENT_ID=$CLIENT_ID"
if [ -n "$CLIENT_SECRET" ]; then
    echo "ZITADEL_CLIENT_SECRET=$CLIENT_SECRET"
fi
echo ""
echo -e "${YELLOW}Configured Redirect URLs:${NC}"
if [ "$APP_DOMAIN" = "localhost" ]; then
    echo "  - http://localhost:3000/login"
    echo "  - http://localhost:3000/api/auth/callback"
else
    echo "  - https://$APP_DOMAIN/login"
    echo "  - https://$APP_DOMAIN/api/auth/callback"
    echo "  - http://localhost:3000/login (dev)"
    echo "  - http://localhost:3000/api/auth/callback (dev)"
fi
echo ""
echo -e "${BLUE}Next Steps:${NC}"
echo "  1. Add credentials to Pinpoint 311 Admin Console"
echo "  2. Enable MFA in Zitadel Console → Settings → Login Policy"
echo "  3. Test login at https://$APP_DOMAIN/staff"
echo ""
echo -e "${GREEN}Zitadel SSO setup complete!${NC}"

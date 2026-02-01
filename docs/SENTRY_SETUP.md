# Sentry Error Tracking Setup

Pinpoint 311 includes Sentry SDK integration for real-time error tracking and performance monitoring.

## Quick Setup (5 minutes)

### 1. Create Sentry Account
1. Go to [sentry.io](https://sentry.io)
2. Create a free account (90-day trial, then free tier available)
3. Create a new project → Select **Python** → **FastAPI**

### 2. Get Your DSN
After creating the project, Sentry will show you a DSN like:
```
https://abc123@o123456.ingest.sentry.io/1234567
```

### 3. Add to Production Environment
SSH to your production server and add the DSN to your environment:

```bash
# SSH to production
ssh ubuntu@132.226.32.116
cd /path/to/app

# Edit .env file
echo "SENTRY_DSN=https://your-dsn-here@sentry.io/project" >> .env
echo "ENVIRONMENT=production" >> .env

# Restart backend
docker compose restart backend celery_worker
```

### 4. Verify Integration
1. Trigger a test error:
```bash
curl https://311.westwindsorforward.org/api/sentry-debug
```
2. Check Sentry dashboard - you should see the test error within 30 seconds

---

## What Gets Tracked

### Errors
- Unhandled Python exceptions
- API 500 errors
- Database connection failures
- External service failures (Auth0, Maps API)

### Performance (10% sampling)
- API response times
- Database query durations
- External HTTP request latency

### Context Included
- Request URL and method
- User role (not PII)
- Request ID for correlation
- Environment (production/staging)

---

## Privacy Configuration

**PII is NOT sent to Sentry by default.** The integration is configured with:

```python
sentry_sdk.init(
    dsn=SENTRY_DSN,
    send_default_pii=False,  # No emails, IPs, usernames
    traces_sample_rate=0.1,  # 10% of requests
)
```

This means:
- ❌ No user emails
- ❌ No IP addresses  
- ❌ No resident names
- ✅ Request IDs (for debugging)
- ✅ Error stack traces
- ✅ Request paths (without query params)

---

## Alert Configuration

### Recommended Alerts in Sentry Dashboard

1. **High Error Rate**
   - Trigger: >10 errors in 5 minutes
   - Action: Email + Slack

2. **New Issue Type**
   - Trigger: First occurrence of new error
   - Action: Email

3. **Performance Degradation**
   - Trigger: P95 latency > 3 seconds
   - Action: Slack

---

## Troubleshooting

### Not seeing errors?
1. Verify `SENTRY_DSN` is set: `docker exec backend env | grep SENTRY`
2. Check backend logs: `docker logs wwf-311-fix-backend-1 | grep -i sentry`
3. Test endpoint: `curl https://your-domain/api/sentry-debug`

### High volume of errors?
1. Check for infinite loops or retry storms
2. Add rate limiting in Sentry project settings
3. Use Sentry's ignore rules for noisy but harmless errors

---

*Last Updated: February 2026*

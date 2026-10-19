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

### 3. Save the DSN
In the Admin Console, open **Setup & Integration**, find the **Crash reporting**
card, paste the DSN, and save. The DSN is stored in the town's chosen secret
store. The API reads it at startup and the worker reads it when each worker
process starts, so restart both:

```bash
docker compose restart backend worker
```

A `SENTRY_DSN` environment variable takes precedence over the saved DSN. The
default `docker-compose.yml` does not pass `SENTRY_DSN` (or `ENVIRONMENT`)
through to the containers; to use them, add them to the `environment:` of the
`backend` and `worker` services in a `docker-compose.override.yml`.

Switching crash reporting off on the setup page drops events without removing
the DSN.

### 4. Verify Integration
`GET /api/sentry-debug` raises a deliberate error, but only when the backend
runs with `DEBUG=true`; otherwise it returns 404. On a production instance,
check the backend log for `[Sentry]` lines instead (startup reports where the DSN came from, or why it could not be read):

```bash
docker compose logs backend | grep -i sentry
```

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
1. Check that a DSN is saved on the **Crash reporting** card, or that `SENTRY_DSN` reaches the container: `docker compose exec backend env | grep SENTRY`
2. Check the logs: `docker compose logs backend worker | grep -i sentry`
3. Restart after saving a DSN: `docker compose restart backend worker`
4. With `DEBUG=true` only: `curl https://your-domain/api/sentry-debug`

### High volume of errors?
1. Check for infinite loops or retry storms
2. Add rate limiting in Sentry project settings
3. Use Sentry's ignore rules for noisy but harmless errors

---

*Last Updated: February 2026*

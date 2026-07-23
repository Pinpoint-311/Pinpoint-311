# Pinpoint 311 Cost Guide

Pinpoint 311 is free and open-source (MIT). You pay only for the cloud services you choose to enable — and most of those have free tiers that cover a typical town. All figures below are **2026 estimates**; provider pricing changes, so treat them as planning numbers, not quotes, and confirm current rates with your provider.

## Cost at a Glance

| Approach | Typical annual cost (town of ~10K) | Data ownership |
|----------|-----------------------------------|----------------|
| Commercial hosted 311 platform | roughly $8,000–$25,000 | Vendor-hosted |
| **Pinpoint 311** | **roughly $25–$1,200** | You own it |

The range for Pinpoint depends almost entirely on whether you use an existing server (infrastructure is then $0) and how many optional cloud features you turn on.

---

## Infrastructure

### Use an existing server (most common)
If the town already runs a Linux server or cloud account, Pinpoint runs there as a set of Docker containers at no additional infrastructure cost. Idle footprint is roughly ~185 MB of RAM (see the README's Resource Footprint), so it fits alongside other workloads.

| Approach | Monthly |
|----------|---------|
| Existing municipal server | $0 |
| Existing VM / cloud account | $0 |

### Need a new server?
A small VM is plenty for a typical town. Give it more headroom for higher volume.

| Option | Specs | Approx. monthly |
|--------|-------|-----------------|
| Free-tier cloud VM (e.g. an always-free ARM instance) | ~4 vCPU / large RAM | $0 |
| Budget VPS | ~2–4 vCPU / 4–8 GB | ~$10–20 |
| Mainstream cloud VM | ~2–4 vCPU / 8 GB | ~$40–80 |

---

## Optional Cloud Services (pay-as-you-go)

Every item below is optional. If you don't enable it, it costs nothing. AI, translation, secret storage, encryption, and moderation are provider-pluggable (Google, Azure, or AWS). Translation, secret storage, KMS, email, and SMS cost about the same across the three clouds, so those are shown as shared ranges. **AI is the exception** — its cost depends mostly on which *model* you pick (each cloud offers both cheap and expensive ones), so it gets its own breakdown below. Maps is the one fixed dependency (Google Maps).

### Maps (required)
Modern Google Maps pricing uses per-API monthly free quotas.

| API | Free monthly | After free (approx.) |
|-----|--------------|----------------------|
| Maps JavaScript loads | ~10,000 | ~$7 / 1,000 |
| Geocoding | ~10,000 | ~$5 / 1,000 |
| Places Autocomplete | ~5,000 sessions | ~$3 / 1,000 |

Most towns stay within the free quotas. A town with a few hundred requests a month typically pays **$0**.

### AI triage & photo analysis (optional)
Cost is driven by the **model tier**, not the cloud — all three clouds offer both a cheap, fast model and a larger, pricier one. For 311 triage the light tier is plenty.

| Model tier | Approx. input / output per 1M tokens | Typical monthly (a few hundred requests) |
|------------|--------------------------------------|------------------------------------------|
| **Light / fast** (recommended for triage) | ~$0.15–0.25 / ~$0.60–1.50 | **~$1–5** |
| **Larger / higher quality** | ~$2.50–3 / ~$10–15 | ~$10–40 |

Picking a light model keeps AI at the low end. The model picker refreshes live from your provider, so you can switch to a cheaper or newer model at any time — and if none is configured, AI is simply skipped at no cost.

### Translation (optional)
| Tier | Cost |
|------|------|
| First ~500K characters/month | Free (covers most towns) |
| Above that | ~$20 / 1M characters |

Typical monthly: **$0–5**.

### Content moderation (optional cloud layer)
Text is always screened for free by the built-in scanner. A cloud moderation service adds contextual text and image screening.

| Item | Approx. rate | Typical monthly |
|------|--------------|-----------------|
| Image moderation | ~$1–1.50 / 1,000 images | ~$0–2 |
| Text moderation | fractions of a cent per record | ~$0–1 |

For 311 photo volumes this is typically **$0–2**.

### Secret storage & PII encryption (optional)
| Service | Free tier | After free |
|---------|-----------|------------|
| Secret store | Several active secrets | cents per secret |
| Key service (KMS) | Thousands of operations | cents per 10K operations |

Typically **$0–1/month**.

### Notifications (optional)

Email:
| Service | Free tier |
|---------|-----------|
| Common transactional email providers | ~3,000–5,000 emails/month free |
| Native cloud email | ~$0.10 / 1,000 after free |

SMS (only if you enable it):
| Service | Approx. per message | 500 messages |
|---------|---------------------|--------------|
| Common SMS providers | ~$0.008 | ~$4 |

Tip: magic-link tracking by email is free, so many towns lean on email over SMS.

---

## Example Scenarios (2026 estimates)

### Small town (~5,000 residents, ~100 requests/month)
| Component | Monthly |
|-----------|---------|
| Server (existing) | $0 |
| Maps | $0 (within free quota) |
| AI | ~$1 |
| Translation | $0 |
| Moderation | $0 |
| SMS (100) | ~$1 |
| Email | $0 |
| **Total** | **~$2** |

### Medium town (~25,000 residents, ~500 requests/month)
| Component | Monthly |
|-----------|---------|
| Server (existing) | $0 |
| Maps | $0 (within free quota) |
| AI | ~$5 |
| Translation | ~$2 |
| Moderation | ~$1 |
| SMS (500) | ~$4 |
| Email | $0 |
| **Total** | **~$12** |

### Large municipality (~100,000+ residents, ~2,000 requests/month)
| Component | Monthly |
|-----------|---------|
| Server (small VPS) | ~$15 |
| Maps | ~$20 |
| AI | ~$15 |
| Translation | ~$10 |
| Moderation | ~$3 |
| SMS (2,000) | ~$16 |
| Email | ~$2 |
| **Total** | **~$80** |

---

## Keeping Costs Down
- Use an existing server or a free-tier VM — infrastructure is the biggest variable.
- Enable only the providers you need; everything is optional and skipped when off.
- Prefer email/magic-link over SMS where you can — email tiers are generous.
- The built-in text moderation is free; add the paid cloud layer only if you want contextual/image screening.
- Set budget alerts in your cloud console.

---

## What's Free
- The Pinpoint 311 software (MIT license), all features, unlimited users and staff.
- Updates, and the built-in text moderation scanner.
- No per-seat or per-request licensing.

---

## Help
- **Issues**: <https://github.com/Pinpoint-311/Pinpoint-311/issues>
- **Discussions**: <https://github.com/Pinpoint-311/Pinpoint-311/discussions>

*Figures are 2026 planning estimates and assume existing municipal servers where noted. Confirm current rates with your providers.*

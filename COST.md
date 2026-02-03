# 💰 Pinpoint 311 Cost Guide

Pinpoint 311 is **100% free and open-source**. You only pay for the cloud services you use.

## 📊 Quick Cost Comparison

| Solution | Annual Cost (10K population) | Data Ownership |
|----------|------------------------------|----------------|
| **SeeClickFix** | $8,000 - $15,000 | ❌ Vendor-hosted |
| **PublicStuff/Accela** | $12,000 - $25,000 | ❌ Vendor-hosted |
| **311 GovPilot** | $10,000 - $20,000 | ❌ Vendor-hosted |
| **Pinpoint 311** | **$50 - $200/month** | ✅ You own it |

---

## 🖥️ Infrastructure Costs

### Self-Hosted VPS (Recommended)

| Provider | Specs | Monthly | Notes |
|----------|-------|---------|-------|
| **Oracle Cloud** | 4 vCPU, 24GB RAM | **$0** | Always Free Tier (ARM) |
| **Hetzner** | 4 vCPU, 8GB RAM | **$15** | Best value in EU/US |
| **DigitalOcean** | 4 vCPU, 8GB RAM | $48 | Simple setup |
| **AWS Lightsail** | 4 vCPU, 8GB RAM | $80 | AWS ecosystem |

> 💡 **Recommendation**: Start with Oracle Cloud's free tier or Hetzner for the best value.

---

## ☁️ Google Cloud Costs (Pay-as-you-go)

All variable costs are based on actual usage. Here's what a typical municipality pays:

### Google Maps Platform

| API | Free Tier | Cost After Free | Typical Monthly Usage |
|-----|-----------|-----------------|----------------------|
| **Maps JavaScript** | $200/mo credit | $7/1K loads | 500 loads = **$0** |
| **Geocoding** | $200/mo credit | $5/1K requests | 200 = **$0** |
| **Places Autocomplete** | $200/mo credit | $2.83/1K | 300 = **$0** |

> 📍 **Most municipalities stay within the $200/month free credit.**

### Vertex AI (Gemini 3.0 Flash)

| Model | Input | Output | Typical Monthly |
|-------|-------|--------|-----------------|
| **Gemini 3.0 Flash** | $0.00001/1K chars | $0.00004/1K chars | ~$2-5 |

> 🤖 AI analysis of 500 requests/month costs approximately **$2-5**.

### Google Translate API

| Tier | Cost | Notes |
|------|------|-------|
| **First 500K chars** | Free | Covers most municipalities |
| **After 500K** | $20/1M chars | Only for high-volume |

> 🌍 Translation for 500 requests/month = **$0-2**

### Google Secret Manager & KMS

| Service | Free Tier | Cost |
|---------|-----------|------|
| **Secret Manager** | 6 active secrets | $0.03/secret after |
| **Cloud KMS** | 2,500 operations | $0.03/10K ops after |

> 🔐 Security services typically cost **$0-1/month**

---

## 📱 Communication Costs

### SMS Notifications

| Provider | Cost per SMS | 500 msgs/month |
|----------|--------------|----------------|
| **Twilio** | $0.0079 | $3.95 |
| **Generic HTTP API** | Varies | $2-5 |

### Email (SMTP)

| Provider | Free Tier | Cost |
|----------|-----------|------|
| **Resend** | 3,000/month | Free |
| **Mailgun** | 5,000/month | Free |
| **SendGrid** | 100/day | Free |
| **AWS SES** | - | $0.10/1K |

---

## 📈 Cost Scenarios

### Small Town (5,000 population)
*~100 requests/month*

| Component | Monthly Cost |
|-----------|--------------|
| VPS (Oracle Free) | $0 |
| Google Maps | $0 (within credit) |
| Vertex AI | $1 |
| Translate | $0 |
| SMS (100 msgs) | $1 |
| Email | $0 |
| **TOTAL** | **~$2/month** |

---

### Medium Town (25,000 population)
*~500 requests/month*

| Component | Monthly Cost |
|-----------|--------------|
| VPS (Hetzner) | $15 |
| Google Maps | $0 (within credit) |
| Vertex AI | $5 |
| Translate | $2 |
| SMS (500 msgs) | $4 |
| Email | $0 |
| **TOTAL** | **~$26/month** |

---

### Large Municipality (100,000+ population)
*~2,000 requests/month*

| Component | Monthly Cost |
|-----------|--------------|
| VPS (DigitalOcean 8GB) | $48 |
| Google Maps | $20 |
| Vertex AI | $15 |
| Translate | $10 |
| SMS (2K msgs) | $16 |
| Email (AWS SES) | $2 |
| **TOTAL** | **~$111/month** |

---

## 🎯 Cost Optimization Tips

1. **Use Oracle Cloud Free Tier** - 4 ARM vCPUs + 24GB RAM forever free
2. **Enable Redis caching** - Reduces API calls by 80%
3. **Batch AI requests** - Process similar requests together
4. **Use magic links over SMS** - Email is free, SMS isn't
5. **Set up budget alerts** in Google Cloud Console

---

## 💵 Annual Cost Summary

| Population | Monthly | Annual | vs. SeeClickFix |
|------------|---------|--------|-----------------|
| 5,000 | $2 | **$24** | Save $8,000+ |
| 25,000 | $26 | **$312** | Save $10,000+ |
| 100,000 | $111 | **$1,332** | Save $15,000+ |

---

## 🆓 What's Actually Free

- ✅ Pinpoint 311 software (MIT License)
- ✅ All features (no premium tier)
- ✅ Unlimited users & staff
- ✅ All integrations included
- ✅ Updates forever
- ✅ Community support

---

## 📞 Need Help?

- **GitHub Issues**: [Report bugs or request features](https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/issues)
- **Discussions**: [Ask questions](https://github.com/WestWindsorForward/WWF-Open-Source-311-Template/discussions)

<p align="center">
  <i>Built for municipalities, by municipalities. No vendor lock-in.</i>
</p>

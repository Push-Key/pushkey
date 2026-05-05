"""
Pushkey — provider database, detection, and key health utilities.
No tkinter dependency — safe to import from CLI and tests.
"""
import json
import os
from datetime import datetime

import pushkey_shared as _s
from pushkey_crypto import log_event


_BUNDLED_PROVIDERS = {
    "OpenAI":          {"url": "https://platform.openai.com/api-keys",                                    "prefix": "sk-",           "category": "AI",                 "patterns": ["openai", "gpt"],             "rotation_days": 90,  "multi_key": True},
    "Anthropic":       {"url": "https://console.anthropic.com/settings/keys",                             "prefix": "sk-ant-",       "category": "AI",                 "patterns": ["anthropic", "claude"],       "rotation_days": 90,  "multi_key": True},
    "Alpaca":          {"url": "https://app.alpaca.markets/paper/dashboard/overview",                     "prefix": "",              "category": "Trading",            "patterns": ["alpaca"],                    "rotation_days": 90,  "multi_key": True},
    "OANDA":           {"url": "https://www.oanda.com/account/tpa/personal_token",                        "prefix": "",              "category": "Trading",            "patterns": ["oanda"],                     "rotation_days": 90,  "multi_key": False},
    "Coinbase":        {"url": "https://www.coinbase.com/settings/api",                                   "prefix": "",              "category": "Trading",            "patterns": ["coinbase"],                  "rotation_days": 90,  "multi_key": True},
    "Supabase":        {"url": "https://supabase.com/dashboard",                                          "prefix": "eyJ",           "category": "Database",           "patterns": ["supabase"],                  "rotation_days": 180, "multi_key": False},
    "Stripe":          {"url": "https://dashboard.stripe.com/apikeys",                                    "prefix": "sk_",           "category": "Payment",            "patterns": ["stripe"],                    "rotation_days": 90,  "multi_key": True},
    "AWS":             {"url": "https://console.aws.amazon.com/iam/home#/security_credentials",          "prefix": "AKIA",          "category": "Cloud",              "patterns": ["aws", "amazon"],             "rotation_days": 90,  "multi_key": True},
    "Vercel":          {"url": "https://vercel.com/account/tokens",                                       "prefix": "",              "category": "Cloud",              "patterns": ["vercel"],                    "rotation_days": 90,  "multi_key": True},
    "GitHub":          {"url": "https://github.com/settings/tokens",                                     "prefix": "ghp_",          "category": "VCS",                "patterns": ["github", "gh_", "ghp_"],    "rotation_days": 90,  "multi_key": True},
    "GitLab":          {"url": "https://gitlab.com/-/profile/personal_access_tokens",                    "prefix": "glpat-",        "category": "VCS",                "patterns": ["gitlab", "glpat"],           "rotation_days": 90,  "multi_key": True},
    "Twilio":          {"url": "https://console.twilio.com/?frameUrl=/console/account/keys",             "prefix": "",              "category": "Communication",      "patterns": ["twilio"],                    "rotation_days": 90,  "multi_key": True},
    "SendGrid":        {"url": "https://app.sendgrid.com/settings/api_keys",                             "prefix": "SG.",           "category": "Communication",      "patterns": ["sendgrid"],                  "rotation_days": 90,  "multi_key": True},
    "Slack":           {"url": "https://api.slack.com/apps",                                             "prefix": "xoxb-",         "category": "Communication",      "patterns": ["slack", "xoxb", "xoxp"],    "rotation_days": 180, "multi_key": False},
    "Discord":         {"url": "https://discord.com/developers/applications",                            "prefix": "",              "category": "Communication",      "patterns": ["discord"],                   "rotation_days": 90,  "multi_key": False},
    "Google Cloud":    {"url": "https://console.cloud.google.com/apis/credentials",                      "prefix": "",              "category": "Cloud",              "patterns": ["google", "gcp"],             "rotation_days": 90,  "multi_key": True},
    "Azure":           {"url": "https://portal.azure.com/#view/Microsoft_AAD_IAM/AppIntegrationsMenuBlade", "prefix": "",            "category": "Cloud",              "patterns": ["azure"],                     "rotation_days": 90,  "multi_key": True},
    "DigitalOcean":    {"url": "https://cloud.digitalocean.com/account/api/tokens",                      "prefix": "dop_v1_",       "category": "Cloud",              "patterns": ["digitalocean", "dop_"],      "rotation_days": 90,  "multi_key": True},
    "Heroku":          {"url": "https://dashboard.heroku.com/account",                                   "prefix": "",              "category": "Cloud",              "patterns": ["heroku"],                    "rotation_days": 90,  "multi_key": False},
    "MongoDB Atlas":   {"url": "https://cloud.mongodb.com/v2",                                           "prefix": "mongodb+srv://","category": "Database",           "patterns": ["mongodb", "mongo"],          "rotation_days": 180, "multi_key": True},
    "PostgreSQL":      {"url": "https://console.cloud.google.com/sql",                                   "prefix": "postgresql://", "category": "Database",           "patterns": ["postgres", "psql"],          "rotation_days": 180, "multi_key": False},
    "Elastic":         {"url": "https://www.elastic.co/cloud/console/",                                  "prefix": "",              "category": "Database",           "patterns": ["elastic"],                   "rotation_days": 90,  "multi_key": True},
    "HashiCorp Vault": {"url": "https://www.vaultproject.io/",                                           "prefix": "s.",            "category": "Security",           "patterns": ["hashicorp"],                 "rotation_days": 30,  "multi_key": True},
    "PagerDuty":       {"url": "https://subdomain.pagerduty.com/api_keys",                               "prefix": "",              "category": "Incident",           "patterns": ["pagerduty"],                 "rotation_days": 90,  "multi_key": True},
    "Datadog":         {"url": "https://app.datadoghq.com/organization-settings/api-keys",               "prefix": "",              "category": "Monitoring",         "patterns": ["datadog"],                   "rotation_days": 90,  "multi_key": True},
    "New Relic":       {"url": "https://one.newrelic.com/launcher/api-keys-ui.launcher",                 "prefix": "",              "category": "Monitoring",         "patterns": ["newrelic"],                  "rotation_days": 90,  "multi_key": True},
    "HubSpot":         {"url": "https://app.hubspot.com/login",                                          "prefix": "pat-",          "category": "CRM",                "patterns": ["hubspot"],                   "rotation_days": 90,  "multi_key": True},
    "Jira":            {"url": "https://id.atlassian.com/manage/api-tokens",                             "prefix": "",              "category": "Project Management", "patterns": ["jira", "atlassian"],         "rotation_days": 90,  "multi_key": True},
}


def _load_providers():
    merged = dict(_BUNDLED_PROVIDERS)
    if _s.PROVIDERS_CACHE.exists():
        try:
            cached = json.loads(_s.PROVIDERS_CACHE.read_text(encoding="utf-8"))
            merged.update(cached.get("providers", {}))
        except Exception:
            pass
    return merged


def update_providers_from_web():
    """Fetch latest providers.json from GitHub. Returns (new_count, updated_count, error_str)."""
    import urllib.request, urllib.error
    try:
        with urllib.request.urlopen(_s.PROVIDERS_REGISTRY_URL, timeout=10) as r:
            raw = r.read().decode("utf-8")
        data = json.loads(raw)
        remote = data.get("providers", {})
        if not remote:
            return 0, 0, "Registry returned empty providers list"
        existing = _load_providers()
        new_count     = sum(1 for k in remote if k not in existing)
        updated_count = sum(1 for k in remote if k in existing and remote[k] != existing.get(k))
        tmp = _s.PROVIDERS_CACHE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(str(tmp), str(_s.PROVIDERS_CACHE))
        global PROVIDERS
        PROVIDERS = _load_providers()
        log_event(f"providers updated: {new_count} new, {updated_count} changed")
        return new_count, updated_count, None
    except urllib.error.URLError as e:
        return 0, 0, f"Network error: {e.reason}"
    except Exception as e:
        return 0, 0, str(e)


def detect_provider(key_name, key_value=""):
    name_lower = key_name.lower()
    for prov_name, prov in PROVIDERS.items():
        for pattern in prov["patterns"]:
            if pattern in name_lower:
                return prov_name
    prefixed = [(prov["prefix"], name) for name, prov in PROVIDERS.items() if prov["prefix"]]
    for prefix, prov_name in sorted(prefixed, key=lambda x: len(x[0]), reverse=True):
        if key_value.startswith(prefix):
            return prov_name
    return None


def provider_supports_multi_key(provider_name: str) -> bool:
    """Return True if the provider supports multiple simultaneous active keys."""
    prov = PROVIDERS.get(provider_name, {})
    return bool(prov.get("multi_key", True))  # default True — optimistic for unknown providers


def days_since(date_str):
    if not date_str:
        return float("inf")
    try:
        dt = datetime.fromisoformat(date_str)
        return (datetime.now() - dt).days
    except Exception:
        return float("inf")


def health_status(key_info):
    age = days_since(key_info.get("rotated") or key_info.get("created"))
    provider = key_info.get("provider")
    threshold = 90
    if provider and provider in PROVIDERS:
        threshold = PROVIDERS[provider].get("rotation_days", 90)
    use_age = days_since(key_info.get("first_used"))
    effective_age = min(age, use_age) if use_age != float("inf") else age
    if effective_age > threshold:
        return "critical"
    if effective_age > threshold * 0.67:
        return "warning"
    return "healthy"


PROVIDERS = _load_providers()

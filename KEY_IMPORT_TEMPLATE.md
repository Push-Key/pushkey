# Pushkey Key Import Template

Reference format for bulk upload (.txt / .env files).
Bulk upload: All Keys tab → "Bulk Upload" button.

───────────────────────────────────────────────────────
## Supported Line Formats
───────────────────────────────────────────────────────

### Standard .env  (recommended)
KEY_NAME=value
KEY_NAME="value with spaces"
KEY_NAME='another value'

### With export prefix
export AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
export AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI...

### Label: value  (copied from provider dashboards)
API Key: sk-proj-abc123
Secret: my_secret_value
Access Token: eyJhbGciOiJIUzI1Ni...

### Inline comments are stripped
STRIPE_SECRET_KEY=sk_live_... # production key

───────────────────────────────────────────────────────
## Key Naming Conventions
───────────────────────────────────────────────────────

| Type              | Pattern                        | Example                    |
|-------------------|--------------------------------|----------------------------|
| API key           | SERVICE_API_KEY                | OPENAI_API_KEY             |
| Secret key        | SERVICE_SECRET_KEY             | STRIPE_SECRET_KEY          |
| Access token      | SERVICE_ACCESS_TOKEN           | GITHUB_ACCESS_TOKEN        |
| Database URL      | SERVICE_DATABASE_URL           | POSTGRES_DATABASE_URL      |
| Wallet private key| CHAIN_WALLET_PRIVATE_KEY       | ETH_WALLET_PRIVATE_KEY     |
| Seed phrase       | CHAIN_SEED_PHRASE              | SOL_SEED_PHRASE            |
| Certificate       | SERVICE_CERT / SERVICE_KEY     | TLS_CERT, TLS_KEY          |
| Webhook secret    | SERVICE_WEBHOOK_SECRET         | STRIPE_WEBHOOK_SECRET      |
| OAuth client ID   | SERVICE_CLIENT_ID              | GOOGLE_CLIENT_ID           |
| OAuth secret      | SERVICE_CLIENT_SECRET          | GOOGLE_CLIENT_SECRET       |

───────────────────────────────────────────────────────
## Categories
───────────────────────────────────────────────────────

AI          OpenAI, Anthropic, Cohere, HuggingFace, Replicate
Trading     Alpaca, OANDA, Coinbase, Binance, Kraken, Interactive Brokers
Database    Supabase, PostgreSQL, MongoDB, Redis, PlanetScale, Turso
Cloud       AWS, GCP, Azure, Vercel, DigitalOcean, Heroku, Fly.io
Payment     Stripe, PayPal, Square, Braintree, Adyen
Comms       Twilio, SendGrid, Resend, Mailgun, Slack, Discord, Telegram
Security    HashiCorp Vault, certificates, JWT secrets, signing keys
Crypto      Wallet keys, seed phrases, RPC URLs, contract addresses
General     Everything else

───────────────────────────────────────────────────────
## Full Example — Mixed Provider File
───────────────────────────────────────────────────────

# === AI Services ===
OPENAI_API_KEY=sk-proj-...
ANTHROPIC_API_KEY=sk-ant-api03-...
COHERE_API_KEY=...

# === Database ===
SUPABASE_URL=https://xxx.supabase.co
SUPABASE_ANON_KEY=eyJhbGciOiJIUzI1NiIs...
SUPABASE_SERVICE_ROLE_KEY=eyJhbGciOiJIUzI1NiIs...
DATABASE_URL=postgresql://postgres:pass@db.xxx.supabase.co:5432/postgres

# === Cloud ===
AWS_ACCESS_KEY_ID=AKIAIOSFODNN7EXAMPLE
AWS_SECRET_ACCESS_KEY=wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY
AWS_DEFAULT_REGION=us-east-1

# === Payment ===
STRIPE_SECRET_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...
STRIPE_PUBLISHABLE_KEY=pk_live_...

# === Trading ===
ALPACA_API_KEY=PKXXXXXXXXXXXXXXXX
ALPACA_SECRET_KEY=XXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXXX
OANDA_API_TOKEN=...
OANDA_ACCOUNT_ID=...

# === Crypto / Web3 ===
ETH_WALLET_PRIVATE_KEY=0x...
ETH_RPC_URL=https://mainnet.infura.io/v3/...
SOL_WALLET_PRIVATE_KEY=...
ALCHEMY_API_KEY=...

# === Comms ===
SENDGRID_API_KEY=SG....
TWILIO_ACCOUNT_SID=ACxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
TWILIO_AUTH_TOKEN=...
SLACK_BOT_TOKEN=xoxb-...
DISCORD_BOT_TOKEN=...
TELEGRAM_BOT_TOKEN=...

# === Auth / Security ===
JWT_SECRET=a-long-random-string-at-least-32-chars
NEXTAUTH_SECRET=...
SESSION_SECRET=...
ENCRYPTION_KEY=...

# === Version Control ===
GITHUB_TOKEN=ghp_...
GITHUB_WEBHOOK_SECRET=...

───────────────────────────────────────────────────────
## Notes
───────────────────────────────────────────────────────

- Blank lines and # comments are ignored during parse
- Key names are uppercased automatically (my_key → MY_KEY)
- Existing keys get rotated: old value saved to history (up to 10)
- Values encrypted at rest with AES-256 (your master password)
- .env is auto-added to .gitignore when written to a project folder
- Never commit this template with actual values filled in

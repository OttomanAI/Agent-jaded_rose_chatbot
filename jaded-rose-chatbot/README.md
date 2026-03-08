# Jaded Rose Chatbot

Multi-channel AI customer service chatbot for **Jaded Rose**, a UK online clothing store. Handles customer queries autonomously across Telegram, WhatsApp, Gmail and a web chat widget — escalating to a human only when necessary.

## System Architecture

```
┌─────────────────────────────────────────────────────────────────────────────────┐
│                              JADED ROSE CHATBOT                                 │
│                        Multi-Channel AI Customer Service                        │
└─────────────────────────────────────────────────────────────────────────────────┘

    ┌──────────┐  ┌──────────┐  ┌──────────┐  ┌──────────┐
    │ Telegram │  │ WhatsApp │  │  Gmail   │  │   Web    │
    │   Bot    │  │ (Twilio) │  │   API    │  │  Widget  │
    └────┬─────┘  └────┬─────┘  └────┬─────┘  └────┬─────┘
         │             │             │              │
         │   /webhook  │   /webhook  │   /webhook   │  /ws/chat
         │  /telegram  │  /whatsapp  │   /gmail     │  WebSocket
         └──────┬──────┴──────┬──────┴──────┬───────┘
                │             │             │
                ▼             ▼             ▼
┌─────────────────────────────────────────────────────────────┐
│                     FastAPI (main.py)                        │
│                     Port 8080 · uvicorn                      │
└──────────────────────────┬──────────────────────────────────┘
                           │
                           ▼
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                    SUPERVISOR (core/)                        │
│                                                             │
│  ┌─────────────────────────────────────────────────────┐    │
│  │           Intent Classification (GPT-4o)            │    │
│  │                                                     │    │
│  │  Intents:  ORDER_TRACKING · FAQ · PRODUCT_QUERY     │    │
│  │            RETURNS · COMPLAINT · ESCALATE           │    │
│  │            GREETING · OUT_OF_SCOPE                  │    │
│  └──────────────────────┬──────────────────────────────┘    │
│                         │                                   │
│  ┌──────────────────────┴──────────────────────────────┐    │
│  │              Confidence Check                       │    │
│  │         >= 0.7 → Route to Agent                     │    │
│  │         <  0.7 → Escalate to Human                  │    │
│  └─────────────────────────────────────────────────────┘    │
│                                                             │
│  ┌─────────────────┐        ┌─────────────────┐            │
│  │ Conversation    │        │   Escalation    │            │
│  │ Memory (Redis)  │        │   Manager       │            │
│  │                 │        │                 │            │
│  │ 10 msgs/session │        │ Email alert to  │            │
│  │ 24hr TTL        │        │ support team +  │            │
│  └─────────────────┘        │ customer ack    │            │
│                             └─────────────────┘            │
└──────────────────────────┬──────────────────────────────────┘
                           │
              ┌────────────┼────────────┬────────────┐
              ▼            ▼            ▼            ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│  FAQ Agent   │ │ Order Agent  │ │Returns Agent │ │Product Agent │
│              │ │              │ │              │ │              │
│ Query →      │ │ Regex extract│ │ Policy from  │ │ Semantic     │
│ Embed →      │ │ order number │ │ Pinecone →   │ │ search →     │
│ Pinecone →   │ │ (JR-XXXX) → │ │ GPT-4o       │ │ GPT-4o       │
│ GPT-4o       │ │ Shopify →    │ │ guided flow  │ │ availability │
│ grounded     │ │ Carrier API  │ │ + RET-XXXXXX │ │ + upsell     │
│ answer       │ │              │ │ reference    │ │              │
└──────┬───────┘ └──────┬───────┘ └──────┬───────┘ └──────┬───────┘
       │                │                │                │
       ▼                ▼                ▼                ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│   Pinecone   │ │   Shopify    │ │   Pinecone   │ │   Pinecone   │
│   NS: faqs   │ │  Admin API   │ │   NS: faqs   │ │ NS: products │
└──────────────┘ └──────┬───────┘ └──────────────┘ └──────────────┘
                        │
                        ▼
              ┌──────────────────┐
              │  Order Tracker   │
              │  (auto-detect)   │
              └────────┬─────────┘
                       │
          ┌────────────┼────────────┬────────────┐
          ▼            ▼            ▼            ▼
   ┌────────────┐┌────────────┐┌────────────┐┌────────────┐
   │ Royal Mail ││    DHL     ││    Evri    ││    DPD     │
   │            ││            ││            ││            │
   │ AB..789GB  ││ JD.. / 10d ││ 15-16 char ││  14 digit  │
   └────────────┘└────────────┘└────────────┘└────────────┘

┌─────────────────────────────────────────────────────────────┐
│                   KNOWLEDGE BASE PIPELINE                    │
│                                                             │
│  documents/*.md ──→ ingest.py ──→ Pinecone (NS: faqs)      │
│  Shopify catalogue ──→ shopify_sync.py ──→ Pinecone         │
│                                              (NS: products) │
└─────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────┐
│                      INFRASTRUCTURE                          │
│                                                             │
│  Redis ─── Conversation memory + session state              │
│  GCP Cloud Run ─── Container hosting (port 8080)            │
│  Pinecone ─── Vector DB (faqs + products namespaces)        │
│  OpenAI GPT-4o ─── Intent classification + generation       │
│  OpenAI text-embedding-3-small ─── Embedding model          │
│  Shopify Admin API ─── Orders, products, fulfillments       │
│  Twilio ─── WhatsApp Business Cloud API                     │
│  Gmail API ─── Pub/Sub push notifications + send            │
└─────────────────────────────────────────────────────────────┘
```

## Quick Start

### 1. Clone and install

```bash
cd jaded-rose-chatbot
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### 2. Configure environment

```bash
cp .env.example .env
# Edit .env with your API keys
```

### 3. Start Redis

```bash
# Docker
docker run -d -p 6379:6379 redis:alpine

# Or install locally
brew install redis && redis-server
```

### 4. Ingest knowledge base

```bash
python -m knowledge_base.ingest
python -m knowledge_base.shopify_sync
```

### 5. Run the server

```bash
uvicorn main:app --host 0.0.0.0 --port 8080 --reload
```

The chatbot will be available at:
- **Health check:** `http://localhost:8080/health`
- **Web widget:** `http://localhost:8080/static/index.html`
- **Telegram webhook:** `http://localhost:8080/webhook/telegram`
- **WhatsApp webhook:** `http://localhost:8080/webhook/whatsapp`
- **Gmail push:** `http://localhost:8080/webhook/gmail`

## Environment Variables

| Variable | Description |
|---|---|
| `TELEGRAM_BOT_TOKEN` | Telegram bot token from @BotFather |
| `TWILIO_ACCOUNT_SID` | Twilio account SID |
| `TWILIO_AUTH_TOKEN` | Twilio auth token |
| `WHATSAPP_FROM_NUMBER` | Twilio WhatsApp sender number |
| `GMAIL_CREDENTIALS_JSON` | Path to Google OAuth credentials JSON |
| `GMAIL_SUPPORT_ADDRESS` | Support inbox email address |
| `OPENAI_API_KEY` | OpenAI API key |
| `PINECONE_API_KEY` | Pinecone API key |
| `PINECONE_INDEX` | Pinecone index name |
| `SHOPIFY_STORE_URL` | Shopify store URL |
| `SHOPIFY_ADMIN_API_KEY` | Shopify Admin API access token |
| `REDIS_URL` | Redis connection string |
| `ESCALATION_EMAIL` | Email for human escalation alerts |
| `ROYAL_MAIL_API_KEY` | Royal Mail Tracking API key |
| `DHL_API_KEY` | DHL Tracking API key |
| `DPD_API_KEY` | DPD Tracking API key |

## Running Tests

```bash
pytest tests/ -v
```

## Deploy to GCP (Cloud Run)

### Build and push

```bash
export PROJECT_ID=your-gcp-project
gcloud builds submit --tag gcr.io/$PROJECT_ID/jaded-rose-chatbot
```

### Deploy

```bash
gcloud run deploy jaded-rose-chatbot \
  --image gcr.io/$PROJECT_ID/jaded-rose-chatbot \
  --platform managed \
  --region europe-west2 \
  --port 8080 \
  --allow-unauthenticated \
  --set-env-vars "$(cat .env | grep -v '^#' | xargs | tr ' ' ',')"
```

### Set up webhooks

After deployment, configure your webhook URLs:

- **Telegram:** `https://YOUR_URL/webhook/telegram` (set via BotFather or Telegram API)
- **Twilio WhatsApp:** `https://YOUR_URL/webhook/whatsapp` (set in Twilio console)
- **Gmail:** Set up Pub/Sub push to `https://YOUR_URL/webhook/gmail`

## Message Flow

```
  Customer sends               Channel receives             Core processes
  "Where is #JR-4821?"         & normalises message         & routes to agent

  ┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
  │                 │     │                      │     │                      │
  │  Customer types │────▶│  Channel Handler     │────▶│  Supervisor          │
  │  message on     │     │                      │     │                      │
  │  Telegram /     │     │  • Validate request  │     │  1. Load history     │
  │  WhatsApp /     │     │  • Extract sender ID │     │     from Redis       │
  │  Gmail /        │     │  • Build session_id  │     │  2. Classify intent  │
  │  Web Widget     │     │  • Detect tracking # │     │     via GPT-4o       │
  │                 │     │    (WhatsApp)         │     │  3. Check confidence │
  └─────────────────┘     └──────────────────────┘     │  4. Route to agent   │
                                                       └──────────┬───────────┘
                                                                  │
                          intent = ORDER_TRACKING                 │
                          confidence = 0.94                       │
                          entities = {order: "JR-4821"}           │
                                                                  ▼
  ┌─────────────────┐     ┌──────────────────────┐     ┌──────────────────────┐
  │                 │     │                      │     │                      │
  │  Customer sees  │◀────│  Channel formats     │◀────│  Order Agent         │
  │  tracking info  │     │  & sends reply       │     │                      │
  │  with status    │     │                      │     │  1. Regex: JR-4821   │
  │  emoji + ETA    │     │  • Telegram MD       │     │  2. Shopify lookup   │
  │                 │     │  • WhatsApp text     │     │  3. Get tracking #   │
  │  "Your order    │     │  • Gmail HTML thread │     │  4. Detect carrier   │
  │   is in transit │     │  • WebSocket JSON    │     │  5. Royal Mail API   │
  │   📦 ..."       │     │                      │     │  6. Format response  │
  └─────────────────┘     └──────────────────────┘     └──────────────────────┘
```

## Escalation Flow

```
  ┌───────────────────┐     confidence < 0.7
  │    Supervisor     │──── OR intent = ESCALATE ────┐
  │  (low confidence  │     OR intent = COMPLAINT    │
  │   or explicit     │                              ▼
  │   escalation)     │              ┌───────────────────────────┐
  └───────────────────┘              │    Escalation Manager     │
                                     │                           │
                                     │  1. Format transcript     │
                                     │  2. Email support team    │
                                     │     (full conversation)   │
                                     │  3. Reply to customer:    │
                                     │     "Connecting you with  │
                                     │      our team — they'll   │
                                     │      be in touch within   │
                                     │      2 hours."            │
                                     └───────────────────────────┘
```

## Project Structure

```
jaded-rose-chatbot/
│
├── main.py                          # FastAPI app — mounts all routes + WebSocket
│
├── channels/                        # ── Channel Integrations ──────────────────
│   ├── telegram/
│   │   ├── bot.py                   #   python-telegram-bot v20+ handlers
│   │   └── webhooks.py              #   POST /webhook/telegram
│   ├── whatsapp/
│   │   ├── bot.py                   #   Twilio message handler + tracking regex
│   │   └── webhooks.py              #   POST /webhook/whatsapp (signature verify)
│   ├── gmail/
│   │   ├── listener.py              #   Pub/Sub push notifications + spam filter
│   │   └── responder.py             #   Threaded HTML replies with branding
│   └── web/
│       ├── api.py                   #   WebSocket /ws/chat endpoint
│       ├── widget.js                #   Embeddable floating chat widget (vanilla JS)
│       └── index.html               #   Standalone test page
│
├── core/                            # ── Brain ─────────────────────────────────
│   ├── supervisor.py                #   Intent classification + agent routing
│   ├── memory.py                    #   Redis-backed conversation memory
│   └── escalation.py               #   Human handoff via email alert
│
├── agents/                          # ── Specialist Agents ─────────────────────
│   ├── faq_agent.py                 #   RAG: embed → Pinecone → GPT-4o
│   ├── order_agent.py               #   Order # regex → Shopify → carrier track
│   ├── returns_agent.py             #   Policy retrieval → guided return flow
│   └── product_agent.py             #   Product search → availability + upsell
│
├── knowledge_base/                  # ── RAG Pipeline ──────────────────────────
│   ├── ingest.py                    #   Chunk .md docs → embed → Pinecone (faqs)
│   ├── shopify_sync.py              #   Shopify catalogue → Pinecone (products)
│   └── documents/
│       ├── faq.md                   #   Store FAQ (delivery, payments, sizing)
│       ├── returns_policy.md        #   30-day return policy
│       └── size_guide.md            #   UK size charts (women's + men's)
│
├── tracking/                        # ── Parcel Tracking ───────────────────────
│   ├── tracker.py                   #   Auto-detect carrier from tracking format
│   ├── shopify_fulfillment.py       #   Extract tracking # from Shopify orders
│   └── carriers/
│       ├── royal_mail.py            #   Royal Mail API (AB123456789GB)
│       ├── dhl.py                   #   DHL Tracking API v2 (JD... / 10-digit)
│       ├── evri.py                  #   Evri API (15-16 alphanumeric)
│       └── dpd.py                   #   DPD API (14-digit)
│
├── tests/                           # ── Test Suite ────────────────────────────
│   ├── test_supervisor.py           #   Intent routing, escalation, greetings
│   ├── test_order_agent.py          #   Order # regex, fulfillment lookups
│   └── test_tracker.py              #   Carrier detection, fallback logic
│
├── .env.example                     # All 16 environment variables documented
├── requirements.txt                 # Python dependencies
├── Dockerfile                       # Python 3.11-slim, port 8080, uvicorn
└── README.md                        # This file
```

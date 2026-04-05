# Deploying Jaded Rose Chatbot on GCP Compute Engine

## Prerequisites

- GCP Compute Engine instance (e2-micro is fine for Telegram-only)
- SSH access to the VM
- API keys: `OPENAI_API_KEY`, `PINECONE_API_KEY`, `TELEGRAM_BOT_TOKEN`, `REDIS_URL`

## Quick Start

### 1. Clone the repo on your VM

```bash
ssh -i ~/.ssh/gcp_key cohiba@YOUR_VM_IP
git clone https://github.com/Jaded-Rose/02_jaded-rose-chatbot.git
cd 02_jaded-rose-chatbot
```

### 2. Create your .env file

```bash
cp .env.example .env
nano .env   # fill in all API keys
```

### 3. Run the setup script

```bash
chmod +x deploy/setup.sh
./deploy/setup.sh
```

This installs dependencies, creates a Python venv, and sets up a **systemd service** that:
- Starts automatically on boot
- Restarts if it crashes
- Survives SSH disconnects

### 4. Verify it's running

```bash
sudo systemctl status jaded-rose-chatbot
sudo journalctl -u jaded-rose-chatbot -f   # tail logs
curl http://localhost:8080/health            # should return {"status":"ok"}
```

## Manual Setup (without the script)

### Install dependencies

```bash
sudo apt-get update && sudo apt-get install -y python3 python3-venv
cd ~/02_jaded-rose-chatbot
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Run in background (quick method)

```bash
source .venv/bin/activate
nohup uvicorn main:app --host 0.0.0.0 --port 8080 > chatbot.log 2>&1 &
```

### Run as systemd service (recommended)

```bash
sudo cp deploy/jaded-rose-chatbot.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable jaded-rose-chatbot
sudo systemctl start jaded-rose-chatbot
```

## Common Commands

| Action | Command |
|--------|---------|
| Check status | `sudo systemctl status jaded-rose-chatbot` |
| View logs | `sudo journalctl -u jaded-rose-chatbot -f` |
| Restart | `sudo systemctl restart jaded-rose-chatbot` |
| Stop | `sudo systemctl stop jaded-rose-chatbot` |
| Update code | `git pull && sudo systemctl restart jaded-rose-chatbot` |

## Ingest Knowledge Base

After deployment, ingest the .kb files into Pinecone:

```bash
source .venv/bin/activate
python -m knowledge_base.ingest
```

## Troubleshooting

**Bot not responding after SSH disconnect?**
You were probably running uvicorn in the foreground. Set up the systemd service (see above) so it persists.

**TELEGRAM_BOT_TOKEN not set?**
Make sure `.env` exists in the project root with the correct token. The app uses `load_dotenv` with an explicit path.

**Pinecone 401 Unauthorized?**
Verify your `PINECONE_API_KEY` in the Pinecone dashboard. Keys can be regenerated there.

**Redis connection failed?**
Check `REDIS_URL` format: `redis://default:PASSWORD@HOST:PORT`

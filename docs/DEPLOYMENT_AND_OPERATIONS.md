# Deployment & Operations Guide

This guide covers deploying, maintaining, and updating Helmis in production on a self-hosted Linux VPS.

---

## 1. System Requirements

- **OS**: Ubuntu 22.04 LTS or Debian 12 (x86_64 or arm64)
- **CPU**: 1 vCPU minimum (2 vCPUs recommended)
- **RAM**: 2 GB RAM minimum (4 GB recommended)
- **Disk**: 20 GB SSD storage minimum
- **Runtime**: Docker Engine 24+ and Docker Compose v2+

---

## 2. Production Deployment Procedure

### Initial Host Setup
```bash
# 1. Update system packages
apt update && apt upgrade -y

# 2. Install Docker and Compose
curl -fsSL https://get.docker.com | sh

# 3. Create deployment directory
mkdir -p /opt/helmis
cd /opt/helmis

# 4. Clone repository
git clone https://github.com/gimigkk/Helmis.git .

# 5. Configure environment secrets
cp .env.example .env
nano .env
```

### Launching the Stack
```bash
docker compose up -d --build
```

---

## 3. Healthcheck & Monitoring

Inspect the health and status of all services:

```bash
# Check container status and health
docker compose ps

# Expected output:
# NAME               IMAGE                     STATUS                    PORTS
# helmis-agent       helmis-agent              Up (healthy)              8765/tcp
# helmis-scheduler   helmis-scheduler          Up                        
# helmis-waha        devlikeapro/waha:latest   Up (healthy)              0.0.0.0:3005->3000/tcp

# View real-time agent execution logs
docker compose logs -f agent --tail 50

# View WAHA WhatsApp bridge logs
docker compose logs -f waha --tail 50

# View scheduler cron trigger logs
docker compose logs -f scheduler --tail 50
```

---

## 4. Zero-Downtime Code Updates

To deploy new code changes without dropping WhatsApp sessions or losing data:

```bash
cd /opt/helmis

# 1. Pull latest changes
git fetch origin && git reset --hard origin/main

# 2. Rebuild and recreate ONLY the agent (waha/scheduler stay up; sessions preserved)
docker compose build agent
docker compose up -d agent

# 3. Verify health
sleep 6
docker compose ps agent
```

**Production-validated notes:**
- `docker compose up -d` **alone does NOT rebuild** — a stale container was shipped once because the build step was skipped; always run `build` before `up -d`.
- Remote must be SSH (`git@github.com:gimigkk/Helmis.git`) — HTTPS lacks credentials on the VPS.
- **NEVER touch `/opt/helmis/data/` or `/opt/helmis/.env`** — live memory sidecar, SQLite DB, WAHA session, and the 8 `GEMINI_KEY_*` secrets live there.
- Full loop used in this session: local `git checkout main && git merge feat/... && git push origin main`, then VPS sync+build above.
- Pre-deploy safety backup exists at `/root/helmis_backup_20260903_054505.tar.gz`; `scripts/rollback.sh` automates the rollback path.

---

## 5. Backup & Recovery

All user data (tasks, notes, documents, memory vectors) lives in `./data/` and `./config/`.

### Creating a Backup
```bash
tar -czvf /root/helmis_backup_$(date +%Y%m%d_%H%M%S).tar.gz ./data ./config .env
```

### Restoring from Backup
```bash
docker compose down
tar -xzvf /path/to/backup.tar.gz -C /opt/helmis/
docker compose up -d
```

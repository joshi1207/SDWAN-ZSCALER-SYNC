# Zscaler → Cisco vManage Sync  
Automated import of Zscaler ZPA/ZIA IP prefixes into Cisco SD-WAN (vManage) Data Prefix Lists.

This tool retrieves Zscaler IP ranges, normalizes them, breaks them into safe-sized chunks (because vManage rejects >500 entries in a single Data Prefix List), and automatically updates the configured DPL in vManage.

---

## 🚀 Features

- Fully automated vManage login flow (JSESSION + XSRF)
- Fetch ZPA/ZIA/Global Zscaler JSON
- IPv4-only, IPv6-only, or dual-stack operation
- Delta detection (add/remove)
- Backup of each DPL before updating
- Chunking support (`≤500` entries per list)
- Automatic creation of new chunk lists
- Optional CLI template integration (future)
- Production-grade error handling & logging

---

## 📦 Repository Contents

```
zscaler-vmanage-sync/
│
├── README.md
├── LICENSE                (optional)
├── .gitignore
│
├── zscaler_to_vmanage.py
├── update_cli_addon_nat.py           (CLI NAT template generator – optional)
│
├── config/
│   ├── env.example
│   └── sample_dpl_backup.json
│
├── docs/
│   ├── OVERVIEW.md
│   ├── ARCHITECTURE.md
│   ├── WORKFLOW.md
│   ├── TROUBLESHOOTING.md
│   ├── CHANGELOG.md
│   └── SECURITY_NOTES.md
│
└── systemd/
    ├── zscaler-sync.service
    └── zscaler-sync.timer
```

---

## ⚙️ Installation

### 1. Create user + directory
```bash
sudo useradd -m -s /bin/bash zscaler-sync
sudo mkdir -p /opt/zscaler-sync
sudo chown -R zscaler-sync:zscaler-sync /opt/zscaler-sync
```

### 2. Install virtualenv
```bash
python3 -m venv /opt/zscaler-sync/.venv
/opt/zscaler-sync/.venv/bin/pip install requests
```

### 3. Clone repo
```bash
sudo -u zscaler-sync git clone https://github.com/joshi1207/zscaler-vmanage-sync.git /opt/zscaler-sync/
```

---

## 🔧 Configure `.env`

Copy:
```bash
cp config/env.example .env
```

Edit:

```md
# --- vManage ---
VMANAGE_HOST=192.168.1.67
VMANAGE_PORT=8443
VMANAGE_USER=admin
VMANAGE_PASS=StrongPass123
VERIFY_TLS=false

# --- Zscaler ---
ZSCALER_JSON_URL=https://config.zscaler.com/api/zscaler.net/zpa/json
ZSCALER_FAMILY=ipv4      # ipv4 | ipv6 | both

# --- Limits ---
MAX_REMOVE_PERCENT=25
ZSCALER_MAX_CHUNK=500

# --- Paths ---
CACHE_FILE=/opt/zscaler-sync/cache.json
BACKUP_DIR=/opt/zscaler-sync/backups
LOG_LEVEL=INFO
```

---

## ▶️ Run

```bash
sudo -u zscaler-sync -H bash -lc '
set -a; source .env; set +a;
/opt/zscaler-sync/.venv/bin/python zscaler_to_vmanage.py
'
```

---

## 🛠 systemd Automation (Optional)

### `zscaler-sync.service`
```ini
[Unit]
Description=Zscaler → vManage Sync Service

[Service]
User=zscaler-sync
WorkingDirectory=/opt/zscaler-sync
ExecStart=/opt/zscaler-sync/.venv/bin/python /opt/zscaler-sync/zscaler_to_vmanage.py
```

### `zscaler-sync.timer`
```ini
[Unit]
Description=Run Zscaler Sync every 12 hours

[Timer]
OnBootSec=5min
OnUnitActiveSec=12h

[Install]
WantedBy=timers.target
```

Enable:
```bash
sudo systemctl enable --now zscaler-sync.timer
```

---

##################################################################################################################################

Users will:

cp config/env.example .env
# edit .env with their values

On automation Host:

sudo mkdir -p /opt/zscaler-sync
sudo chown -R zscaler-sync:zscaler-sync /opt/zscaler-sync

# from GitHub repo root:
sudo rsync -av . /opt/zscaler-sync/

cd /opt/zscaler-sync
python3 -m venv .venv
./.venv/bin/pip install -r requirements.txt

cp config/env.example .env
# edit .env

sudo cp systemd/zscaler-sync.service /etc/systemd/system/
sudo cp systemd/zscaler-sync.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now zscaler-sync.timer

## Quick Start

```bash
git clone https://github.com/<you>/zscaler-vmanage-sync.git
cd zscaler-vmanage-sync

python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt

cp config/env.example .env
# edit .env with your vManage + Zscaler details

python src/zscaler_to_vmanage.py --dry-run   # see planned changes
python src/zscaler_to_vmanage.py             # apply to vManage

# 📄 License

MIT License (recommended)

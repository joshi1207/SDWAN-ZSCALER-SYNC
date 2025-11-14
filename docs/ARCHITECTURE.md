# Architecture

## Components

### 1. ZPA/ZIA JSON Loader
- Pulls JSON from `config.zscaler.com/api/.../json`
- Normalizes CIDRs using `ipaddress` module
- Supports IPv4 / IPv6 filtering via `ZSCALER_FAMILY`

### 2. Delta Engine
Compares:
- Existing vManage DPL entries  
- New Zscaler entries  

Determines:
- Additions  
- Removals  

### 3. vManage REST Client

Implements the full vManage session handshake:

1. `GET /` → seed cookies  
2. `POST /j_security_check` → login  
3. `GET /dataservice/client/token` → XSRF token  
4. Use `X-XSRF-TOKEN` for all API calls

### 4. Chunk Manager
Because vManage rejects “too large” lists, chunking is implemented:

```
total_entries = 988
max_chunk = 500
chunks = split(entries, size=500)

creates:
ZSCALER_BYPASS_01  → 500 entries
ZSCALER_BYPASS_02  → 488 entries
```

### 5. Backup Engine
Before changes:

```
/opt/zscaler-sync/backups/ZSCALER_BYPASS-YYYYMMDD-HHMMSS.json
```

Contains full JSON.

---

# Flow Diagram (ASCII)

```
        ┌────────────────────┐
        │  Zscaler JSON      │
        │  (config.zscaler)  │
        └─────────┬──────────┘
                  │
          Fetch & Parse
                  │
        ┌─────────▼──────────┐
        │ Normalize CIDRs     │
        │ Filter IPv4/IPv6    │
        └─────────┬──────────┘
                  │
            Compare with
          existing DPL(s)
                  │
  ┌───────────────▼────────────────┐
  │  Needs chunking? (>500)        │
  └───────┬────────────────────────┘
          │ no
          │
          ▼
 Update main DPL

          │ yes
          ▼
 Create/Update sublists
  (_01, _02, _03...)

```


# Operational Workflow

## Scheduled Job

1. systemd timer triggers script every 12 hours
2. Script loads `.env`
3. Script logs into vManage
4. Fetches Zscaler JSON
5. Normalizes CIDRs
6. Delta detection
7. If too many removals:
   - Honors `MAX_REMOVE_PERCENT`
8. Backs up existing DPL
9. Updates DPL + chunk lists
10. Logs result to stdout or Teams webhook (optional)

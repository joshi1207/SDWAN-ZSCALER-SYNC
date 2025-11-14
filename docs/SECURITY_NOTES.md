# Security Notes

### Do NOT commit:
- `.env`
- Any DPL backup containing real prefixes
- vManage credentials
- Token dump files
- Output logs with sensitive paths

### Recommended:
- Use a dedicated low-privilege vManage user
- Limit network access to Zscaler + vManage only
- Use TLS verification in production (VERIFY_TLS=true)
- Enable RBAC audit logging on vManage

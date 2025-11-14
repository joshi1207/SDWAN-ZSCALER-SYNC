# Troubleshooting Guide

### ❌ 400 Invalid policy (ipPrefix missing)
Cause:
- Wrong Zscaler JSON endpoint  
- ZPA/ZIA format mismatch  
- IPv6 entries included where vManage does not accept IPv6

Fix:
- Use correct endpoint:  
  `https://config.zscaler.com/api/zscaler.net/zpa/json`
- Use IPv4 only:  
  `ZSCALER_FAMILY=ipv4`

---

### ❌ SessionTokenFilter: token mismatch
Cause:
- XSRF token extracted before cookies updated

Fix:
- Always capture token using the same cookie jar
- Do not call `/dataservice/...` between token steps

---

### ❌ Validation failed on list type dataPrefix
Cause:
- List exceeds vManage internal limit

Fix:
- Set `ZSCALER_MAX_CHUNK=500`

---

### ❌ vManage returns 403
Cause:
- Controller in vManage-mode requiring REFs  
- User has insufficient permissions

Fix:
- Ensure user has:
  - Policy Editor
  - Template Editor
  - CLI write permissions

# Project Overview

The purpose of this tool is to automate the synchronization of Zscaler-provided IP prefix lists into Cisco vManage.

Cisco vManage has strict validation rules and a hard limit of ~500 entries per Data Prefix List. Zscaler publishes 1000+ prefixes, which makes manual updates impossible.

This tool handles:

- Fetching Zscaler JSON
- Normalizing IPv4/IPv6 CIDRs
- Chunking large lists into multiple suffix lists
  - e.g., `ZSCALER_BYPASS_01`, `ZSCALER_BYPASS_02`, …
- Updating vManage Data Prefix Lists via REST API

This eliminates:
- Manual edits
- Frequent outages due to stale bypass rules
- Human error when copying large numbers of prefixes

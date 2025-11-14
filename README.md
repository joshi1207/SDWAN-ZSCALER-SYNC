# SDWAN-ZSCALER-SYNC
Automated import of Zscaler ZPA/ZIA IP prefixes into Cisco SD-WAN (vManage) Data Prefix Lists.  This tool retrieves Zscaler IP ranges, normalizes them, breaks them into safe-sized chunks (because vManage rejects >500 entries in a single Data Prefix List), and automatically updates the configured DPL in vManage.

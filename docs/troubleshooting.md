# Wi-Lab Troubleshooting Guide

## Quick Diagnostic Commands

### Check Service Status

```bash
# Is Wi-Lab running?
sudo systemctl status wilab.service

# Is it enabled for autostart?
sudo systemctl is-enabled wilab.service
# Output: enabled or disabled

# Is API responding?
curl http://localhost:8080/api/v1/health
# Expected: {"status":"ok"}
```

### View Service Logs

```bash
# Real-time logs (follow mode)
sudo journalctl -u wilab.service -f

# Last 100 lines
sudo journalctl -u wilab.service -n 100

# Since last boot
sudo journalctl -u wilab.service -b

# Since 1 hour ago
sudo journalctl -u wilab.service --since "1 hour ago"

# Errors only
sudo journalctl -u wilab.service | grep -E "ERROR|CRITICAL|Traceback"
```

---

## Service Management

### Start/Stop/Restart Service

```bash
# Start Wi-Lab
sudo systemctl start wilab.service

# Stop Wi-Lab
sudo systemctl stop wilab.service

# Restart Wi-Lab (stop + start)
sudo systemctl restart wilab.service

# Reload configuration (if systemd file changed)
sudo systemctl daemon-reload
```

### Enable/Disable Autostart

```bash
# Enable autostart on boot
sudo systemctl enable wilab.service

# Disable autostart
sudo systemctl disable wilab.service

# Check autostart status
sudo systemctl is-enabled wilab.service
```

---

## Common Issues

### Issue 1: Service Fails to Start

**Symptoms:**
- `systemctl status` shows "failed" or "inactive"
- API unreachable

**Diagnosis:**
```bash
# Check logs for errors
sudo journalctl -u wilab.service -n 50 | grep -i "error"

# Check Python syntax errors
/opt/wilab-venv/bin/python /home/simone/wi-lab/main.py

# Check if another service uses port 8080
sudo lsof -ti:8080
```

**Common causes:**
1. **Port 8080 in use:** Check `sudo lsof -ti:8080`, kill other process or change port in config
2. **Config file invalid:** Run `python3 -c "import yaml; yaml.safe_load(open('config.yaml'))"`
3. **WiFi interface not available:** Run `iw dev`, verify interface name in config
4. **Permissions:** Service must run as root (check `User=root` in service file)

**Resolution:**
```bash
# Fix config file if needed
nano /home/simone/wi-lab/config.yaml

# Verify config
python3 -c "from wilab.config import load_config; load_config('config.yaml')"

# Restart service
sudo systemctl restart wilab.service

# Check logs
sudo journalctl -u wilab.service -f
```

### Issue 2: API Responds But Cannot Create WiFi Network

**Symptoms:**
- Health check works: `curl http://localhost:8080/api/v1/health` returns `{"status":"ok"}`
- Network creation fails
- API returns error response

**Diagnosis:**
```bash
# Check logs for detailed error
sudo journalctl -u wilab.service -f

# Verify WiFi interface exists
iw dev

# Check interface supports AP mode
iw list | grep -A 5 "Supported interface modes" | grep "AP"

# Verify interface is free (not in use by NetworkManager)
nmcli dev
```

**Common causes:**
1. **Interface not found:** Name mismatch in config
2. **No AP mode support:** Driver doesn't support AP
3. **Interface in use:** NetworkManager or other app controlling it

**Resolution:**
```bash
# Find correct interface name
iw dev
# Update config.yaml with exact name

# Restart service
sudo systemctl restart wilab.service

# Try creating network again via API
curl -X POST http://localhost:8080/api/v1/interface/wlx782051245264/network \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{
    "ssid": "TestAP",
    "channel": 6,
    "band": "2.4ghz",
    "encryption": "wpa2",
    "password": "test1234",
    "tx_power_level": 4
  }'
```

### Issue 3: WiFi Network Running But Clients Cannot Connect

**Symptoms:**
- Network visible on client devices
- Clients cannot connect or cannot access Internet

**Diagnosis:**
```bash
# Check network status
curl http://localhost:8080/api/v1/interface/wlx782051245264/network

# Check connected clients
curl http://localhost:8080/api/v1/interface/wlx782051245264/clients

# Check hostapd running
ps aux | grep [h]ostapd

# Check dnsmasq running
ps aux | grep [d]nsmasq

# Check iptables rules
sudo iptables -L FORWARD -n -v | head -20
```

**Common causes:**
1. **DHCP not working:** dnsmasq not running or misconfigured
2. **No Internet access:** NAT rules missing or disabled
3. **Subnet conflict:** WiFi subnet conflicts with host network

**Resolution:**
```bash
# Verify logs
sudo journalctl -u wilab.service -f

# If subnet conflict suspected:
# Check host subnet
ip addr show | grep "inet "

# Check WiFi subnet in config
grep dhcp_base_network config.yaml

# If conflict: update config, restart service
sudo systemctl restart wilab.service
```

### Issue 4: SSH Connection Lost After Network Creation

**Symptoms:**
- SSH disconnects immediately after creating WiFi network
- Cannot reconnect via SSH
- Host networking broken

**Cause:** WiFi subnet conflicts with host network (see [networking.md](networking.md))

**Emergency Recovery:**

**Option A: Console/IPMI Access**
```bash
# At console:
# Stop service
sudo systemctl stop wilab.service

# Fix config
nano /home/simone/wi-lab/config.yaml
# Change dhcp_base_network to different subnet

# Restart
sudo systemctl restart wilab.service
```

**Option B: Reboot**
```bash
# System reboot clears iptables rules
sudo reboot

# After reboot: fix config and restart
```

**Prevention:**
```bash
# Before deploying, always verify host subnet
ip addr show | grep "inet " | head -1
# If output is 192.168.10.113/24, use 192.168.120.0/24 for WiFi

# Update config
grep dhcp_base_network config.yaml

# Verify no conflict
```

### Issue 5: TX Power Not Changing

**Symptoms:**
- TX power set via API, but doesn't take effect
- Driver doesn't support dynamic power change

**Diagnosis:**
```bash
# Check TX power capability
iw dev wlx782051245264 info | grep "tx power"

# Verify power was set
curl http://localhost:8080/api/v1/interface/wlx782051245264/txpower

# Check for warning indicating unsupported hardware
# Response will include: "warning": "Interface does not support dynamic power change"
```

**Common causes:**
1. **Hardware limitation:** Driver (e.g., rtw88_8822bu) doesn't support dynamic TX power
2. **Network must be recreated:** Some drivers require network restart to apply power changes

**Resolution:**
```bash
# If warning present: stop and recreate network with desired TX power
curl -X DELETE http://localhost:8080/api/v1/interface/wlx782051245264/network

# Recreate with desired power level
curl -X POST http://localhost:8080/api/v1/interface/wlx782051245264/network \
  -H "Authorization: Bearer token" \
  -H "Content-Type: application/json" \
  -d '{
    "ssid": "TestAP",
    "channel": 6,
    "band": "2.4ghz",
    "encryption": "wpa2",
    "password": "test1234",
    "tx_power_level": 1
  }'
```

---

## Performance Issues

### WiFi Connection Slow or Unstable

**Diagnosis:**
```bash
# Check signal strength on client device
# Check channel and bandwidth
iw dev wlx782051245264 info

# Look for interference
sudo iw dev wlx782051245264 scan | grep -E "SSID:|signal:"

# Check TX power
curl http://localhost:8080/api/v1/interface/wlx782051245264/txpower | jq '.'
```

**Solutions:**
1. **Change channel:** Use less congested channels (1, 6, 11 on 2.4 GHz)
2. **Increase TX power:** Set `tx_power_level` to 4 when creating network
3. **Check WiFi band:** Use 5 GHz if available (less congestion)
4. **Reduce interference:** Move away from other 2.4 GHz devices

---

## Networking Issues

For detailed networking diagnostics, troubleshooting, and iptables/DNS issues, see:

**→ [networking.md](networking.md)**

Key sections:
- [Diagnostics and Monitoring](networking.md#diagnostics-and-monitoring)
- [Troubleshooting](networking.md#troubleshooting)
- [Emergency Recovery](networking.md#emergency-recovery)

---

## Testing and Validation

### Complete Health Check

```bash
#!/bin/bash
echo "=== Wi-Lab Health Check ==="
echo ""

# 1. Service status
echo "1. Service Status:"
sudo systemctl status wilab.service | grep "Active:"

# 2. API health
echo ""
echo "2. API Health:"
curl -s http://localhost:8080/api/v1/health | jq '.status'

# 3. Interfaces available
echo ""
echo "3. Available Interfaces:"
curl -s http://localhost:8080/api/v1/interfaces \
  -H "Authorization: Bearer your-token" | jq '.interfaces | length'

# 4. WiFi capability
echo ""
echo "4. WiFi Interface Status:"
iw dev | grep -E "Interface|type"

# 5. Port listening
echo ""
echo "5. Port 8080 Listening:"
sudo ss -tlnp | grep :8080 | awk '{print "✓", $4}'

# 6. Recent errors
echo ""
echo "6. Recent Errors:"
sudo journalctl -u wilab.service -n 20 | grep -i "error" | wc -l

echo ""
echo "=== Check Complete ==="
```

### API Testing

See [swagger.md](swagger.md) for complete API testing guide with examples.

---

## Debug Mode

### Enable Verbose Logging

```bash
# Increase logging in Python (if supported)
PYTHONVERBOSE=2 /opt/wilab-venv/bin/python /home/simone/wi-lab/main.py

# View with timestamps
sudo journalctl -u wilab.service --timestamps=precise -f
```

### Manual Service Start (For Debugging)

```bash
# Stop background service
sudo systemctl stop wilab.service

# Run in foreground (Ctrl+C to stop)
CONFIG_PATH=/home/simone/wi-lab/config.yaml /opt/wilab-venv/bin/python /home/simone/wi-lab/main.py

# Errors and output visible directly
```

---

## Getting Help

1. **Check logs:** `sudo journalctl -u wilab.service -n 50`
2. **Verify configuration:** See [installation-guide.md](installation-guide.md)
3. **Network issues:** See [networking.md](networking.md)
4. **API testing:** See [swagger.md](swagger.md)
5. **Development:** See [README-DEV.md](../README-DEV.md)

---

**Service issue resolved! 🔧**

If problems persist, collect logs and create a GitHub issue.

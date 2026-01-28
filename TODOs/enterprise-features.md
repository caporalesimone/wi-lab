# Feature: Enterprise Features Foundation & Docker Support

**Priority:** 10  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Provide Docker containerization for deployment flexibility, regulatory domain support for international usage, and lay groundwork for future enterprise features.

## Part 1: Docker Compose Support

### Implementation Tasks

- [ ] Create `docker-compose.yml` in project root with services:
  - **wilab-api** - Main Wi-Lab API service
  - **nginx** (optional) - Reverse proxy for TLS and routing
  - **redis** (optional) - For caching and session storage

### Docker Configuration

- [ ] Use host network mode for WiFi interface access
- [ ] Volume mounts:
  - `/etc/wilab` - Configuration directory
  - `/var/lib/wilab` - Data persistence
  - `/sys` - System interface access
  - `/proc` - Process info access
- [ ] Environment variables for configuration
- [ ] Build stage for frontend compilation

### docker-compose.yml Structure

```yaml
version: '3.8'
services:
  wilab:
    image: wilab:latest
    container_name: wilab-api
    network_mode: host
    volumes:
      - ./config.yaml:/etc/wilab/config.yaml:ro
      - wilab-data:/var/lib/wilab
      - /sys:/sys:ro
      - /proc:/proc:ro
    environment:
      - WILAB_CONFIG=/etc/wilab/config.yaml
    restart: unless-stopped
    cap_add:
      - NET_ADMIN
      - SYS_ADMIN
    privileged: true

volumes:
  wilab-data:
```

### Dockerfile

- [ ] Ensure Dockerfile builds with dependencies
- [ ] Multi-stage build for frontend compilation
- [ ] Run as non-root user (if possible)
- [ ] Health check configuration
- [ ] Image layers optimized for size

### Testing

- [ ] Verify compose file syntax
- [ ] Test container startup and initialization
- [ ] Verify volume mounts working
- [ ] Test network access from container
- [ ] Test persistence across restarts

### Documentation

- [ ] Create `docs/docker-setup.md`
- [ ] Include docker-compose.yml walkthrough
- [ ] Explain volume configuration
- [ ] Document environment variables
- [ ] Include troubleshooting section

## Part 2: Regulatory Domain Support

### Implementation Tasks

- [ ] Create domain data structure: `{ domain_code: channels }`
- [ ] Supported domains:
  - `US` - United States (channels 1-11 2.4GHz, 36-165 5GHz)
  - `EU` - Europe (channels 1-13 2.4GHz, 36-144 5GHz)
  - `JP` - Japan (channels 1-14 2.4GHz, 36-48 5GHz)
  - `CN` - China (channels 1-13 2.4GHz, 149-165 5GHz)
  - `AU` - Australia (channels 1-13 2.4GHz, 36-165 5GHz)
  - `BR` - Brazil (channels 1-13 2.4GHz, 36-165 5GHz)
  - Add more as needed

### Configuration

- [ ] Add `regulatory_domain` parameter to config.yaml
- [ ] Default: `US`
- [ ] API endpoint to get supported domains
- [ ] Get current domain status

### Implementation

- [ ] Use `iw reg set <domain>` command on startup
- [ ] Validate domain before application
- [ ] Verify domain set successfully
- [ ] Use in channel validation
- [ ] Document channel support per region

### API Integration

- [ ] `GET /api/v1/admin/regulatory-domains` - List supported domains
- [ ] `GET /api/v1/admin/regulatory-domain` - Get current domain
- [ ] `PUT /api/v1/admin/regulatory-domain` - Set domain (admin only)
- [ ] Response includes available channels per band

### Health Check

- [ ] Add to health endpoint: `regulatory_domain` field
- [ ] Include available channels in health response

### Testing

- [ ] Unit tests for domain validation
- [ ] Unit tests for channel list per domain
- [ ] Test `iw reg set` command execution
- [ ] Verify channels available after domain change
- [ ] Mock iw command for test environment

### Documentation

- [ ] Document supported regulatory domains
- [ ] Explain how to change domain
- [ ] Include channel availability per region
- [ ] Add to README and Swagger docs

## Part 3: Advanced Features Foundation (Planning)

### Design Documentation

- [ ] **Multi-SSID Architecture** - How multiple networks per interface would work
  - Use vlan tagging or separate virtual interfaces
  - Share physical interface, separate virtual APs
  - Scalability implications (max N networks per interface)
  - Example: eth0 → vlan100 (SSID-A), vlan101 (SSID-B)

- [ ] **WPA-Enterprise / RADIUS Integration** - Enterprise authentication
  - Replace WPA2-PSK with WPA2-Enterprise
  - RADIUS server configuration (address, port, secret)
  - User database integration points
  - Security considerations

- [ ] **Persistent Network Storage** - Long-term data persistence
  - Current: In-memory storage (lost on restart)
  - Options: Redis, SQLite, PostgreSQL
  - Pros/cons of each
  - Migration strategy from in-memory

### Architecture Review

- [ ] Performance bottleneck analysis
- [ ] Scalability assessment (max networks, clients)
- [ ] Deployment considerations (single/multi-host)
- [ ] High availability options
- [ ] Load balancing strategy

### Future Roadmap

- [ ] Document v3.4+ feature candidates
- [ ] Prioritize based on user feedback
- [ ] Estimate effort for each feature
- [ ] Create issues/epics for future work

### Testing

- [ ] Design review with team
- [ ] Feasibility analysis for each feature
- [ ] Prototype key components if needed

## Benefits

- **Portability:** Docker enables deployment anywhere
- **Isolation:** Container isolation for security
- **Flexibility:** Compose configuration for custom setups
- **Global Ready:** Support for international regulatory requirements
- **Future Proof:** Foundation for enterprise scalability

## Breaking Changes

- None (optional features)

## Success Criteria

- ✅ docker-compose.yml working end-to-end
- ✅ Container starts and serves API correctly
- ✅ Volumes persist data across restarts
- ✅ Regulatory domains configurable
- ✅ Channel availability reflects domain
- ✅ Architecture documentation for v3.4+
- ✅ All features documented

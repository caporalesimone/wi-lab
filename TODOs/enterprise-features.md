# Feature: Enterprise Features Foundation & Docker Support

**Priority:** 10  
**Status:** PROPOSED  
**Estimated Effort:** ~2 hours  

## Description

Provide Docker containerization for deployment flexibility and lay groundwork for future enterprise features. (Regulatory domains are done: `country_code` in `config.yaml`, applied with `iw reg set` at startup; the channels offered follow the country.)

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

## Part 3: Advanced Features Foundation (Planning)

### Design Documentation

- Multi-SSID and WPA-Enterprise / RADIUS: see [ap-improvements.md](ap-improvements.md) (items 2 and 19).
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
- **Future Proof:** Foundation for enterprise scalability

## Breaking Changes

- None (optional features)

## Success Criteria

- ✅ docker-compose.yml working end-to-end
- ✅ Container starts and serves API correctly
- ✅ Volumes persist data across restarts
- ✅ Architecture documentation for v3.4+
- ✅ All features documented

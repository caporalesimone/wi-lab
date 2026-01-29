# Wi-Lab Development Roadmap

## Overview

This document outlines the development roadmap for Wi-Lab with focus on the next 3 major releases (v1.1.0 → v1.3.0), followed by a prioritized backlog of additional features.

Each feature is fully detailed in dedicated markdown files in the `TODOs/` directory.

---

## 🎯 Next Planned Releases

| Version | Feature | File | Description |
|---------|---------|------|-------------|
| v1.2.0 | API Simplification | [api-simplification.md](TODOs/api-simplification.md) | Streamline API complexity by consolidating overlapping endpoints. Reduces network endpoints from 3 to 2. |
| v1.3.0 | Traffic Statistics | [traffic-statistics.md](TODOs/traffic-statistics.md) | Real-time traffic statistics collection (TX/RX bytes, packets, errors) for network monitoring. |
| v1.4.0 | Link Quality Simulation | [link-quality-simulation.md](TODOs/link-quality-simulation.md) | Simulate poor network conditions (packet loss, latency) using Linux `tc` for safe, reproducible testing. |
| v1.5.0 | Device Busy Reservation | [device-busy-reservation.md](TODOs/device-busy-reservation.md) | Exclusive network reservation with timer-based automatic release. Prevents concurrent access with countdown UI. |

---

## 📚 Future Ideas

| Feature | File | Description |
|---------|------|-------------|
| Startup Recovery | [startup-recovery.md](TODOs/startup-recovery.md) | Auto-cleanup orphaned processes and iptables rules on crash |
| Graceful Shutdown | [graceful-shutdown.md](TODOs/graceful-shutdown.md) | SIGTERM handling and DHCP subnet collision detection |
| Per-Client Controls | [client-controls.md](TODOs/client-controls.md) | Per-MAC blocking and rate limiting for individual clients |
| Real-Time Events | [realtime-events.md](TODOs/realtime-events.md) | SSE streaming for network activity and client events |
| Python SDK & CLI | [python-sdk-cli.md](TODOs/python-sdk-cli.md) | Official Python library and command-line tool |
| Enterprise Features | [enterprise-features.md](TODOs/enterprise-features.md) | Docker Compose support and regulatory domain configuration |

---
---
global_sync_id: "v2"
---

# Flying Circus Operator’s Manual

**Welcome to the Flying Circus documentation.** This guide covers the platform architecture, application deployment instructions, and reference documentation for the NixOS-based cloud platform, all managed components (roles), and all associated infrastructure services.

---

## Documentation Overview

Explore our core guides, infrastructure concepts, and self-service capabilities:

| Topic | Highlights & Quick Links |
| :--- | :--- |
| **🚀 Getting Started** | [First Steps & Tutorial](./infrastructure/getting-started.md) · [Application Deployments](./platform/deployment/index.md) · [User Accounts & SSH](./platform/users/index.md) |
| **⚙️ Infrastructure & Core** | [Virtual Machines](./infrastructure/vms.md) · [Dual-Interface Networking](./infrastructure/networking/index.md) · [Block Storage](./infrastructure/block-storage.md) · [Backups](./infrastructure/backup.md) |
| **☁️ Self-Service** | [S3-Compatible Object Storage](./infrastructure/object-storage.md) · [AI & Machine Learning (LLM-API, Open WebUI etc.)](./infrastructure/ai-ml.md) · [Portal (my.flyingcircus.io)](https://my.flyingcircus.io){:target="_blank"} |
| **📦 Managed Components** | Ready-to-use environments for PostgreSQL, MariaDB, MySQL, Kubernetes (k3s), NGINX, Redis, OpenSearch, and more. |

---

## Platform Editions & Releases

Our **supported release window** covers three versions aligned with NixOS upstream:

+ **Stable:** The latest official NixOS release. For detailed migration paths and release history, see the **[Platform What's new and Upgrades](./platform/upgrades-whats-new.md)**.

+ **Sunsetting:** The two prior releases without upstream support, maintained as an extended grace period for upgrades.

> **Tip:** Use the **version selector in the top-right navigation** to switch to the documentation matching your deployed release.

---

## Support & Operations

**Need help with your setup or running into an issue?** Whether it's a general question, daily project chat via Matrix, or an urgent production incident, find all contact channels, SLA response times, and emergency hotline details in our **[Support Guide](./support/overview.md)**.

* **Ticket Support:** Email [support@flyingcircus.io](mailto:support@flyingcircus.io)
* **Phone Support:** +49 345 219401-0
* **System Status:** Live incidents and scheduled maintenance at [status.flyingcircus.io](https://status.flyingcircus.io){:target="_blank"}
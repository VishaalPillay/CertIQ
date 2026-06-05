# AZ-900 Azure Fundamentals — Contoso Internal Study Guide

> **Audience:** Contoso engineers preparing for the Microsoft AZ-900 certification exam.
> **Last Updated:** June 2026

---

## Cloud Concepts

### What Is Cloud Computing?

Cloud computing is the delivery of computing services — including servers, storage, databases, networking, software, analytics, and intelligence — over the internet ("the cloud") to offer faster innovation, flexible resources, and economies of scale. Instead of owning and maintaining physical datacenters and servers, you rent access to everything from applications to storage from a cloud provider like Microsoft Azure.

### Shared Responsibility Model

The Shared Responsibility Model defines which security tasks are handled by the cloud provider (Microsoft) and which remain with the customer. Understanding this model is critical for the exam and for real-world architecture decisions.

**How responsibility shifts by service type:**

| Responsibility Area | IaaS | PaaS | SaaS |
|---|---|---|---|
| Physical datacenter security | Microsoft | Microsoft | Microsoft |
| Physical network | Microsoft | Microsoft | Microsoft |
| Physical hosts | Microsoft | Microsoft | Microsoft |
| Operating system | **Customer** | Microsoft | Microsoft |
| Network controls | **Customer** | Shared | Microsoft |
| Application | **Customer** | **Customer** | Microsoft |
| Identity & directory infrastructure | **Customer** | Shared | Shared |
| Data | **Customer** | **Customer** | **Customer** |
| Devices & accounts | **Customer** | **Customer** | **Customer** |

**Concrete examples:**
- **IaaS (e.g., Azure VMs):** Microsoft secures the physical host and datacenter. You are responsible for patching the OS, configuring firewall rules, and encrypting your data.
- **PaaS (e.g., Azure App Service):** Microsoft manages the OS and runtime. You are responsible for your application code and data, but network controls are shared — Microsoft manages the underlying network fabric while you configure access restrictions.
- **SaaS (e.g., Microsoft 365):** Microsoft manages nearly everything. You are still responsible for your data, the devices you connect from, and the accounts and identities you use to access the service.

> **Exam Trap:** The customer is ALWAYS responsible for data, devices, and accounts — regardless of the cloud service type. This is a frequently tested concept.

### Cloud Deployment Models

| Model | Description | Use Case |
|---|---|---|
| **Public Cloud** | Resources owned and operated by a third-party provider, delivered over the public internet. | Contoso's web applications, dev/test environments, SaaS products. |
| **Private Cloud** | Cloud infrastructure operated solely for a single organization, on-premises or hosted. | Contoso's legacy financial systems with strict regulatory requirements. |
| **Hybrid Cloud** | Combines public and private clouds, allowing data and applications to be shared between them. | Contoso keeps sensitive patient data on-premises but bursts analytics workloads to Azure during peak periods. |

### Key Benefits of Cloud Computing

- **High Availability (HA):** Cloud providers offer SLAs guaranteeing uptime (e.g., 99.99% for certain Azure services). Systems remain operational even during component failures through redundancy and failover mechanisms.
- **Scalability:** The ability to adjust resources to meet demand.
  - *Vertical scaling (scale up/down):* Increasing or decreasing the capabilities of a single resource, e.g., upgrading a VM from 4 vCPUs to 16 vCPUs.
  - *Horizontal scaling (scale out/in):* Adding or removing instances of a resource, e.g., adding more VMs behind a load balancer.
- **Elasticity:** The ability to automatically scale resources in real-time based on demand. For example, Azure Virtual Machine Scale Sets can add VM instances during a traffic spike and remove them when traffic drops — you only pay for what you use.
- **Agility:** The ability to rapidly deploy and configure cloud-based resources as requirements change. Provisioning a new environment in Azure takes minutes, not weeks.
- **Disaster Recovery:** Cloud-based backup services, data replication, and geo-distribution ensure business continuity. Azure Site Recovery can replicate workloads across regions.

### CapEx vs OpEx

| | Capital Expenditure (CapEx) | Operational Expenditure (OpEx) |
|---|---|---|
| **Definition** | Upfront spending on physical infrastructure. | Spending on services or products as needed (pay-as-you-go). |
| **Example** | Contoso buys a $500,000 server rack for the on-premises datacenter. | Contoso pays $2,000/month for Azure VMs that host the same workload. |
| **Accounting** | Depreciated over useful life (3–5 years). | Fully expensed in the billing period. |
| **Flexibility** | Low — committed upfront. | High — scale up or down as needed. |

### Consumption-Based Pricing

Cloud computing uses a consumption-based model: you pay only for the resources you actually use. There are no upfront costs for infrastructure you might not fully utilize. If demand drops, your costs drop. This model eliminates the risk of over-provisioning and under-utilization that is common with on-premises infrastructure. Azure meters track resource usage and bills are generated based on actual consumption.

---

## Core Azure Architecture

### Physical Infrastructure

**Datacenters:** Azure datacenters are physical facilities with dedicated power, cooling, and networking. They are organized into Azure regions and are not directly accessible to users.

**Regions:** A region is a geographical area containing one or more datacenters that are networked together with a low-latency network. Examples include **East US**, **West Europe**, **Central India**, **Japan East**, and **Brazil South**. When deploying resources, you choose a region based on proximity to users, compliance requirements, and service availability.

> **Exam Trap:** Not all Azure services are available in all regions. Always verify regional availability before architecting a solution.

**Region Pairs:** Each Azure region is paired with another region within the same geography, at least **300 miles apart**. The 300-mile separation rule ensures that a large-scale disaster (natural disaster, power grid failure) is unlikely to affect both regions simultaneously. Benefits of region pairs include:
- During planned Azure maintenance, updates are rolled out to one region in a pair at a time to minimize downtime.
- In a broad outage, recovery of one region in every pair is prioritized.
- Data residency is maintained within the same geography for compliance.

Example pairs: East US ↔ West US, North Europe ↔ West Europe, Central India ↔ South India.

**Availability Zones:** Availability Zones are physically separate locations within an Azure region. Each zone has independent power, cooling, and networking. A region that supports Availability Zones has a minimum of three separate zones. If one zone experiences a failure (e.g., a cooling system outage), the other zones continue operating. You can deploy resources across zones to achieve high availability — for instance, placing VMs in Zone 1, Zone 2, and Zone 3 behind a load balancer.

> **Exam Trap:** Availability Zones are NOT available in all Azure regions. Some regions consist of a single datacenter and do not support zonal deployment.

**Sovereign Clouds:** Isolated Azure instances that operate independently from the main Azure cloud:
- **Azure Government:** Physically isolated datacenters and networks in the US, accessible only to screened US government agencies and their partners. Meets US government security and compliance requirements (FedRAMP, ITAR, CJIS).
- **Azure China (21Vianet):** Operated by 21Vianet, a Chinese provider, to comply with Chinese regulations. Microsoft does not directly operate these datacenters.

### Management Infrastructure

**Resources:** A resource is the basic building block in Azure — anything you create, provision, or deploy. Examples: a VM, a storage account, a virtual network, a database.

**Resource Groups (RGs):** A logical container for resources. Rules:
- Every Azure resource must belong to exactly **one** resource group.
- A resource group can contain resources from **multiple different regions** (the RG itself has a region for metadata, but its resources can be anywhere).
- Resource groups **cannot be nested** inside other resource groups.
- Deleting an RG deletes **all resources** within it — use this with caution.
- Actions (like access controls or policies) applied to an RG apply to all resources inside it.

**Subscriptions:** A subscription is both a **billing boundary** and an **access control boundary**.
- *Billing boundary:* Separate subscriptions generate separate billing reports and invoices. Contoso might have one subscription for Development and another for Production to track costs independently.
- *Access control boundary:* Azure applies access-management policies at the subscription level. Different departments can have different subscription-level policies.

**Management Groups:** Containers that help you manage access, policy, and compliance across **multiple subscriptions**. Management groups can be nested (up to six levels deep, excluding the root and subscription levels). Policies and RBAC assignments applied to a management group are **inherited** by all child management groups and subscriptions.

**Hierarchy Diagram:**

```
Tenant Root Management Group
├── Management Group: "Contoso IT"
│   ├── Subscription: "Production"
│   │   ├── Resource Group: "rg-web-prod"
│   │   │   ├── App Service
│   │   │   ├── SQL Database
│   │   │   └── Storage Account
│   │   └── Resource Group: "rg-network-prod"
│   │       ├── Virtual Network
│   │       └── Network Security Group
│   └── Subscription: "Development"
│       └── Resource Group: "rg-dev-team"
│           ├── VM (Dev Server)
│           └── Storage Account
└── Management Group: "Contoso Finance"
    └── Subscription: "Finance-Prod"
        └── Resource Group: "rg-finance"
            └── SQL Database
```

---

## Core Azure Services

### Compute Services

| Service | Type | Best For |
|---|---|---|
| **Azure Virtual Machines** | IaaS | Full OS control, lift-and-shift migrations, custom software. |
| **Azure Container Instances (ACI)** | Serverless containers | Running isolated containers quickly without managing infrastructure. No orchestration needed. |
| **Azure Kubernetes Service (AKS)** | Managed Kubernetes | Complex containerized applications requiring orchestration, scaling, and service discovery at scale. |
| **Azure App Service** | PaaS | Web apps, REST APIs, mobile backends. Supports .NET, Java, Node.js, Python, PHP. No infrastructure management. |
| **Azure Functions** | Serverless compute | Event-driven, short-lived code execution. Pay only for execution time. Ideal for processing queue messages, HTTP triggers, scheduled tasks. |

**When to use which:**
- Need full control over the OS? → **VMs**.
- Running a single container for a quick job? → **ACI**.
- Orchestrating dozens of microservices in containers? → **AKS**.
- Building a web application and want zero infrastructure management? → **App Service**.
- Running code only in response to events, with no idle cost? → **Azure Functions**.

> **Exam Trap:** Azure Functions is consumption-based by default — you are billed per execution and execution time, not for idle capacity. App Service, by contrast, bills for the App Service Plan even if no requests are being processed.

### Networking Services

- **Virtual Network (VNet):** The fundamental building block for private networks in Azure. VNets enable Azure resources to communicate with each other, the internet, and on-premises networks securely. VNets are scoped to a single region but can be connected across regions using VNet peering.
- **Subnets:** Segments within a VNet that allow you to organize and secure resources. Each subnet has its own address range within the VNet.
- **Network Security Groups (NSGs):** Contain security rules that allow or deny inbound and outbound network traffic. NSGs can be associated with subnets or individual network interfaces. Rules are evaluated by priority (lower number = higher priority).
- **VPN Gateway:** Connects Azure VNets to on-premises networks over an encrypted tunnel across the **public internet**. Supports Site-to-Site, Point-to-Site, and VNet-to-VNet connections.
- **Azure ExpressRoute:** Provides a **private connection** between on-premises infrastructure and Azure that does **not** traverse the public internet. Offers higher reliability, faster speeds, consistent latencies, and higher security than typical internet connections.

> **Exam Trap:** The key difference between VPN Gateway and ExpressRoute — VPN Gateway uses the public internet (encrypted); ExpressRoute uses a dedicated private connection. ExpressRoute is more expensive but offers better performance and reliability.

### Storage Services

| Service | Type | Use Case |
|---|---|---|
| **Blob Storage** | Unstructured (object) | Images, videos, backups, logs, data lakes. Supports Hot, Cool, Cold, and Archive access tiers. |
| **Azure Files** | File shares (SMB/NFS) | Shared file storage accessible from cloud or on-premises via SMB 3.0 or NFS protocols. Can replace or extend on-premises file servers. |
| **Queue Storage** | Messaging | Asynchronous message processing between application components. Each message can be up to 64 KB. |
| **Disk Storage** | Block storage | Managed disks for Azure VMs. Available in Ultra, Premium SSD, Standard SSD, and Standard HDD tiers. |
| **Table Storage** | NoSQL key-value | Storing large amounts of structured, non-relational data. Schemaless design for rapid development. |

### Storage Redundancy Options

| Option | Description | Durability |
|---|---|---|
| **LRS (Locally Redundant Storage)** | Replicates data 3 times within a single datacenter in one region. | Protects against server rack and drive failures. Not protected against datacenter-level disaster. |
| **ZRS (Zone-Redundant Storage)** | Replicates data across 3 Availability Zones in one region. | Protects against zone-level failures. Recommended for high-availability scenarios. |
| **GRS (Geo-Redundant Storage)** | Replicates data 3 times in the primary region (LRS) and 3 times in a paired secondary region. | Protects against regional outages. Secondary data is not readable unless failover occurs. |
| **RA-GRS (Read-Access Geo-Redundant Storage)** | Same as GRS but provides **read access** to the secondary region at all times. | Ideal for applications that need read availability even during a regional outage. |

> **Exam Trap:** With standard GRS, you cannot read from the secondary region until a failover is initiated. If you need constant read access to the replica, choose RA-GRS. Also note: GZRS and RA-GZRS exist as combinations of ZRS + geo-redundancy.

---

## Azure Governance, Management, and Cost

### Cost Management Tools

- **TCO (Total Cost of Ownership) Calculator:** Estimates the cost savings you can realize by migrating workloads to Azure. You input your current on-premises infrastructure details (servers, storage, networking, labor costs) and it compares the projected Azure cost over 1–5 years. Used for migration planning, **not** for pricing individual Azure services.
- **Azure Pricing Calculator:** Estimates the monthly cost of specific Azure services. You configure products (VMs, storage accounts, databases) with desired specifications and it generates an estimate. Used for planning new Azure deployments.
- **Azure Cost Management + Billing:** A built-in Azure tool for monitoring, allocating, and optimizing cloud spending. Features include cost analysis dashboards, custom views, forecast projections, and the ability to export cost data.
- **Cost Alerts and Budgets:** You can set budget thresholds (e.g., $10,000/month for the Production subscription) and configure alerts at percentage thresholds (50%, 80%, 100%). Alerts are sent via email and can trigger action groups for automation.

> **Exam Trap:** The TCO Calculator and Pricing Calculator serve different purposes. TCO compares on-premises vs. Azure costs for migration justification. The Pricing Calculator estimates costs for specific Azure resources you plan to deploy.

### Governance Tools

- **Azure Policy:** A service for creating, assigning, and managing policies that enforce rules over resources. Policies are **preventive** — they can deny non-compliant resource creation or audit existing resources. Example: enforce that all VMs must be deployed in the "East US" region, or require that all resources have a "CostCenter" tag.
- **RBAC (Role-Based Access Control):** Controls **who** can do **what** on **which resources**. RBAC uses role assignments that combine a security principal (user, group, service principal), a role definition (Owner, Contributor, Reader, or custom), and a scope (management group, subscription, resource group, or individual resource). RBAC is inherited down the hierarchy — a Contributor role at the subscription level grants Contributor access to all resource groups and resources within that subscription.
- **Resource Locks:** Prevent accidental modification or deletion of critical resources. Two lock types:
  - *CanNotDelete:* Authorized users can read and modify the resource but cannot delete it.
  - *ReadOnly:* Authorized users can read the resource but cannot modify or delete it (effectively making it read-only).
- **Azure Blueprints:** Enables you to define a repeatable set of governance tools and standard Azure resources that your organization requires. Blueprints can package role assignments, policy assignments, ARM templates, and resource groups into a single deployable artifact. Useful for setting up new environments that comply with organizational standards.

### Monitoring and Advisors

- **Azure Monitor:** A comprehensive monitoring service that collects, analyzes, and acts on telemetry data from Azure and on-premises environments. It includes Metrics, Logs (Log Analytics), Alerts, and Application Insights. Use it to detect and diagnose issues across applications and infrastructure.
- **Azure Advisor:** A personalized cloud consultant that provides best-practice recommendations across five categories:
  1. **Cost** — Identify underutilized resources, right-size VMs, purchase reserved instances.
  2. **Security** — Enable MFA, apply disk encryption, address vulnerability findings.
  3. **Reliability** — Enable soft delete for backups, configure Availability Zones, add health probes.
  4. **Performance** — Resize VMs for better performance, optimize database queries, use CDN.
  5. **Operational Excellence** — Configure service health alerts, apply tags, update to latest API versions.
- **Azure Service Health:** Provides personalized alerts and guidance when Azure service issues affect you. Three components:
  - *Azure Status:* Global view of the health of all Azure services across all regions.
  - *Service Health:* Focused view of the Azure services and regions you are using (tracks service issues, planned maintenance, and health advisories).
  - *Resource Health:* Information about the health of your individual Azure resources (e.g., a specific VM that is experiencing issues).

### Data Governance

- **Microsoft Purview:** A unified data governance service that helps you manage and govern on-premises, multi-cloud, and SaaS data. Provides automated data discovery, sensitive data classification, and end-to-end data lineage. Useful for organizations that need a comprehensive view of their data estate and must comply with regulations like GDPR or HIPAA.

---

> **Final Study Tips for Contoso Engineers:**
> - Focus on understanding the *why* behind each service, not just memorization.
> - Pay special attention to service comparisons — the exam frequently asks "which service should you use" scenario questions.
> - Remember the hierarchy: Management Groups → Subscriptions → Resource Groups → Resources.
> - Practice with the Azure portal — hands-on experience reinforces conceptual understanding.
> - Review the Shared Responsibility Model thoroughly; it appears in multiple question formats.

# Contoso Cloud Architecture Best Practices & Governance Manual

This document outlines the cloud best practices, architectural principles, naming conventions, and security baselines mandated for all systems deployed within Contoso's Azure environments. All teams must comply with these standards before any workload is promoted to production.

---

## 1. Microsoft Azure Well-Architected Framework (WAF)

All cloud resources deployed at Contoso must align with the five pillars of the Azure Well-Architected Framework. Each pillar is summarized below with concrete implementation requirements.

### Reliability

Reliability ensures your application can meet the commitments you make to your customers. High availability and fault tolerance should be designed into every component from day one.

- **Redundancy**: Deploy multi-region architectures for critical user-facing applications. Use Availability Zones within a region to protect against datacenter failures. For storage, use at minimum Zone-Redundant Storage (ZRS) for production workloads and Read-Access Geo-Redundant Storage (RA-GRS) for critical business data that must survive a full region outage.
- **Failover**: Implement auto-failover groups for databases (e.g., Azure SQL auto-failover groups, Cosmos DB multi-region writes). Define Recovery Time Objective (RTO) and Recovery Point Objective (RPO) targets for each application tier. Tier-1 applications must have an RTO of less than 15 minutes and RPO of less than 5 minutes.
- **Health Probes**: Configure health endpoints on all App Service and VM-based workloads. Azure Load Balancer and Application Gateway should probe these endpoints every 15 seconds. If a backend becomes unhealthy, traffic must be automatically rerouted within 30 seconds.
- **Chaos Engineering**: Teams are encouraged to run controlled failure injection tests using Azure Chaos Studio at least once per quarter. Document the results and update runbooks accordingly.

### Security

Security protects your data, applications, and infrastructure from threats. Contoso follows a defense-in-depth approach with multiple layers of protection.

- **Identity Boundary**: All authentication must go through Microsoft Entra ID. No application may implement its own username/password authentication system. Enforce the principle of least privilege using Azure RBAC at the resource group level rather than at the individual resource level. Use Privileged Identity Management (PIM) for any role that can modify production infrastructure.
- **Network Isolation**: All backend services (databases, caches, message queues) must be placed on private subnets and accessed exclusively via Private Endpoints. No database server should have a public IP address in production. Use Network Security Groups (NSGs) with explicit deny rules as the last rule in each NSG. Enable Azure DDoS Protection Standard on production virtual networks.
- **Data Encryption**: All data must be encrypted at rest using Azure Storage Service Encryption (SSE) with platform-managed keys as a minimum. Tier-1 applications must use Customer-Managed Keys (CMK) stored in Azure Key Vault. All data in transit must use TLS 1.2 or higher. TLS 1.0 and 1.1 must be explicitly disabled on all web-facing endpoints.
- **Secrets Management**: No credential, connection string, API key, or certificate may appear in source code, environment variables baked into container images, or configuration files committed to version control. All secrets must be stored in Azure Key Vault and accessed at runtime via Managed Identity.

### Cost Optimization

Cost optimization focuses on avoiding unnecessary expenses and maximizing cloud efficiency without sacrificing performance or reliability.

- **Right-Sizing**: Review Azure Advisor recommendations weekly. Downsize or deallocate VMs that consistently run below 20% CPU utilization. Use Azure Monitor metrics to justify sizing decisions. For non-production environments, implement auto-shutdown schedules (e.g., shut down dev/test VMs at 20:00 IST and restart at 08:00 IST).
- **Reserved Instances**: For workloads with predictable usage (production databases, always-on app services), purchase 1-year or 3-year Reserved Instances. This typically saves 30-60% compared to pay-as-you-go pricing. All reserved instance purchases must be approved by the Cloud Engineering lead.
- **Lifecycle Management**: Implement Blob Storage lifecycle policies to automatically transition data from Hot to Cool tier after 30 days and from Cool to Archive after 90 days. Configure expiration rules to delete temporary/diagnostic data after 180 days.
- **Spot VMs**: Use Azure Spot VMs for batch processing, CI/CD build agents, and any workload that can tolerate interruption. Spot VMs offer up to 90% discount compared to on-demand pricing.

### Operational Excellence

Operational excellence focuses on running and monitoring systems in production with predictable, repeatable outcomes.

- **Infrastructure as Code (IaC)**: All Azure resources must be deployed via Bicep templates or Terraform configurations stored in version control. Manual portal changes are prohibited in production and staging environments. Every IaC module must include a README documenting input parameters, outputs, and example usage.
- **CI/CD**: All deployments to staging and production must go through Azure DevOps Pipelines or GitHub Actions. Direct deployments via Azure CLI or Portal are prohibited. Pipelines must include automated tests (unit, integration) and a manual approval gate before production promotion.
- **Monitoring and Alerting**: All applications must integrate Application Insights for distributed tracing and performance monitoring. Diagnostic logs from all Azure resources must be forwarded to a central Log Analytics Workspace. Define alert rules for key metrics (response time > 2 seconds, error rate > 1%, CPU > 80% sustained for 10 minutes). On-call engineers must acknowledge critical alerts within 15 minutes.

### Performance Efficiency

Performance efficiency is the ability of your workload to scale to meet demands placed on it by users in an efficient manner.

- **Autoscale**: Configure autoscale rules on Virtual Machine Scale Sets and App Service plans based on CPU and memory thresholds. Scale-out should trigger when CPU exceeds 70% for 5 minutes. Scale-in should trigger when CPU drops below 30% for 10 minutes. Always set minimum and maximum instance counts to prevent runaway scaling.
- **Caching**: Integrate Azure Cache for Redis to offload read-heavy operations from transactional databases. Cache frequently accessed reference data (certification catalogs, org hierarchies) with a TTL of 5 minutes. Use the Cache-Aside pattern: check cache first, query the database on a miss, populate the cache for subsequent reads.
- **CDN**: Serve static assets (JavaScript bundles, CSS, images) through Azure CDN. Configure cache expiration headers at the application level. Use CDN purge operations when deploying new frontend versions.

---

## 2. Resource Naming Conventions

Consistent resource naming is critical for management, billing, and security. Contoso enforces a structured naming pattern for all Azure resources:

**Pattern**: `[company]-[env]-[region]-[service-prefix]-[app-name]-[id]`

### Standard Prefix List

| Service Type | Prefix | Example Name |
|---|---|---|
| Resource Group | `rg` | `ct-prod-cin-rg-billing` |
| Virtual Network | `vnet` | `ct-prod-cin-vnet-crm-01` |
| Subnet | `snet` | `ct-prod-cin-snet-db-01` |
| Network Security Group | `nsg` | `ct-prod-cin-nsg-web-01` |
| Key Vault | `kv` | `ct-prod-cin-kv-secrets-01` |
| SQL Database | `sqldb` | `ct-prod-cin-sqldb-orders` |
| App Service Plan | `plan` | `ct-prod-cin-plan-api-01` |
| App Service Web App | `app` | `ct-prod-cin-app-portal` |
| Function App | `func` | `ct-prod-cin-func-notifications` |
| Storage Account | `st` | `ctprodcinstorders01` |
| Cosmos DB Account | `cosmos` | `ct-prod-cin-cosmos-analytics` |
| Redis Cache | `redis` | `ct-prod-cin-redis-session` |
| Service Bus | `sb` | `ct-prod-cin-sb-events` |

### Environment Identifiers

| Code | Meaning | Allowed Operations |
|---|---|---|
| `prod` | Production | IaC deployments only, manual changes prohibited |
| `stage` | Staging / UAT | IaC deployments, limited manual debugging |
| `dev` | Development | IaC preferred, manual changes tolerated |
| `test` | Testing / QA | IaC preferred, manual changes tolerated |

### Region Codes

| Code | Azure Region |
|---|---|
| `cin` | Central India |
| `sin` | South India |
| `eus` | East US |
| `weu` | West Europe |

> **Exam Tip**: Storage account names in Azure must be globally unique, 3-24 characters, lowercase letters and numbers only (no hyphens). This is why storage accounts use a compressed naming pattern without hyphens.

---

## 3. Resource Tagging Strategy

Tags are key-value pairs applied to resources to categorize them for billing, operations, and security. The following tags are **mandatory** on all resource groups and their child resources:

| Tag Key | Purpose | Allowed Values | Example |
|---|---|---|---|
| `Owner` | Technical owner's email | Valid Contoso email | `priya.sharma@contoso.com` |
| `Department` | Department responsible for billing | `CloudEngineering`, `Security`, `DataPlatform`, `DevOps` | `CloudEngineering` |
| `Environment` | Stage of the resource lifecycle | `prod`, `stage`, `dev`, `test` | `prod` |
| `CostCenter` | Cost center code for finance | Alphanumeric code | `CC-ENG-998` |
| `Criticality` | Business impact level | `Tier-1`, `Tier-2`, `Tier-3` | `Tier-1` |
| `Project` | Project or application name | Free text | `CertIQ` |
| `ManagedBy` | IaC tool managing the resource | `Bicep`, `Terraform`, `Manual` | `Bicep` |

**Tag Enforcement**: An Azure Policy assignment at the management group level denies resource group creation if `Owner`, `Department`, `Environment`, and `CostCenter` tags are missing. Resources inherit tags from their parent resource group via a tag inheritance policy.

**Cost Reporting**: Finance generates monthly cost reports grouped by `Department` and `CostCenter` tags. Untagged resources are flagged in the weekly Cloud Governance review meeting and must be remediated within 5 business days.

---

## 4. Security & Compliance Baseline

All Contoso development teams must implement the following security configurations as non-negotiable requirements.

### Key Vault Integration

- All keys, secrets, connection strings, and certificates must be stored in Azure Key Vault. Referencing secrets directly from App Service configuration (using `@Microsoft.KeyVault(SecretUri=...)` syntax) is the preferred pattern.
- Enable **soft-delete** (default retention: 90 days) and **purge protection** on all Key Vaults. This prevents accidental or malicious permanent deletion of secrets.
- Set up Key Vault firewall rules to restrict access to authorized IP ranges and VNets. Enable Key Vault logging to a Log Analytics workspace for audit trails.
- Rotate secrets at least every 90 days. Use Key Vault's built-in rotation policies where supported (e.g., storage account keys).

### Managed Identities

- Disable local authentication and key-based access where possible. For example, Azure Storage accounts should have `AllowSharedKeyAccess` set to `false` in production, forcing all access through Entra ID and RBAC.
- Web apps and Function apps must use System-Assigned Managed Identity to access downstream services (Key Vault, Storage, SQL, Cosmos DB). User-Assigned Managed Identity should be used when the same identity needs to be shared across multiple resources.
- Never hardcode `DefaultEndpointsProtocol=https;AccountName=...;AccountKey=...` connection strings in code. Instead, use `DefaultAzureCredential()` which automatically discovers the Managed Identity in Azure and developer credentials locally.

### Compliance Scanning

- Enable Microsoft Defender for Cloud on all subscriptions. Ensure the Secure Score stays above 80%. Address any "High" severity recommendations within 48 hours.
- Run Azure Policy compliance scans daily. Non-compliant resources in production trigger an automatic incident ticket assigned to the resource owner.
- Enable diagnostic settings on all Azure resources to send platform logs and metrics to the central Log Analytics workspace for compliance auditing and incident investigation.

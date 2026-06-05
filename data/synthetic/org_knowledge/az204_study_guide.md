# AZ-204: Developing Solutions for Microsoft Azure — Internal Study Guide

> **Audience:** Contoso engineers preparing for the AZ-204 certification exam.
> **Last Updated:** June 2026
> **Maintainer:** Cloud Engineering Guild

This guide covers the eight core domains tested on the AZ-204 exam. Each section includes Azure CLI commands, code examples, common exam traps, and practical deployment advice drawn from Contoso's production experience.

---

## Azure App Service

Azure App Service is a fully managed platform for building, deploying, and scaling web applications, REST APIs, and mobile back-ends. It supports .NET, Java, Node.js, Python, and PHP. Understanding App Service deeply is critical for the AZ-204 exam because Microsoft tests nuanced configuration behavior, not just high-level concepts.

### Deployment Slots and Swap Behavior

Deployment slots are live instances of your app with their own hostnames. The Standard, Premium, and Isolated tiers support multiple slots. When you swap slots, Azure performs a **warm-up** by sending an HTTP request to the root of the destination slot before completing the swap. This ensures zero-downtime deployments.

During a swap, the **target slot's app settings and connection strings are applied to the source slot's code** before the swap completes. This is the most commonly misunderstood behavior on the exam. The swap operation does not move settings — it moves code to the slot that already has the production settings. If the warm-up fails (returns a non-200 status code), the swap is aborted.

**Slot-specific (sticky) settings** remain with the slot and do not move during a swap. Mark a setting as slot-specific when it should differ between staging and production — for example, a database connection string pointing to a staging database. Settings that are NOT marked as slot-specific travel with the code during a swap.

**Auto-swap** automatically swaps a staging slot into production whenever code is deployed to that slot. Enable it in the slot's configuration. Auto-swap is supported on Windows App Service plans but is not available on Linux consumption plans. Auto-swap eliminates the manual approval step, which is useful for continuous deployment pipelines but risky for production workloads that need manual verification.

```bash
# Create a deployment slot named "staging"
az webapp deployment slot create --name myapp --resource-group myRG --slot staging

# Swap staging into production
az webapp deployment slot swap --name myapp --resource-group myRG --slot staging --target-slot production

# Configure auto-swap on the staging slot
az webapp config set --name myapp --resource-group myRG --slot staging --auto-swap-slot-name production
```

### App Settings vs Connection Strings

App settings are key-value pairs injected as environment variables at runtime. Connection strings are also key-value pairs, but they are typed (SQLServer, MySQL, PostgreSQL, Custom) and are exposed differently depending on the platform. On .NET, connection strings are injected into `ConfigurationManager.ConnectionStrings`, while app settings go into `ConfigurationManager.AppSettings`. On non-.NET platforms, both are exposed as environment variables, but connection strings get a prefix based on their type (e.g., `SQLCONNSTR_`, `MYSQLCONNSTR_`, `CUSTOMCONNSTR_`).

**Exam tip:** If a question asks how to store a connection string that should stay with the slot (not swap), you need both to add it as a connection string AND mark it as slot-specific. Simply adding it as a connection string does not make it sticky.

```bash
# Set an app setting
az webapp config appsettings set --name myapp --resource-group myRG --settings MY_KEY=my_value

# Set a connection string (type: SQLServer)
az webapp config connection-string set --name myapp --resource-group myRG \
  --connection-string-type SQLServer \
  --settings DefaultConnection="Server=tcp:myserver.database.windows.net;Database=mydb;"

# Mark a setting as slot-specific
az webapp config appsettings set --name myapp --resource-group myRG --slot-settings SLOT_SPECIFIC_KEY=value
```

### Scaling: Manual vs Autoscale

Manual scaling sets a fixed instance count. Autoscale uses rules based on metrics (CPU percentage, memory percentage, HTTP queue length, custom metrics) to scale out or scale in. Autoscale rules have a **cool-down period** (default 5 minutes) that prevents flapping. Always configure both a scale-out and a scale-in rule — if you only define scale-out, instances will never be reclaimed.

Autoscale operates on the App Service Plan, not individual apps. All apps in the same plan share the same instances. This means a noisy app can impact other apps in the same plan.

**Exam gotcha:** Autoscale based on CPU percentage uses the **average** across all instances, not the maximum. If you have 4 instances and one is at 100% CPU while the others are idle, the average is 25%, which may not trigger a scale-out rule set at 70%.

```bash
# Scale manually to 3 instances
az appservice plan update --name myPlan --resource-group myRG --number-of-workers 3
```

### Custom Domains and SSL

To add a custom domain, you must verify ownership via a CNAME or TXT record. For SSL, you can use an App Service Managed Certificate (free, auto-renewed, but only for standard domains — no wildcard support), or upload your own certificate. SSL bindings come in two types: **SNI SSL** (recommended, uses Server Name Indication) and **IP-based SSL** (assigns a dedicated IP, required for legacy clients that don't support SNI).

```bash
# Add a custom domain
az webapp config hostname add --webapp-name myapp --resource-group myRG --hostname www.contoso.com

# Upload and bind an SSL certificate
az webapp config ssl upload --name myapp --resource-group myRG --certificate-file cert.pfx --certificate-password pwd123
az webapp config ssl bind --name myapp --resource-group myRG --certificate-thumbprint <thumbprint> --ssl-type SNI
```

**Practical advice:** Always use slot-specific settings for connection strings in staging slots to avoid accidentally pointing staging code at production databases after a swap.

---

## Azure Functions

Azure Functions is the serverless compute service on Azure. Functions execute code in response to triggers and can connect to external services via bindings. The exam tests trigger types, binding directions, Durable Functions patterns, and cold start behavior extensively.

### Triggers and Bindings

Every function has exactly **one trigger**. Triggers cause a function to run. Bindings are declarative connections to data sources; they can be **input** (read data into the function) or **output** (write data from the function). You configure bindings in `function.json` or via attributes in C#.

| Trigger Type | Description | Common Binding Direction |
|---|---|---|
| HTTP | REST API endpoint | Trigger + Output |
| Timer | CRON schedule | Trigger only |
| Blob Storage | New/modified blob | Trigger + Input + Output |
| Queue Storage | New queue message | Trigger + Output |
| Cosmos DB | Change feed | Trigger + Input + Output |
| Event Grid | Event subscription | Trigger only |
| Service Bus | Queue/topic message | Trigger + Output |

**Timer trigger** uses NCRONTAB expressions with six fields (second, minute, hour, day, month, day-of-week). For example, `0 */5 * * * *` runs every 5 minutes. The sixth field (seconds) is what distinguishes NCRONTAB from standard CRON.

```csharp
// C# Queue-triggered function with Blob output binding
[FunctionName("ProcessOrder")]
public static async Task Run(
    [QueueTrigger("orders", Connection = "StorageConnection")] string orderJson,
    [Blob("processed/{rand-guid}.json", FileAccess.Write, Connection = "StorageConnection")] Stream outputBlob,
    ILogger log)
{
    log.LogInformation($"Processing order: {orderJson}");
    var bytes = Encoding.UTF8.GetBytes(orderJson);
    await outputBlob.WriteAsync(bytes, 0, bytes.Length);
}
```

### Durable Functions Patterns

Durable Functions extend Azure Functions with stateful orchestrations. The exam frequently tests these five patterns:

1. **Function Chaining** — Activities execute sequentially, each passing output to the next. Use `CallActivityAsync` in the orchestrator.
2. **Fan-Out/Fan-In** — Launch multiple activities in parallel with `Task.WhenAll`. The orchestrator waits for all to complete before continuing. This is the most common pattern for batch processing.
3. **Async HTTP API** — The orchestration is started by an HTTP call and polled for status. The Durable Functions runtime provides built-in status query endpoints (`/runtime/webhooks/durableTask/instances/{instanceId}`).
4. **Monitor** — A polling loop inside the orchestrator that checks a condition periodically using `CreateTimer`. The orchestrator sleeps between checks without consuming resources.
5. **Human Interaction** — The orchestrator waits for an external event (`WaitForExternalEvent`) such as a manager approval. Combine with a timer for timeout handling.

**Orchestrator constraints:** Orchestrator functions must be **deterministic**. They are replayed from history, so you must not use `DateTime.Now` (use `CurrentUtcDateTime` from the context), `Guid.NewGuid()` (use `NewGuid()` from the context), random numbers, or I/O operations directly. All I/O must happen inside activity functions.

```csharp
// Durable Functions — Fan-Out/Fan-In pattern
[FunctionName("FanOutFanIn")]
public static async Task<int[]> RunOrchestrator(
    [OrchestrationTrigger] IDurableOrchestrationContext context)
{
    var workItems = await context.CallActivityAsync<List<string>>("GetWorkItems", null);
    var tasks = workItems.Select(item => context.CallActivityAsync<int>("ProcessItem", item));
    int[] results = await Task.WhenAll(tasks);
    return results;
}
```

### Cold Start and Hosting Plans

Cold start is the latency when a function app is invoked after being idle. The **Consumption plan** has the highest cold start (can be several seconds for .NET, longer for Java). Mitigation strategies include:

- **Premium Plan** — Pre-warmed instances that are always ready. Minimum one instance is always warm. This is the recommended plan for production workloads that need low latency.
- **Always Ready instances** — Configure a minimum number of pre-warmed instances on the Premium plan.
- **Dedicated (App Service) Plan** — Functions run on always-on VMs with no cold start, but you pay for the full plan regardless of execution.

```bash
# Create a function app on the Premium plan
az functionapp create --name myFuncApp --resource-group myRG \
  --storage-account mystorageacct --plan myPremiumPlan --runtime dotnet

# List function apps in a resource group
az functionapp list --resource-group myRG --output table
```

**Exam tip:** Questions about "minimizing cold start while keeping costs low" almost always point to the Premium plan, not the Dedicated plan.

---

## Azure Blob Storage

Azure Blob Storage is object storage optimized for massive amounts of unstructured data. The exam tests access levels, tiers, SAS tokens, lifecycle policies, and immutable storage.

### Container Access Levels

When creating a blob container, you set the **public access level**:

- **Private (default)** — No anonymous access. All requests must be authenticated.
- **Blob** — Anonymous read access for individual blobs, but you cannot list blobs in the container.
- **Container** — Anonymous read access for blobs AND the ability to list all blobs in the container.

**Exam gotcha:** Even if a container is set to "Blob" access level, the storage account must also have `AllowBlobPublicAccess` enabled. If the account-level setting is disabled, container-level settings are ignored and all access is private.

### Access Tiers and Rehydration

| Tier | Storage Cost | Access Cost | Minimum Retention | Use Case |
|---|---|---|---|---|
| Hot | Highest | Lowest | None | Frequently accessed data |
| Cool | Lower | Higher | 30 days | Infrequently accessed, stored ≥30 days |
| Cold | Even Lower | Even Higher | 90 days | Rarely accessed, stored ≥90 days |
| Archive | Lowest | Highest | 180 days | Compliance, long-term backup |

**Rehydration** from Archive tier can take up to 15 hours with Standard priority or 1 hour with High priority. You cannot read a blob in the Archive tier — you must rehydrate it to Hot or Cool first. Rehydrating to Cool is cheaper than to Hot.

### Lifecycle Management Policies

Lifecycle management policies automate tier transitions and deletion. Policies are defined as JSON rules:

```json
{
  "rules": [
    {
      "name": "moveToCool",
      "type": "Lifecycle",
      "definition": {
        "actions": {
          "baseBlob": {
            "tierToCool": { "daysAfterModificationGreaterThan": 30 },
            "tierToArchive": { "daysAfterModificationGreaterThan": 180 },
            "delete": { "daysAfterModificationGreaterThan": 365 }
          }
        },
        "filters": {
          "blobTypes": ["blockBlob"],
          "prefixMatch": ["logs/"]
        }
      }
    }
  ]
}
```

### SAS Tokens

Shared Access Signatures provide granular, time-limited access to storage resources:

- **Service SAS** — Grants access to a specific service (Blob, Queue, Table, File). Signed with the storage account key.
- **Account SAS** — Grants access to one or more services and can include service-level operations. Signed with the storage account key.
- **User Delegation SAS** — Signed with Azure AD credentials instead of the account key. This is the **most secure** option and the one Microsoft recommends. It only works with Blob storage.

**Exam tip:** When a question asks for the "most secure" way to grant temporary access, the answer is always User Delegation SAS because it does not expose the storage account key.

### Immutable Storage

Immutable storage supports two policies: **legal hold** (no expiry, manually removed) and **time-based retention** (locked after a specified number of days, cannot be shortened once locked). Once a time-based retention policy is locked, it cannot be deleted or shortened. Blobs cannot be modified or deleted during the retention period.

```bash
# Create a blob container
az storage container create --name mycontainer --account-name mystorageacct --public-access off

# Upload a blob
az storage blob upload --container-name mycontainer --account-name mystorageacct \
  --name myfile.txt --file ./myfile.txt --tier Cool

# Generate a User Delegation SAS
az storage blob generate-sas --account-name mystorageacct --container-name mycontainer \
  --name myfile.txt --permissions r --expiry 2026-07-01T00:00:00Z --auth-mode login --as-user
```

---

## Azure Cosmos DB

Azure Cosmos DB is a globally distributed, multi-model database service. The AZ-204 exam heavily tests partitioning, consistency levels, Request Units, and the Change Feed. This is one of the most concept-heavy sections on the exam.

### Partitioning Strategy

Every Cosmos DB container has a **partition key** that determines how data is distributed across **logical partitions**. Each logical partition has a maximum size of **20 GB**. Multiple logical partitions are mapped to **physical partitions** managed by Cosmos DB.

Choosing a good partition key is the single most important design decision for Cosmos DB. A good key has **high cardinality** (many distinct values) and distributes read/write workloads evenly. A bad key creates **hot partitions** where one logical partition receives disproportionate traffic.

**Example:** For an e-commerce order system, `/customerId` is a good partition key if customers generate roughly equal order volumes. Using `/countryCode` would be bad because a few countries would dominate traffic. Using `/orderId` gives perfect distribution but makes queries by customer inefficient (cross-partition queries).

**Exam tip:** Cross-partition queries are expensive because they fan out to all physical partitions. Always design your partition key so that the most frequent queries include the partition key in the WHERE clause.

### Consistency Levels

Cosmos DB offers five consistency levels, from strongest to weakest:

1. **Strong** — Reads are guaranteed to return the most recent committed write. Only available in single-region accounts or multi-region with single write region. Highest latency and lowest throughput. Costs 2x RUs for reads.
2. **Bounded Staleness** — Reads may lag behind writes by at most K versions or T time interval. Provides linearizability within the staleness window. Good for scenarios requiring strong consistency with some tolerance.
3. **Session** — Default level. Within a single client session, reads reflect writes from that session (read-your-own-writes). Different sessions may see stale data. Most popular choice for web applications.
4. **Consistent Prefix** — Reads never see out-of-order writes. If writes happen in order A, B, C, a reader sees A, A-B, or A-B-C but never A-C or B-A. No staleness guarantees.
5. **Eventual** — No ordering guarantee. Reads may see out-of-order or stale data. Lowest latency and cost. Suitable for scenarios like "like" counts or non-critical telemetry.

**Exam gotcha:** Session consistency is the **default** when creating a Cosmos DB account. Strong consistency is NOT available when you have multiple write regions enabled.

### Request Units (RUs)

A Request Unit is a normalized measure of throughput. A point read (GET by ID and partition key) of a 1 KB document costs **1 RU**. Writes cost approximately **5 RUs** per 1 KB. Cross-partition queries cost significantly more.

You can provision throughput at the **database level** (shared across containers) or at the **container level** (dedicated). The minimum is 400 RU/s for a container. Autoscale allows you to set a maximum RU/s and the system scales between 10% of max and max.

```csharp
// C# — Point read by ID and partition key (1 RU for 1 KB doc)
var response = await container.ReadItemAsync<Order>(
    id: "order-123",
    partitionKey: new PartitionKey("customer-456"));
Console.WriteLine($"Request charge: {response.RequestCharge} RUs");
```

### Server-Side Programming

- **Stored Procedures** — Execute JavaScript on the server within a single logical partition. They provide ACID transactions within that partition. Stored procedures cannot span partitions.
- **Triggers** — Pre-triggers run before an operation; post-triggers run after. They must be explicitly requested in the operation.
- **UDFs (User-Defined Functions)** — Custom JavaScript functions callable from SQL queries. They are read-only and cannot modify data.

### Change Feed

The Change Feed provides a sorted list of documents in a container in the order they were modified. It does not capture deletes by default — you must implement soft-delete patterns. The **Change Feed Processor library** simplifies consumption with automatic lease management and load balancing across multiple consumers.

```csharp
// Change Feed Processor setup
var changeFeedProcessor = container
    .GetChangeFeedProcessorBuilder<Order>("orderProcessor", HandleChangesAsync)
    .WithInstanceName("consoleHost")
    .WithLeaseContainer(leaseContainer)
    .Build();
await changeFeedProcessor.StartAsync();
```

### Global Distribution

Cosmos DB supports **multi-region writes** (also called multi-master). Each region can accept writes, and conflicts are resolved using Last Writer Wins (default, based on `_ts`) or custom conflict resolution policies. Automatic failover can be enabled so that if a region goes down, another region is promoted automatically.

```bash
# Create a Cosmos DB account with Session consistency
az cosmosdb create --name mycosmosdb --resource-group myRG --default-consistency-level Session

# Add a read region
az cosmosdb update --name mycosmosdb --resource-group myRG \
  --locations regionName=eastus failoverPriority=0 \
  --locations regionName=westeurope failoverPriority=1

# Create a database with autoscale throughput
az cosmosdb sql database create --account-name mycosmosdb --resource-group myRG \
  --name ordersdb --max-throughput 4000
```

**Practical advice:** At Contoso, we use Session consistency for all customer-facing APIs and Eventual consistency for analytics pipelines. This balances cost and user experience.

---

## Azure API Management

Azure API Management (APIM) is a gateway that sits in front of your APIs, providing security, throttling, caching, and transformation. The exam tests policy configuration extensively, so you must be comfortable reading and writing XML policies.

### Policy Sections

Every APIM policy has four sections that execute in order:

1. **Inbound** — Runs when a request is received, before it reaches the backend. Use for authentication, rate limiting, request transformation.
2. **Backend** — Controls how the request is forwarded to the backend service. Use for setting backend URL, forwarding headers.
3. **Outbound** — Runs after the backend responds, before the response is sent to the client. Use for response transformation, header manipulation.
4. **On-Error** — Runs if an error occurs in any of the other sections. Use for logging, returning custom error responses.

### Policy Examples

```xml
<!-- Rate limiting: 100 calls per 60 seconds per subscription key -->
<policies>
  <inbound>
    <rate-limit calls="100" renewal-period="60" />
    <base />
  </inbound>
  <backend>
    <base />
  </backend>
  <outbound>
    <base />
  </outbound>
  <on-error>
    <base />
  </on-error>
</policies>
```

```xml
<!-- JWT Validation -->
<inbound>
  <validate-jwt header-name="Authorization" require-scheme="Bearer">
    <openid-config url="https://login.microsoftonline.com/{tenant}/.well-known/openid-configuration" />
    <required-claims>
      <claim name="aud" match="all">
        <value>{client-id}</value>
      </claim>
    </required-claims>
  </validate-jwt>
  <base />
</inbound>
```

```xml
<!-- CORS policy -->
<inbound>
  <cors allow-credentials="true">
    <allowed-origins>
      <origin>https://contoso.com</origin>
    </allowed-origins>
    <allowed-methods>
      <method>GET</method>
      <method>POST</method>
    </allowed-methods>
    <allowed-headers>
      <header>Authorization</header>
      <header>Content-Type</header>
    </allowed-headers>
  </cors>
  <base />
</inbound>
```

### Products, Subscriptions, and Developer Portal

APIs are grouped into **Products**. Users subscribe to products to get access. Each subscription has a **subscription key** sent via the `Ocp-Apim-Subscription-Key` header or as a query parameter. Products can be **Open** (no subscription required) or **Protected** (subscription required, may need approval).

The **Developer Portal** is an auto-generated website where developers can discover APIs, read documentation, test endpoints interactively, and manage their subscriptions.

### OAuth 2.0 Integration

APIM can validate OAuth 2.0 tokens using the `validate-jwt` policy. The typical flow is: the client obtains a token from Azure AD (or another identity provider), sends it in the Authorization header, and APIM validates the token before forwarding the request to the backend. The backend can also receive the validated token for further authorization.

```bash
# Create an APIM instance (Developer tier for non-production)
az apim create --name myapim --resource-group myRG --publisher-email admin@contoso.com \
  --publisher-name Contoso --sku-name Developer --location eastus

# Import an API from an OpenAPI spec
az apim api import --resource-group myRG --service-name myapim \
  --path myapi --specification-format OpenApi --specification-url https://petstore.swagger.io/v2/swagger.json

# Set a policy on an API
az apim api policy create --resource-group myRG --service-name myapim --api-id myapi \
  --xml-policy "<policies><inbound><rate-limit calls='50' renewal-period='60'/><base/></inbound><backend><base/></backend><outbound><base/></outbound><on-error><base/></on-error></policies>"
```

**Exam tip:** The `<base />` element inherits policies from the parent scope (All APIs → Product → API → Operation). Removing `<base />` prevents policy inheritance, which can break expected behavior.

---

## Messaging Services

Azure provides three primary messaging services, and the exam loves to test when to use which. Understanding the differences is essential.

### Comparison Table

| Feature | Event Grid | Event Hubs | Service Bus |
|---|---|---|---|
| **Model** | Reactive event routing | High-throughput streaming | Enterprise message broker |
| **Protocol** | HTTP push (webhooks) | AMQP, HTTPS, Kafka | AMQP, HTTPS |
| **Delivery** | At-least-once | At-least-once | At-least-once / At-most-once |
| **Ordering** | No guarantee | Per partition | FIFO (with sessions) |
| **Use Case** | Azure resource events, custom events | Telemetry, log ingestion, IoT | Order processing, workflows |
| **Max Message Size** | 1 MB (CloudEvents) | 1 MB (256 KB for Basic tier) | 256 KB (Standard) / 100 MB (Premium) |
| **Retention** | 24 hours (retry) | 1–90 days (configurable) | Until consumed |

### Event Grid

Event Grid is designed for event-driven architectures. It routes events from **sources** (Azure services, custom topics) to **handlers** (webhooks, Azure Functions, Event Hubs, Service Bus queues). It supports **CloudEvents v1.0** schema and a custom Azure Event Grid schema. Event Grid uses a retry policy with exponential backoff and can dead-letter undelivered events to a storage container.

### Service Bus: Queues, Topics, and Sessions

Service Bus queues provide **FIFO ordering** (when sessions are used), **duplicate detection**, and **dead-letter queues**. Topics and subscriptions enable pub-sub patterns where multiple subscribers receive copies of each message with optional SQL-like filters.

**Sessions** enable ordered message processing by grouping messages with the same `SessionId`. When a consumer locks a session, it processes all messages in that session in order. This is essential for scenarios where message ordering matters (e.g., processing steps for an order).

**Dead-letter queues (DLQ)** receive messages that cannot be processed — either because they exceeded the maximum delivery count or were explicitly dead-lettered by the consumer. Every queue and subscription has a DLQ that you can read from programmatically.

**Poison messages** are messages that repeatedly fail processing. After the maximum delivery count is reached (default: 10), the message is moved to the DLQ. Always monitor your DLQ and set up alerts.

### Event Hubs

Event Hubs is optimized for **big data streaming**. It uses **partitions** (2–32 for Standard, up to 2000 for Dedicated) for parallel processing and **consumer groups** for independent readers. Data is retained for a configurable period (1–90 days). Event Hubs supports the Apache Kafka protocol, allowing Kafka producers and consumers to use Event Hubs with minimal code changes.

```bash
# Create a Service Bus namespace and queue
az servicebus namespace create --name mysbnamespace --resource-group myRG --sku Standard
az servicebus queue create --name orders --namespace-name mysbnamespace --resource-group myRG \
  --max-delivery-count 10 --enable-dead-lettering-on-message-expiration true

# Create an Event Grid topic
az eventgrid topic create --name myegtopic --resource-group myRG --location eastus

# Create an Event Hub namespace and event hub
az eventhubs namespace create --name myehnamespace --resource-group myRG --sku Standard
az eventhubs eventhub create --name telemetry --namespace-name myehnamespace --resource-group myRG \
  --partition-count 4 --message-retention 7
```

**Exam tip:** If the question mentions "reactive" or "event-driven with Azure services," choose Event Grid. If it mentions "streaming" or "telemetry ingestion," choose Event Hubs. If it mentions "ordered processing" or "enterprise workflows," choose Service Bus.

---

## Caching and CDN

Caching reduces latency and database load. The exam tests Redis caching patterns, eviction policies, and CDN configuration.

### Azure Cache for Redis Patterns

- **Cache-Aside (Lazy Loading)** — The application checks the cache first. On a miss, it reads from the database, writes the result to the cache, and returns it. This is the most common pattern. Stale data is possible if the database is updated without invalidating the cache.
- **Write-Through** — Every write goes to both the cache and the database simultaneously. Ensures cache consistency but adds write latency.
- **Write-Behind (Write-Back)** — Writes go to the cache first, and the cache asynchronously flushes to the database. Reduces write latency but risks data loss if the cache fails before flushing.

### Eviction Policies

When the cache reaches its memory limit, an eviction policy determines which keys to remove:

- **volatile-lru** — Evict the least recently used key among keys with an expiry set.
- **allkeys-lru** — Evict the least recently used key among all keys.
- **volatile-ttl** — Evict the key with the shortest time-to-live among keys with an expiry set.
- **noeviction** — Return errors on write operations when memory is full. Use when data loss is unacceptable and you want to be alerted.

**Exam tip:** The default eviction policy for Azure Cache for Redis is **volatile-lru**. If your application does not set TTLs on keys, no keys will be evicted under this policy, and the cache will eventually return errors.

### Redis Data Types for Caching

Redis supports strings, lists, sets, sorted sets, and hashes. For caching scenarios, **strings** are used for simple key-value caching, **hashes** for storing objects with multiple fields (e.g., a user profile with name, email, role), and **sorted sets** for leaderboards or ranked data.

### Azure CDN

Azure CDN caches static content at edge locations worldwide. Key configuration options:

- **Caching rules** — Override cache headers to control TTL at the CDN level. Options include "Bypass cache," "Override," and "Set if missing."
- **Query string behavior** — Three modes: Ignore query strings (all requests hit the same cache), Cache every unique URL (each query string variation is cached separately), or Bypass caching for URLs with query strings.
- **Purge** — Immediately removes cached content from all edge nodes. Use when content is updated and you cannot wait for TTL expiry.
- **Preload** — Pre-populates edge nodes with content before the first request. Useful for large files that should be available immediately.

```bash
# Create a CDN profile and endpoint
az cdn profile create --name mycdnprofile --resource-group myRG --sku Standard_Microsoft
az cdn endpoint create --name myendpoint --resource-group myRG --profile-name mycdnprofile \
  --origin myapp.azurewebsites.net

# Purge content
az cdn endpoint purge --name myendpoint --resource-group myRG --profile-name mycdnprofile \
  --content-paths "/css/*" "/js/*"

# Create an Azure Cache for Redis instance
az redis create --name myredis --resource-group myRG --location eastus --sku Standard --vm-size c1
```

---

## Authentication and Identity

Azure identity services are tested across multiple question types on AZ-204. You must understand Managed Identity types, the DefaultAzureCredential chain, OAuth 2.0 flows, MSAL, and Key Vault integration.

### Managed Identity

Managed Identity provides an automatically managed identity in Azure AD for Azure resources. There are two types:

| Feature | System-Assigned | User-Assigned |
|---|---|---|
| **Creation** | Created with the resource | Created as a standalone Azure resource |
| **Lifecycle** | Tied to the resource (deleted when resource is deleted) | Independent (persists until explicitly deleted) |
| **Sharing** | Cannot be shared across resources | Can be assigned to multiple resources |
| **Use Case** | Single resource needing identity | Multiple resources sharing the same identity |

**Exam tip:** If a question asks about assigning the same identity to multiple VMs or function apps, the answer is User-Assigned Managed Identity. System-Assigned cannot be shared.

### DefaultAzureCredential

The `DefaultAzureCredential` class from the Azure Identity library tries multiple credential types in order:

1. Environment variables (`AZURE_CLIENT_ID`, `AZURE_TENANT_ID`, `AZURE_CLIENT_SECRET`)
2. Workload Identity (Kubernetes)
3. Managed Identity (system-assigned, then user-assigned)
4. Azure CLI (`az login`)
5. Azure PowerShell
6. Azure Developer CLI
7. Interactive browser (disabled by default)

This chain allows code to work seamlessly in local development (Azure CLI) and in production (Managed Identity) without code changes.

### OAuth 2.0 Flows

The Microsoft Identity Platform (Azure AD) supports these OAuth 2.0 flows:

- **Authorization Code Flow** — For web apps where the user signs in interactively. The app receives an authorization code, exchanges it for tokens. Most secure for user-facing apps. Always use PKCE (Proof Key for Code Exchange) with public clients.
- **Client Credentials Flow** — For daemon services or background jobs with no user interaction. The app authenticates with its own credentials (client secret or certificate) and gets an app-only token.
- **On-Behalf-Of Flow** — For middle-tier APIs that need to call downstream APIs on behalf of the signed-in user. The API exchanges the user's token for a new token scoped to the downstream API.

### MSAL Library Usage

The Microsoft Authentication Library (MSAL) simplifies token acquisition. It handles caching, token refresh, and retry logic.

```csharp
// C# — Acquire token using Client Credentials flow (daemon app)
using Azure.Identity;
using Microsoft.Identity.Client;

var app = ConfidentialClientApplicationBuilder
    .Create(clientId)
    .WithClientSecret(clientSecret)
    .WithAuthority(new Uri($"https://login.microsoftonline.com/{tenantId}"))
    .Build();

var result = await app.AcquireTokenForClient(new[] { "https://graph.microsoft.com/.default" })
    .ExecuteAsync();

Console.WriteLine($"Token: {result.AccessToken}");
```

```csharp
// C# — Using DefaultAzureCredential to access Key Vault
using Azure.Identity;
using Azure.Security.KeyVault.Secrets;

var client = new SecretClient(
    new Uri("https://mykeyvault.vault.azure.net/"),
    new DefaultAzureCredential());

KeyVaultSecret secret = await client.GetSecretAsync("DatabasePassword");
Console.WriteLine($"Secret value: {secret.Value}");
```

### Key Vault Integration

Azure Key Vault stores three types of objects:

- **Secrets** — Connection strings, passwords, API keys. Retrieved programmatically at runtime.
- **Keys** — Cryptographic keys for encryption/signing. Can be software-protected or HSM-protected.
- **Certificates** — SSL/TLS certificates with automatic renewal support.

Access to Key Vault is controlled by **RBAC** (recommended) or **Access Policies**. When using Managed Identity, grant the identity the appropriate RBAC role (e.g., `Key Vault Secrets User` for reading secrets).

```bash
# Create a Key Vault
az keyvault create --name mykeyvault --resource-group myRG --location eastus

# Set a secret
az keyvault secret set --vault-name mykeyvault --name DatabasePassword --value "S3cur3P@ss!"

# Grant a managed identity access to secrets
az role assignment create --role "Key Vault Secrets User" \
  --assignee <managed-identity-principal-id> \
  --scope /subscriptions/<sub-id>/resourceGroups/myRG/providers/Microsoft.KeyVault/vaults/mykeyvault

# Enable system-assigned managed identity on a web app
az webapp identity assign --name myapp --resource-group myRG
```

**Practical advice:** Never store secrets in app settings or code. Use Key Vault with Managed Identity. At Contoso, we use Key Vault References in App Service, which automatically resolve Key Vault secrets as app settings at runtime: set the app setting value to `@Microsoft.KeyVault(VaultName=mykeyvault;SecretName=DatabasePassword)`.

---

*End of study guide. For questions or updates, contact the Cloud Engineering Guild via the #az204-study Slack channel.*

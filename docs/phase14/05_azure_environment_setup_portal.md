# Phase 14 — Azure Dev Environment Setup (Portal Guide)

> **Status:** Guide for creating the **Azure dev environment** through the Azure portal in a web browser.
> **Date:** 2026-10-16
> **Same result as:** [04 — Azure environment setup (CLI)](04_azure_environment_setup.md). Both guides create the same resources with the same names, so either one (or a mix) works. The design they implement is in the [technical specification](02_tech_spec.md) §4, §5, §10.4 and §12.

> ℹ️ **About the portal.** Microsoft moves fields between tabs from time to time. This guide names each setting; if it is not on the tab mentioned, look on the neighbouring tabs (Basics, Networking, Security, Advanced, Integrations, Monitoring). A handful of steps cannot be done by clicking — they run in **Azure Cloud Shell**, a terminal inside the portal (top bar → the `>_` icon), so you still need only a browser.

---

## 0. Before you start

| Need | Notes |
|------|-------|
| A dev subscription where you are **Owner** | Needed for resources and role assignments |
| Permission to create **Entra ID groups** | Or ask your Entra admin to do §4.1 |
| vCPU quota in **Central India**: Dsv5 family ≥ 32 | Portal → **Quotas** → Compute → filter by region |
| Ability to add NS records for `azdev.hirebuddha.com` at your current DNS provider | For dev hostnames |
| Access to the Google Cloud project used for Vertex AI | §15 |
| Admin on the GitHub repository and organisation | §16 |

Confirm the region (open item O11): **Central India** must offer AKS, PostgreSQL Flexible Server 16, Azure Managed Redis and (for Claude) Microsoft Foundry models. Pick the region now; moving later means recreating everything.

**Tip — save templates as you go.** On every *Review + create* page there is a **Download a template for automation** link. Save each template into `infra/azure/portal-exports/` — they are a head start for the Bicep code in WS0.

---

## 1. Your values sheet

Pick a 4-character suffix (letters/digits, e.g. `k7q2`) and write the names down. Every step below uses them.

| Thing | Name | Resource group |
|-------|------|----------------|
| Suffix | `<sfx>` | — |
| Resource groups | `rg-hb-dev-core`, `rg-hb-dev-data`, `rg-hb-dev-aks`, `rg-hb-dev-edge` | — |
| Virtual network | `vnet-hb-dev` (10.40.0.0/16) | core |
| Public IPs | `pip-hb-dev-egress`, `pip-hb-dev-ingress` | core |
| NAT gateway | `ng-hb-dev` | core |
| Entra groups | `grp-hb-dev-admins`, `grp-hb-dev-developers`, `grp-hb-dev-pg-admins` | — |
| Managed identities | `id-hb-dev-aks`, `-api`, `-worker`, `-connsvc`, `-provisioner`, `-migrator`, `-appcontroller`, `-ci` | core |
| Log Analytics | `log-hb-dev` | core |
| Azure Monitor workspace | `amw-hb-dev` | core |
| Managed Grafana | `graf-hb-dev-<sfx>` | core |
| Application Insights | `appi-hb-dev` | core |
| Key Vaults | `kv-hb-dev-<sfx>` (platform), `kv-hb-dev-tk-<sfx>` (tenant keys) | core |
| Container registries | `acrhbdev<sfx>` (platform), `acrhbappsdev<sfx>` (tenant apps) | core |
| Storage account | `sthbdev<sfx>` | data |
| AKS cluster | `aks-hb-dev` (node RG `rg-hb-dev-aks-nodes`) | aks |
| PostgreSQL servers | `psql-hb-dev-control`, `psql-hb-dev-pool-01` | data |
| Postgres private DNS zone | `hb-dev.private.postgres.database.azure.com` | core |
| Managed Redis | `redis-hb-dev-<sfx>` | data |
| DNS zone | `azdev.hirebuddha.com` | edge |
| Front Door | `afd-hb-dev` | edge |
| AI resource | `ai-hb-dev-<sfx>` | core |

Region for everything: **Central India**. Tags on everything: `env=dev`, `app=hirebuddha`, `owner=platform`.

---

## 2. Register resource providers

Portal → **Subscriptions** → your dev subscription → **Settings → Resource providers**. Select each of these and click **Register** (skip any already *Registered*):

`Microsoft.ContainerService`, `Microsoft.DBforPostgreSQL`, `Microsoft.Cache`, `Microsoft.KeyVault`, `Microsoft.ContainerRegistry`, `Microsoft.Network`, `Microsoft.OperationalInsights`, `Microsoft.Insights`, `Microsoft.Monitor`, `Microsoft.Dashboard`, `Microsoft.Storage`, `Microsoft.Cdn`, `Microsoft.ManagedIdentity`, `Microsoft.AlertsManagement`, `Microsoft.CognitiveServices`, `Microsoft.App`.

**AKS Pod Sandboxing (verify):** if it is still a preview in your region, open **Subscriptions → Settings → Preview features**, search **Kata**, select the AKS Kata VM isolation feature and **Register**. Wait until it shows *Registered*.

---

## 3. Resource groups and network

### 3.1 Resource groups

Portal → **Resource groups** → **+ Create**, four times: `rg-hb-dev-core`, `rg-hb-dev-data`, `rg-hb-dev-aks`, `rg-hb-dev-edge` — region Central India, tags from §1.

### 3.2 Virtual network

**Virtual networks** → **+ Create**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / Name / Region | `rg-hb-dev-core` / `vnet-hb-dev` / Central India |
| IP addresses | IPv4 address space | `10.40.0.0/16` (delete the default range if different) |
| IP addresses | Subnets | Delete `default`, then **+ Add a subnet** three times (below) |

| Subnet name | Range | Extra setting |
|-------------|-------|---------------|
| `snet-aks-nodes` | `10.40.0.0/20` | — |
| `snet-pg` | `10.40.16.0/24` | **Subnet delegation:** `Microsoft.DBforPostgreSQL/flexibleServers` |
| `snet-pe` | `10.40.17.0/24` | — |

Leave the Security tab at defaults (no Bastion, no Firewall, no DDoS plan in dev). **Review + create**.

### 3.3 Public IPs

**Public IP addresses** → **+ Create**, twice:

| Setting | Value |
|---------|-------|
| Resource group | `rg-hb-dev-core` |
| Name | `pip-hb-dev-egress`, then `pip-hb-dev-ingress` |
| IP version / SKU / Tier | IPv4 / **Standard** / Regional |
| Availability zone | No zone (dev) |
| Assignment | **Static** |

Open `pip-hb-dev-egress` → **Overview** and note the **IP address**: this is the fixed outbound IP to give partners who allow-list (Tata Tele etc.).

### 3.4 NAT gateway

**NAT gateways** → **+ Create**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / Name / Region | `rg-hb-dev-core` / `ng-hb-dev` / Central India |
| Basics | TCP idle timeout | 10 minutes |
| Outbound IP | Public IP addresses | `pip-hb-dev-egress` |
| Subnet | Virtual network / subnet | `vnet-hb-dev` / tick **`snet-aks-nodes`** only |

---

## 4. Identity

### 4.1 Entra ID groups

Portal → **Microsoft Entra ID** → **Groups** → **New group**, three times:

| Group type | Name | Members |
|------------|------|---------|
| Security | `grp-hb-dev-admins` | you + platform leads |
| Security | `grp-hb-dev-developers` | developers |
| Security | `grp-hb-dev-pg-admins` | you (the managed identities are added in §4.2) |

### 4.2 Managed identities

Portal → **Managed Identities** → **+ Create**, eight times, all in `rg-hb-dev-core`, Central India:

`id-hb-dev-aks`, `id-hb-dev-api`, `id-hb-dev-worker`, `id-hb-dev-connsvc`, `id-hb-dev-provisioner`, `id-hb-dev-migrator`, `id-hb-dev-appcontroller`, `id-hb-dev-ci`.

For each one, open it and copy the **Client ID** from **Overview** into your values sheet — the Kubernetes setup (§9.3) needs them.

Then **Microsoft Entra ID → Groups → `grp-hb-dev-pg-admins` → Members → + Add members**, search for `id-hb-dev-provisioner` and `id-hb-dev-migrator` (managed identities appear by name) and add both.

---

## 5. Monitoring

| Create (portal search) | Settings |
|------------------------|----------|
| **Log Analytics workspaces** → + Create | `log-hb-dev`, RG core. After creation: **Settings → Usage and estimated costs → Data retention** = 30 days |
| **Azure Monitor workspaces** → + Create | `amw-hb-dev`, RG core |
| **Azure Managed Grafana** → + Create | `graf-hb-dev-<sfx>`, RG core, pricing plan **Standard**; on the Microsoft Grafana / Integrations tab link `amw-hb-dev` if offered |
| **Application Insights** → + Create | `appi-hb-dev`, RG core, resource mode **Workspace-based**, workspace `log-hb-dev` |

Grafana access: open `graf-hb-dev-<sfx>` → **Access control (IAM)** → **+ Add → Add role assignment**:
* **Grafana Admin** → group `grp-hb-dev-admins`
* **Grafana Viewer** → group `grp-hb-dev-developers`

Open `appi-hb-dev` → **Overview** and copy the **Connection String** (used in §6.3).

---

## 6. Key Vaults and secrets

### 6.1 Create the two vaults

**Key vaults** → **+ Create**, twice:

| Tab | Setting | Platform vault | Tenant-keys vault |
|-----|---------|----------------|-------------------|
| Basics | Name | `kv-hb-dev-<sfx>` | `kv-hb-dev-tk-<sfx>` |
| Basics | Resource group / Region | `rg-hb-dev-core` / Central India | same |
| Basics | Pricing tier | Standard | **Premium** |
| Basics | Days to retain deleted vaults | 30 | 30 |
| Basics | Purge protection | **Enable** | **Enable** |
| Access configuration | Permission model | **Azure role-based access control** | same |
| Networking | Public access | All networks (dev only) | same |

### 6.2 Who may do what

On each vault → **Access control (IAM)** → **+ Add → Add role assignment**. Choose the role, then on **Members** pick *User, group, or service principal* (groups) or *Managed identity* (identities):

| Vault | Role | Assign to |
|-------|------|-----------|
| both | Key Vault Administrator | `grp-hb-dev-admins` |
| platform | Key Vault Secrets User | `grp-hb-dev-developers` |
| platform | Key Vault Secrets User | identities `api`, `worker`, `connsvc`, `provisioner`, `migrator`, `appcontroller` |
| platform | Key Vault Crypto User | identity `api` (signs Data API tokens) |
| tenant keys | Key Vault Crypto User | identity `connsvc` |
| tenant keys | Key Vault Crypto Officer | identity `provisioner` |

Role assignments can take a few minutes to take effect; if the next step says *forbidden*, wait and retry.

### 6.3 Secrets and the signing key

Platform vault → **Objects → Secrets → + Generate/Import**. For random values, open Cloud Shell and run `openssl rand -hex 32`, or use your password manager's generator.

| Secret name | Value |
|-------------|-------|
| `secret-key` | random 64 hex characters |
| `internal-token` | random 64 hex characters |
| `appinsights-connection-string` | the connection string from §5 |
| `pg-break-glass-password` | the PostgreSQL admin password you choose in §10 |
| `razorpay-key-id`, `razorpay-key-secret`, `razorpay-webhook-secret` | Razorpay **test** keys |
| `twilio-account-sid`, `twilio-auth-token`, `tata-*`, `smtp-*` | provider sandbox / test values |
| `azure-openai-endpoint` | from §14 |
| `redis-url` | built in §11 |
| `github-app-id`, `github-app-private-key`, `github-webhook-secret` | from §16.2 |
| `meta-app-id`, `meta-app-secret`, `linkedin-client-id`, `linkedin-client-secret`, `google-oauth-client-id`, `google-oauth-client-secret` | HireBuddha **dev** provider apps |

Then **Objects → Keys → + Generate/Import**: name `data-api-signing`, key type **RSA**, size **2048**.

---

## 7. Container registries and storage

### 7.1 Registries

**Container registries** → **+ Create**, twice: `acrhbdev<sfx>` and `acrhbappsdev<sfx>`, RG core, Central India, pricing plan **Standard**. (Admin user stays disabled — the default.)

Role assignments (**Access control (IAM) → Add role assignment**):

| Registry | Role | Assign to |
|----------|------|-----------|
| `acrhbdev<sfx>` | AcrPush | identity `ci`; group `grp-hb-dev-developers` |
| `acrhbappsdev<sfx>` | Contributor | identity `appcontroller` (runs ACR Tasks builds) |

### 7.2 Storage account

**Storage accounts** → **+ Create**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / Name / Region | `rg-hb-dev-data` / `sthbdev<sfx>` / Central India |
| Basics | Primary service / Performance / Redundancy | Azure Blob Storage / Standard / **LRS** |
| Advanced | Require secure transfer | On |
| Advanced | Allow enabling anonymous access on containers | **Off** |
| Advanced | Enable storage account key access | **Off** |
| Advanced | Default to Microsoft Entra authorization in the portal | **On** |
| Advanced | Minimum TLS version | 1.2 |
| Data protection | Soft delete for blobs / containers | On, 14 days each |
| Data protection | Versioning for blobs | On |

After creation → **Access control (IAM)**:

| Role | Assign to |
|------|-----------|
| Storage Blob Data Owner | `grp-hb-dev-admins` |
| Storage Blob Data Contributor | `grp-hb-dev-developers`; identities `api`, `worker`, `provisioner`, `appcontroller`, `connsvc` |

Then **Data storage → Containers → + Container**: `platform` and `migration` (anonymous access level: Private).

---

## 8. AKS cluster

### 8.1 Give the cluster identity network rights (first)

* `vnet-hb-dev` → **Access control (IAM)** → **Network Contributor** → managed identity `id-hb-dev-aks`.
* Resource group `rg-hb-dev-core` → **Access control (IAM)** → **Network Contributor** → `id-hb-dev-aks` (lets AKS use the static ingress IP).

### 8.2 Create the cluster

**Kubernetes services** → **+ Create → Kubernetes cluster**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / Cluster preset | `rg-hb-dev-aks` / Dev/Test |
| Basics | Name / Region / Availability zones | `aks-hb-dev` / Central India / None |
| Basics | AKS pricing tier | **Free** |
| Basics | Kubernetes version / Automatic upgrade | default / patch |
| Basics | Authentication and authorization | **Microsoft Entra ID authentication with Azure RBAC**; cluster admin group `grp-hb-dev-admins` |
| Node pools | Default pool (edit it) | Name `system`, mode System, OS SKU **Azure Linux**, size **D2s_v5**, scale method **Manual**, 1 node |
| Node pools | **+ Add node pool** | `platform`: User, Azure Linux, **D4s_v5**, autoscale **1–4**, label `hb/pool=platform` |
| Node pools | **+ Add node pool** | `apps`: User, Azure Linux, **D4s_v5**, autoscale **1–4**, label `hb/pool=apps` |
| Networking | Network configuration | **Azure CNI Overlay** |
| Networking | Bring your own virtual network | `vnet-hb-dev` / `snet-aks-nodes` |
| Networking | Pod CIDR / Service CIDR / DNS service IP | `192.168.0.0/16` / `172.16.0.0/16` / `172.16.0.10` |
| Networking | Network policy / data plane | **Cilium** |
| Networking | Outbound type | **User-assigned NAT gateway** |
| Integrations | Container registry | `acrhbdev<sfx>` |
| Integrations / Monitoring | Container insights | On → workspace `log-hb-dev` |
| Integrations / Monitoring | Managed Prometheus | On → `amw-hb-dev` |
| Integrations / Monitoring | Managed Grafana | `graf-hb-dev-<sfx>` |
| Security | OIDC issuer | **Enable** |
| Security | Workload identity | **Enable** |
| Security / Advanced | Secrets Store CSI driver (Key Vault provider) | **Enable** |
| Advanced | Cluster identity | User-assigned → `id-hb-dev-aks` |
| Advanced | Infrastructure resource group | `rg-hb-dev-aks-nodes` |

Save the automation template, then **Review + create**. Creation takes 10–15 minutes.

### 8.3 After creation

1. **KEDA:** cluster → **Settings → Application scaling** → enable **KEDA**.
2. **Sandbox pool (Cloud Shell):** the portal may not offer the *Kata VM isolation* runtime, so add this pool from Cloud Shell:

   ```bash
   az aks nodepool add -g rg-hb-dev-aks --cluster-name aks-hb-dev -n sandbox --mode User --os-sku AzureLinux \
     --workload-runtime KataVmIsolation \
     --node-vm-size Standard_D4s_v5 --enable-cluster-autoscaler --min-count 1 --max-count 4 \
     --labels hb/pool=sandbox --node-taints hb/pool=sandbox:NoSchedule
   ```
   (verify: older CLI versions call the value `KataMshvVmIsolation`; the VM size must support nested virtualization.)
3. **Keep apps off the system pool:** cluster → **Settings → Node pools → system → Taints and labels** → add taint `CriticalAddonsOnly=true:NoSchedule`.
4. **Pull from the apps registry:** `acrhbappsdev<sfx>` → **Access control (IAM)** → **AcrPull** → managed identity **`aks-hb-dev-agentpool`** (the kubelet identity, in `rg-hb-dev-aks-nodes`).
5. **Who can use the cluster:** cluster → **Access control (IAM)**:
   * **Azure Kubernetes Service RBAC Cluster Admin** → `grp-hb-dev-admins`
   * **Azure Kubernetes Service Cluster User Role** → `grp-hb-dev-developers`
   * **Azure Kubernetes Service RBAC Writer** → `grp-hb-dev-developers` (cluster-wide is acceptable in dev; the namespace-only version needs the Cloud Shell command in [04 §9.4](04_azure_environment_setup.md#94-namespaces-service-accounts-workload-identity))
6. **OIDC issuer URL:** cluster → **Overview → JSON View**, find `oidcIssuerProfile.issuerUrl` and copy it into your values sheet.

---

## 9. Kubernetes namespaces and workload identity

### 9.1 Federated credentials (portal)

For each of `api`, `worker`, `connsvc`, `provisioner`, `migrator`, `appcontroller`: open **Managed Identities → `id-hb-dev-<name>` → Settings → Federated credentials → + Add credential**:

| Field | Value |
|-------|-------|
| Federated credential scenario | **Kubernetes accessing Azure resources** |
| Cluster issuer URL | the OIDC issuer URL from §8.3 |
| Namespace | `hb-platform` |
| Service account | `sa-<name>` (e.g. `sa-worker`) |
| Name | `fc-aks-hb-dev-<name>` |

### 9.2 Namespaces and service accounts (portal YAML)

Cluster → **Kubernetes resources → Namespaces → + Create → Apply a YAML**. Replace each `<client-id-…>` with the Client IDs from §4.2 and click **Add**:

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: hb-platform
  labels: { pod-security.kubernetes.io/enforce: baseline }
---
apiVersion: v1
kind: Namespace
metadata:
  name: hb-system
  labels: { pod-security.kubernetes.io/enforce: baseline }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-api, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-api>" } }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-worker, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-worker>" } }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-connsvc, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-connsvc>" } }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-provisioner, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-provisioner>" } }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-migrator, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-migrator>" } }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: sa-appcontroller, namespace: hb-platform, annotations: { azure.workload.identity/client-id: "<client-id-appcontroller>" } }
```

### 9.3 Cluster add-ons (Cloud Shell)

Helm charts cannot be installed from portal screens. In Cloud Shell:

```bash
az aks get-credentials -g rg-hb-dev-aks -n aks-hb-dev --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true
helm install eg oci://docker.io/envoyproxy/gateway-helm --version <stable-version> -n envoy-gateway-system --create-namespace
```

Point the Envoy Gateway load balancer at `pip-hb-dev-ingress` as described in [04 §9.5](04_azure_environment_setup.md#95-cluster-add-ons).

---

## 10. PostgreSQL Flexible Server

### 10.1 Private DNS zone

**Private DNS zones** → **+ Create**: name `hb-dev.private.postgres.database.azure.com`, RG core. Then open it → **DNS Management → Virtual Network Links → + Add**: link name `link-vnet-hb-dev`, network `vnet-hb-dev`, auto-registration **off**.

### 10.2 The two servers

**Azure Database for PostgreSQL flexible servers** → **+ Create**, twice:

| Tab | Setting | Control server | Tenant pool server |
|-----|---------|----------------|--------------------|
| Basics | Resource group / Name | `rg-hb-dev-data` / `psql-hb-dev-control` | `rg-hb-dev-data` / `psql-hb-dev-pool-01` |
| Basics | Region / PostgreSQL version | Central India / **16** | same |
| Basics | Workload type → **Configure server** | Compute tier **Burstable**, size **Standard_B2ms**, storage **64 GiB** | Compute tier **General Purpose**, size **Standard_D2ds_v5**, storage **128 GiB** |
| Basics | High availability | Disabled | Disabled (dev) |
| Basics | Backup retention / Geo-redundancy | 7 days / off | same |
| Basics | Authentication method | **PostgreSQL and Microsoft Entra authentication** | same |
| Basics | Microsoft Entra admin | select group `grp-hb-dev-pg-admins` | same |
| Basics | Administrator login / password | `hbadmin` / a strong password → save it in Key Vault as `pg-break-glass-password` | same password |
| Networking | Connectivity method | **Private access (VNet Integration)** | same |
| Networking | Virtual network / Subnet | `vnet-hb-dev` / `snet-pg` | same |
| Networking | Private DNS zone | `hb-dev.private.postgres.database.azure.com` | same |

### 10.3 Server settings and databases

On **each** server → **Settings → Server parameters** → search `azure.extensions` → tick `VECTOR`, `PGCRYPTO`, `PG_TRGM`, `UUID-OSSP`, `BTREE_GIN` → **Save**.

On **`psql-hb-dev-pool-01`** → **Server parameters** → `pgbouncer.enabled` = **true** → **Save** (or the server's *Connection pooling / PgBouncer* page if shown).

**Settings → Databases → + Add**:
* control server: `hb_control`, `hb_gitea`
* pool server: `t_devacme01`, `t_devbeta001`

### 10.4 Database roles (Cloud Shell + a temporary pod)

The servers are private, so SQL runs from a short-lived `psql` pod inside the cluster. In Cloud Shell (after §9.3's `get-credentials`):

```bash
TOKEN=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
kubectl run psql -n hb-system --rm -it --restart=Never --image=postgres:16 --env="PGPASSWORD=$TOKEN" -- \
  psql "host=psql-hb-dev-pool-01.postgres.database.azure.com dbname=postgres user=grp-hb-dev-pg-admins sslmode=require"
```

At the `postgres=>` prompt paste:

```sql
SELECT * FROM pgaadauth_create_principal('id-hb-dev-worker', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-api', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-connsvc', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-migrator', false, false);
CREATE ROLE hb_runtime  NOLOGIN;
CREATE ROLE hb_dataapi  NOLOGIN;
CREATE ROLE hb_migrator NOLOGIN;
GRANT hb_runtime  TO "id-hb-dev-worker", "id-hb-dev-api", "id-hb-dev-connsvc";
GRANT hb_migrator TO "id-hb-dev-migrator";
```

Type `\q`, then repeat with `host=psql-hb-dev-control.postgres.database.azure.com`. (Members of an Entra admin group sign in with the **group name** as user and an access token as password; tokens last about an hour.)

---

## 11. Azure Managed Redis

Portal search **Azure Managed Redis** → **+ Create**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / DNS name / Region | `rg-hb-dev-data` / `redis-hb-dev-<sfx>` / Central India |
| Basics | Performance tier / Cache size | **Balanced** / **B1** |
| Networking | Connectivity | **Private endpoint** → **+ Add**: name `pe-redis-hb-dev`, network `vnet-hb-dev`, subnet `snet-pe`, **Integrate with private DNS zone: Yes** (the portal creates the correct zone) |
| Advanced | Minimum TLS version | 1.2 |
| Advanced | Clustering policy | Non-clustered — spike SP-2: Arq fails with `CROSSSLOT` under Enterprise |
| Advanced | High availability | Enabled (can be disabled in dev to halve the cost) |

After creation: **Overview** → copy the **Endpoint / host name** and port (10000), then **Settings → Authentication / Access keys** → copy the primary key. Create the Key Vault secret `redis-url` with value `rediss://:<primary-key>@<host-name>:10000/0`.

---

## 12. DNS and Front Door

### 12.1 DNS zone

**DNS zones** → **+ Create**: name `azdev.hirebuddha.com`, RG edge. Open it → **Overview** shows four **name servers**. At the current DNS provider of `hirebuddha.com`, add **NS records for `azdev`** pointing to those four servers. (Production DNS is untouched.)

Then in the zone → **+ Record set**: name `origin`, type **A**, value = the IP of `pip-hb-dev-ingress`.

### 12.2 Front Door

Do this once the platform ingress serves `/health` (after the first deployment), otherwise the health probe will show the origin as down.

**Front Door and CDN profiles** → **+ Create** → **Azure Front Door** → **Custom create**:

| Tab | Setting | Value |
|-----|---------|-------|
| Basics | Resource group / Name / Tier | `rg-hb-dev-edge` / `afd-hb-dev` / **Standard** |
| Endpoint | **+ Add an endpoint** | `ep-hb-dev-<sfx>` |
| Endpoint → **+ Add a route** | Domains | **+ Add a new domain** ×4: DNS management **Azure managed DNS**, zone `azdev.hirebuddha.com`, custom domains `app`, `api`, `gateway`, `connect`, certificate **AFD managed**, minimum TLS 1.2 |
| Route | Origin group → **+ Add a new origin group** | Name `og-platform`; origin host name `origin.azdev.hirebuddha.com` (type *Custom*), origin host header the same, HTTPS 443; health probe **Enabled**, path `/health`, protocol HTTPS, interval 60 s |
| Route | Accepted protocols / redirect / forwarding | HTTP and HTTPS / **Redirect all traffic to HTTPS** / **HTTPS only** |

With *Azure managed DNS*, the portal adds the validation and CNAME records in your zone for you; certificates show *Approved* after a few minutes.

Spike SP-7 tests telephony WebSockets through Front Door; if they misbehave, change the `gateway` record to point straight at `pip-hb-dev-ingress`.

---

## 13. Two dev tenants by hand

Until the Provisioner (WS2) exists, create the two dev tenants `devacme01` and `devbeta001` like this:

| Step | Where | What |
|------|-------|------|
| 1 | **Managed Identities → + Create** | `id-hb-dev-t-devacme01` (RG core); copy its Client ID |
| 2 | Tenant-keys vault → **Keys → + Generate/Import** | Name `t-devacme01`, RSA, 3072 |
| 3 | The new key → **Access control (IAM)** | **Key Vault Crypto User** → managed identity `id-hb-dev-t-devacme01` (if the key has no IAM page in your portal, use the Cloud Shell command in [04 §10.6](04_azure_environment_setup.md#106-two-dev-tenants-by-hand-until-the-provisioner-exists)) |
| 4 | Storage account → **Containers → + Container** | `t-devacme01`, Private |
| 5 | AKS → **Kubernetes resources → Namespaces → Apply a YAML** | YAML below |
| 6 | The identity → **Federated credentials → + Add** | Scenario *Kubernetes accessing Azure resources*, namespace `t-devacme01`, service account `data-api`, name `fc-data-api` |
| 7 | Cloud Shell `psql` pod (§10.4), pool server | SQL below |

```yaml
apiVersion: v1
kind: Namespace
metadata:
  name: t-devacme01
  labels: { pod-security.kubernetes.io/enforce: restricted }
---
apiVersion: v1
kind: ServiceAccount
metadata: { name: data-api, namespace: t-devacme01, annotations: { azure.workload.identity/client-id: "<client-id-t-devacme01>" } }
```

```sql
SELECT * FROM pgaadauth_create_principal('id-hb-dev-t-devacme01', false, false);
GRANT hb_dataapi TO "id-hb-dev-t-devacme01";
REVOKE CONNECT ON DATABASE t_devacme01 FROM PUBLIC;
GRANT  CONNECT ON DATABASE t_devacme01 TO "id-hb-dev-t-devacme01", hb_runtime, hb_migrator;
```

Repeat everything for `devbeta001`.

---

## 14. AI models on Azure

1. Portal search **Azure AI Foundry** (or **Microsoft Foundry**) → create an **AI Services / Foundry resource** `ai-hb-dev-<sfx>` in RG core, in a region that offers the models you need.
2. Resource → **Access control (IAM)** → **Cognitive Services User** → managed identities `api` and `worker`.
3. Open the Foundry portal from the resource → **Deployments**: deploy the GPT models HireBuddha uses; copy the endpoint into Key Vault as `azure-openai-endpoint`.
4. **Claude (spike SP-5):** Foundry → **Model catalog** → search *Claude* → deploy in a region that offers it. If none does yet, keep using Anthropic's API with its key in Key Vault.

---

## 15. Google federation for Gemini (Google Cloud console)

In the Google Cloud console, project = the Vertex AI project:

1. **IAM & Admin → Workload Identity Federation → Create pool**: name `hb-azure-dev`.
2. **Add a provider → OpenID Connect (OIDC)**: name `aks-dev`; **Issuer (URL)** = the AKS OIDC issuer URL (§8.3); **Audiences → Allowed audiences** = `api://AzureADTokenExchange`; attribute mapping `google.subject` = `assertion.sub`.
3. **IAM & Admin → Service accounts → Create**: `hb-vertex-dev`, role **Vertex AI User**.
4. Back in the pool → **Grant access** → *Grant access using service account impersonation* → service account `hb-vertex-dev` → principals filtered by **subject** = `system:serviceaccount:hb-platform:sa-api`; repeat for `system:serviceaccount:hb-platform:sa-worker`.
5. In the pool → **Connected service accounts → Download config** (or *Configure your application*): OIDC token path `/var/run/secrets/azure/tokens/azure-identity-token`, format **text** → download `google-wif-dev.json`.

The file contains no secret. It is mounted into the API and worker pods and named in `GOOGLE_WIF_CREDENTIAL_FILE` (tech spec §12.4).

---

## 16. GitHub

### 16.1 Deploying from GitHub Actions

1. **Managed Identities → `id-hb-dev-ci` → Federated credentials → + Add credential**:

   | Field | Value |
   |-------|-------|
   | Scenario | **GitHub Actions deploying Azure resources** |
   | Organization / Repository | your org / `hire-buddha-app` |
   | Entity | **Environment**, name `azure-dev` |
   | Name | `gh-azure-dev` |

2. AKS cluster → **Access control (IAM)**: **Azure Kubernetes Service Cluster User Role** and **Azure Kubernetes Service RBAC Writer** → managed identity `id-hb-dev-ci`.
3. On GitHub: repository → **Settings → Environments → New environment** `azure-dev` → **Environment variables**: `AZURE_CLIENT_ID` (Client ID of `id-hb-dev-ci`), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `AKS_NAME`, `AKS_RESOURCE_GROUP`.

### 16.2 Dev GitHub App for tenant connections

GitHub organisation → **Settings → Developer settings → GitHub Apps → New GitHub App**, exactly as in [04 §15.2](04_azure_environment_setup.md#152-dev-github-app-for-tenant-connections). Store the App ID, private key and webhook secret in the platform vault (§6.3).

---

## 17. Smoke tests (portal only)

Apply these through **AKS → Kubernetes resources → Workloads → + Create → Apply a YAML**, then open **Workloads → Pods → (pod) → Logs**.

**Workload identity can read Key Vault** (replace `<kv-name>`):

```yaml
apiVersion: v1
kind: Pod
metadata:
  name: wi-test
  namespace: hb-platform
  labels: { azure.workload.identity/use: "true" }
spec:
  serviceAccountName: sa-worker
  restartPolicy: Never
  nodeSelector: { hb/pool: platform }
  containers:
  - name: az
    image: mcr.microsoft.com/azure-cli
    command: ["sh", "-c"]
    args:
    - az login --service-principal -u "$AZURE_CLIENT_ID" -t "$AZURE_TENANT_ID" --federated-token "$(cat $AZURE_FEDERATED_TOKEN_FILE)" -o none &&
      az keyvault secret show --vault-name <kv-name> -n internal-token --query name -o tsv
```

Expected log: `internal-token`.

**Sandbox pods run in their own micro-VM:**

```yaml
apiVersion: v1
kind: Pod
metadata: { name: kata-test, namespace: t-devacme01 }
spec:
  runtimeClassName: kata-vm-isolation          # (verify) the runtime class created by Pod Sandboxing
  restartPolicy: Never
  nodeSelector: { hb/pool: sandbox }
  tolerations: [{ key: hb/pool, operator: Equal, value: sandbox, effect: NoSchedule }]
  securityContext: { runAsNonRoot: true, runAsUser: 1000, seccompProfile: { type: RuntimeDefault } }
  containers:
  - name: c
    image: mcr.microsoft.com/azurelinux/base/core:3.0
    command: ["sh", "-c", "uname -r"]
    securityContext: { allowPrivilegeEscalation: false, capabilities: { drop: ["ALL"] } }
```

Expected log: a kernel version different from the node's (node kernel: **Node pools → sandbox → Nodes**).

**Outbound IP is the NAT gateway's:** apply a pod running `curlimages/curl` with `args: ["-s", "https://ifconfig.me"]` in `hb-system`; its log must show the IP of `pip-hb-dev-egress`.

Delete the test pods afterwards (**Pods → select → Delete**).

---

## 18. Verification checklist

| # | Check | Where |
|---|-------|-------|
| 1 | Four node pools: system, platform, apps, sandbox | AKS → Settings → Node pools |
| 2 | `wi-test` log shows `internal-token` | AKS → Workloads → Pods |
| 3 | Outbound IP equals `pip-hb-dev-egress` | curl pod log |
| 4 | `CREATE EXTENSION IF NOT EXISTS vector;` succeeds in `t_devacme01` | Cloud Shell `psql` pod (§10.4) |
| 5 | Redis private endpoint *Approved*; host resolves to 10.40.17.x | Redis → Networking / Private endpoint connections |
| 6 | `kata-test` kernel differs from the node's | Pod log |
| 7 | Gemini answers from a pod using `google-wif-dev.json` | After the first deployment (spike SP-4) |
| 8 | `https://app.azdev.hirebuddha.com/health` → 200 | Browser, after the first deployment |
| 9 | A GitHub Actions run on `main` deploys | GitHub → Actions; AKS → Workloads |
| 10 | Container logs in Log Analytics; dashboards in Grafana | `log-hb-dev` → Logs; Grafana → Dashboards |

Record names and IDs in `infra/azure/env/dev.env` (non-secret) so the team uses the same values.

---

## 19. Keeping dev costs down

* **Stop** the cluster when idle: AKS → **Overview → Stop** (and **Start** later).
* **Stop** each PostgreSQL server: server → **Overview → Stop** (Azure restarts it automatically after 7 days).
* Reduce the sandbox pool minimum to 0 once spike SP-1 is done: **Node pools → sandbox → Scale node pool**.
* Create a monthly budget with alerts: **Cost Management → Budgets → + Add**, scope = the dev subscription.

The cost estimate for this environment is about **$1,255/month** running 24×7, or about **$410/month** with leaner sizes and office-hours stopping.

---

## 20. What still needs Cloud Shell

| Step | Why the portal cannot do it |
|------|-----------------------------|
| Sandbox node pool with Kata (§8.3) | The portal may not offer the Kata runtime option |
| Helm add-ons (§9.3) | No Helm in the portal |
| SQL roles and grants (§10.4, §13) | The servers are private and the portal has no query editor for them |
| Namespace-scoped AKS roles (optional) | The portal assigns roles at cluster scope only |
| Generating random secrets (optional) | Use Cloud Shell `openssl rand -hex 32` or a password manager |

Everything else — about 90% of the setup — is point-and-click. For staging and production, use the infrastructure code from WS0 rather than the portal, so they are repeatable (see the CLI guide [§20](04_azure_environment_setup.md#20-staging-and-production-what-is-different)).

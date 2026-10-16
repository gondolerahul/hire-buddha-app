# Phase 14 — Azure Environment Setup Guide

> **Status:** Guide for creating the **Azure dev environment** so Phase 14 development can start there. Staging and production are created later from code (WS0 in the [implementation plan](01_implementation_plan.md)); §20 lists how they differ.
> **Date:** 2026-10-16
> **Design it implements:** [02 — Technical specification](02_tech_spec.md) §4, §5, §10.4, §12.
> **Decisions:** D34 (AKS layout), D38 (Flexible Server), D39 (move to Azure); open item O11 (regions) — this guide assumes **Central India** until O11 is decided.

> ⚠️ **About the commands.** They are written for the Azure CLI in a **bash** shell (Azure Cloud Shell, WSL or Git Bash). Azure CLI flags change between versions. Commands marked **(verify)** use features whose names or availability vary by CLI version or region — if one fails, run it with `--help` and check the linked product's current docs. Never paste secrets into files that are committed.

---

## 0. What you will have at the end

```
Azure subscription (dev)
│
├─ rg-hb-dev-core   VNet 10.40/16 + NAT gateway (fixed outbound IP), private DNS zones,
│                   Key Vaults (platform secrets, tenant keys), two container registries,
│                   Log Analytics, Azure Monitor workspace, Managed Grafana, App Insights,
│                   managed identities, AI Foundry resource
├─ rg-hb-dev-data   Flexible Servers: control (hb_control, hb_gitea) and pool-01 (tenant DBs),
│                   Azure Managed Redis, Storage account (Blob)
├─ rg-hb-dev-aks    AKS cluster aks-hb-dev: pools system / platform / apps / sandbox (micro-VM)
└─ rg-hb-dev-edge   DNS zone azdev.hirebuddha.com, Front Door
```

Plus: workload identity for every platform service, Google federation for Gemini, GitHub Actions deploying with OIDC, and a verification checklist (§18).

Time needed: about one working day for someone comfortable with Azure, mostly waiting for resources.

---

## 1. Before you start

| Need | Why | How to check |
|------|-----|--------------|
| An Azure subscription for dev, and **Owner** on it (or Contributor + Role Based Access Control Administrator) | Creating resources and role assignments | `az role assignment list --assignee <you> --scope /subscriptions/<id>` |
| Permission to create **Entra ID groups** and **app registrations** (or an Entra admin who will do §5) | Admin groups, Postgres admin group | Entra admin center |
| vCPU quota in the region: Dsv5 family ≥ 32, total regional ≥ 40 | Node pools | `az vm list-usage -l centralindia -o table` |
| A DNS name you can delegate, e.g. `azdev.hirebuddha.com` | Dev hostnames without touching production DNS | Access to the current DNS provider of `hirebuddha.com` |
| Access to the GCP project used for Vertex AI (role to manage IAM and workload identity pools) | Gemini federation (§14) | `gcloud projects get-iam-policy <project>` |
| Admin on the GitHub repository and the GitHub organisation | Actions OIDC, GitHub App (§16) | GitHub settings |
| Tools: Azure CLI ≥ 2.65, `kubectl` + `kubelogin`, Helm 3, `jq`, `openssl`, `psql`, `gcloud` | Running this guide | `az version`; `az aks install-cli` installs kubectl and kubelogin |

Region choice (O11): confirm that **Central India** offers AKS Pod Sandboxing, Flexible Server PostgreSQL 16, Azure Managed Redis and (for Claude) Microsoft Foundry models. If one is missing, pick the region before continuing — changing later means recreating everything.

```bash
az account list-locations -o table | grep -i india
az provider show -n Microsoft.DBforPostgreSQL --query "resourceTypes[?resourceType=='flexibleServers'].locations" -o tsv | tr '\t' '\n' | grep -i india
```

---

## 2. Variables

Run once per shell. Keep `SUFFIX` — it makes global names unique; write it down.

```bash
export SUB_ID="<dev-subscription-id>"
export TENANT_ID="<entra-tenant-id>"
export LOCATION="centralindia"
export ENV="dev"
export PREFIX="hb"
export SUFFIX="<4 random hex chars, e.g. output of: openssl rand -hex 2>"

export RG_CORE="rg-$PREFIX-$ENV-core"
export RG_DATA="rg-$PREFIX-$ENV-data"
export RG_AKS="rg-$PREFIX-$ENV-aks"
export RG_EDGE="rg-$PREFIX-$ENV-edge"

export VNET="vnet-$PREFIX-$ENV"
export AKS="aks-$PREFIX-$ENV"
export KV="kv-$PREFIX-$ENV-$SUFFIX"            # platform secrets
export KV_TENANTS="kv-$PREFIX-$ENV-tk-$SUFFIX"  # tenant encryption keys
export ACR="acr$PREFIX$ENV$SUFFIX"             # platform images
export ACR_APPS="acr${PREFIX}apps$ENV$SUFFIX"  # tenant app images
export ST="st$PREFIX$ENV$SUFFIX"
export PG_CONTROL="psql-$PREFIX-$ENV-control"
export PG_POOL="psql-$PREFIX-$ENV-pool-01"
export REDIS="redis-$PREFIX-$ENV-$SUFFIX"
export LAW="log-$PREFIX-$ENV"
export AMW="amw-$PREFIX-$ENV"
export GRAFANA="graf-$PREFIX-$ENV-$SUFFIX"
export APPI="appi-$PREFIX-$ENV"
export AI="ai-$PREFIX-$ENV-$SUFFIX"
export DNS_ZONE="azdev.hirebuddha.com"
export PG_DNS_ZONE="$PREFIX-$ENV.private.postgres.database.azure.com"
```

Save the non-secret values in `infra/azure/env/dev.env` (create the folder) so teammates use the same names.

---

## 3. Sign in, extensions, resource providers

```bash
az login --tenant "$TENANT_ID"
az account set --subscription "$SUB_ID"

az extension add --upgrade --name amg                    # Managed Grafana
az extension add --upgrade --name application-insights
az extension add --upgrade --name redisenterprise        # Azure Managed Redis

for ns in Microsoft.ContainerService Microsoft.DBforPostgreSQL Microsoft.Cache Microsoft.KeyVault \
          Microsoft.ContainerRegistry Microsoft.Network Microsoft.OperationalInsights Microsoft.Insights \
          Microsoft.Monitor Microsoft.Dashboard Microsoft.Storage Microsoft.Cdn Microsoft.ManagedIdentity \
          Microsoft.AlertsManagement Microsoft.CognitiveServices Microsoft.App; do
  az provider register --namespace "$ns"
done
```

**AKS Pod Sandboxing (verify):** if it is still a preview feature for your CLI/region, also run:

```bash
az extension add --upgrade --name aks-preview
az feature register --namespace Microsoft.ContainerService --name KataVMIsolationPreview
az feature show --namespace Microsoft.ContainerService --name KataVMIsolationPreview --query properties.state   # wait for "Registered"
az provider register --namespace Microsoft.ContainerService
```

---

## 4. Resource groups and network

```bash
for rg in $RG_CORE $RG_DATA $RG_AKS $RG_EDGE; do
  az group create -n "$rg" -l "$LOCATION" --tags env=$ENV app=hirebuddha owner=platform
done

# VNet and subnets
az network vnet create -g $RG_CORE -n $VNET -l $LOCATION --address-prefixes 10.40.0.0/16 \
  --subnet-name snet-aks-nodes --subnet-prefixes 10.40.0.0/20
az network vnet subnet create -g $RG_CORE --vnet-name $VNET -n snet-pg --address-prefixes 10.40.16.0/24 \
  --delegations Microsoft.DBforPostgreSQL/flexibleServers
az network vnet subnet create -g $RG_CORE --vnet-name $VNET -n snet-pe --address-prefixes 10.40.17.0/24

# NAT gateway: every outbound call uses ONE fixed IP (for partner allow-lists)
az network public-ip create -g $RG_CORE -n pip-$PREFIX-$ENV-egress -l $LOCATION --sku Standard --allocation-method Static
az network nat gateway create -g $RG_CORE -n ng-$PREFIX-$ENV -l $LOCATION \
  --public-ip-addresses pip-$PREFIX-$ENV-egress --idle-timeout 10
az network vnet subnet update -g $RG_CORE --vnet-name $VNET -n snet-aks-nodes --nat-gateway ng-$PREFIX-$ENV

echo "Outbound IP for partners:" $(az network public-ip show -g $RG_CORE -n pip-$PREFIX-$ENV-egress --query ipAddress -o tsv)

# Static IP for the platform ingress (Front Door origin)
az network public-ip create -g $RG_CORE -n pip-$PREFIX-$ENV-ingress -l $LOCATION --sku Standard --allocation-method Static

# Handy IDs
export VNET_ID=$(az network vnet show -g $RG_CORE -n $VNET --query id -o tsv)
export SNET_AKS_ID=$(az network vnet subnet show -g $RG_CORE --vnet-name $VNET -n snet-aks-nodes --query id -o tsv)
export SNET_PG_ID=$(az network vnet subnet show -g $RG_CORE --vnet-name $VNET -n snet-pg --query id -o tsv)
export SNET_PE_ID=$(az network vnet subnet show -g $RG_CORE --vnet-name $VNET -n snet-pe --query id -o tsv)
```

---

## 5. Identity: groups and managed identities

```bash
for g in admins developers pg-admins; do
  az ad group create --display-name "grp-$PREFIX-$ENV-$g" --mail-nickname "grp-$PREFIX-$ENV-$g"
done
export ADMINS_ID=$(az ad group show -g "grp-$PREFIX-$ENV-admins" --query id -o tsv)
export DEVS_ID=$(az ad group show -g "grp-$PREFIX-$ENV-developers" --query id -o tsv)
export PGADMINS_ID=$(az ad group show -g "grp-$PREFIX-$ENV-pg-admins" --query id -o tsv)

ME=$(az ad signed-in-user show --query id -o tsv)
az ad group member add -g "grp-$PREFIX-$ENV-admins" --member-id "$ME"
az ad group member add -g "grp-$PREFIX-$ENV-pg-admins" --member-id "$ME"

# One managed identity per platform service (tech spec §5.2, §12.2)
for id in aks api worker connsvc provisioner migrator appcontroller ci; do
  az identity create -g $RG_CORE -n id-$PREFIX-$ENV-$id -l $LOCATION
done
pid() { az identity show -g $RG_CORE -n id-$PREFIX-$ENV-$1 --query principalId -o tsv; }
cid() { az identity show -g $RG_CORE -n id-$PREFIX-$ENV-$1 --query clientId -o tsv; }

# The provisioner creates databases and grants roles → member of the Postgres admin group
az ad group member add -g "grp-$PREFIX-$ENV-pg-admins" --member-id "$(pid provisioner)"
az ad group member add -g "grp-$PREFIX-$ENV-pg-admins" --member-id "$(pid migrator)"
```

Tenant Data API identities (`id-hb-dev-t-<key>`) are created per tenant by the Provisioner (WS2). Until it exists, §11.4 shows how to create the two dev tenants by hand.

---

## 6. Monitoring

```bash
az monitor log-analytics workspace create -g $RG_CORE -n $LAW -l $LOCATION --retention-time 30
export LAW_ID=$(az monitor log-analytics workspace show -g $RG_CORE -n $LAW --query id -o tsv)

az monitor account create -g $RG_CORE -n $AMW -l $LOCATION             # Azure Monitor workspace (managed Prometheus)
export AMW_ID=$(az monitor account show -g $RG_CORE -n $AMW --query id -o tsv)

az grafana create -g $RG_CORE -n $GRAFANA -l $LOCATION
export GRAFANA_ID=$(az grafana show -g $RG_CORE -n $GRAFANA --query id -o tsv)
az role assignment create --assignee-object-id $ADMINS_ID --assignee-principal-type Group --role "Grafana Admin" --scope $GRAFANA_ID
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group --role "Grafana Viewer" --scope $GRAFANA_ID

az monitor app-insights component create -g $RG_CORE -a $APPI -l $LOCATION --workspace $LAW_ID --kind web --application-type web
```

The App Insights connection string goes into Key Vault in §7 (`appinsights-connection-string`).

---

## 7. Key Vaults and platform secrets

```bash
az keyvault create -g $RG_CORE -n $KV -l $LOCATION \
  --enable-rbac-authorization true --enable-purge-protection true --retention-days 30
az keyvault create -g $RG_CORE -n $KV_TENANTS -l $LOCATION --sku premium \
  --enable-rbac-authorization true --enable-purge-protection true --retention-days 30
export KV_ID=$(az keyvault show -n $KV --query id -o tsv)
export KVT_ID=$(az keyvault show -n $KV_TENANTS --query id -o tsv)

# People
for scope in $KV_ID $KVT_ID; do
  az role assignment create --assignee-object-id $ADMINS_ID --assignee-principal-type Group --role "Key Vault Administrator" --scope $scope
done
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group --role "Key Vault Secrets User" --scope $KV_ID

# Workloads: read platform secrets
for id in api worker connsvc provisioner migrator appcontroller; do
  az role assignment create --assignee-object-id "$(pid $id)" --assignee-principal-type ServicePrincipal \
    --role "Key Vault Secrets User" --scope $KV_ID
done
# API signs Data API tokens with a Key Vault key
az role assignment create --assignee-object-id "$(pid api)" --assignee-principal-type ServicePrincipal --role "Key Vault Crypto User" --scope $KV_ID
# Tenant keys: Connection Service wraps/unwraps, Provisioner creates (tech spec §10.4)
az role assignment create --assignee-object-id "$(pid connsvc)" --assignee-principal-type ServicePrincipal --role "Key Vault Crypto User" --scope $KVT_ID
az role assignment create --assignee-object-id "$(pid provisioner)" --assignee-principal-type ServicePrincipal --role "Key Vault Crypto Officer" --scope $KVT_ID
```

Role assignments can take a few minutes to apply. Then seed the secrets the platform needs (values below are generated; third-party values come from each provider's **test/sandbox** account):

```bash
az keyvault secret set --vault-name $KV -n secret-key      --value "$(openssl rand -hex 32)" -o none
az keyvault secret set --vault-name $KV -n internal-token  --value "$(openssl rand -hex 32)" -o none
az keyvault key create --vault-name $KV -n data-api-signing --kty RSA --size 2048 -o none
az keyvault secret set --vault-name $KV -n appinsights-connection-string \
  --value "$(az monitor app-insights component show -g $RG_CORE -a $APPI --query connectionString -o tsv)" -o none
```

| Secret name | Content | Source |
|-------------|---------|--------|
| `razorpay-key-id`, `razorpay-key-secret`, `razorpay-webhook-secret` | Razorpay **test** keys | Razorpay dashboard (test mode) |
| `twilio-account-sid`, `twilio-auth-token` | Twilio test/sub-account | Twilio console |
| `tata-*` | Tata Tele sandbox credentials | Tata Tele |
| `smtp-*` | Dev SMTP | Mail provider |
| `azure-openai-endpoint` | Endpoint only (auth by managed identity) | §15 |
| `github-app-id`, `github-app-private-key`, `github-webhook-secret` | Dev GitHub App | §16 |
| `meta-app-id`, `meta-app-secret`, `linkedin-client-id`, `linkedin-client-secret`, `google-oauth-client-id`, `google-oauth-client-secret` | HireBuddha **dev** provider apps | Each provider's developer console |
| `pg-break-glass-password` | Postgres password admin (§10) | Generated |
| `redis-url` | Managed Redis URL with key (§11) | Generated |

Set third-party values from the portal or with `az keyvault secret set` on your own machine; never put them in shell history files or the repository.

---

## 8. Container registries and storage

```bash
az acr create -g $RG_CORE -n $ACR      -l $LOCATION --sku Standard --admin-enabled false
az acr create -g $RG_CORE -n $ACR_APPS -l $LOCATION --sku Standard --admin-enabled false
export ACR_ID=$(az acr show -n $ACR --query id -o tsv)
export ACR_APPS_ID=$(az acr show -n $ACR_APPS --query id -o tsv)
az role assignment create --assignee-object-id "$(pid ci)" --assignee-principal-type ServicePrincipal --role AcrPush --scope $ACR_ID
az role assignment create --assignee-object-id "$(pid appcontroller)" --assignee-principal-type ServicePrincipal --role Contributor --scope $ACR_APPS_ID   # runs ACR Tasks builds
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group --role AcrPush --scope $ACR_ID

# Storage (Blob) — no shared keys, no public blobs
az storage account create -g $RG_DATA -n $ST -l $LOCATION --sku Standard_LRS --kind StorageV2 \
  --min-tls-version TLS1_2 --allow-blob-public-access false --allow-shared-key-access false
az storage account blob-service-properties update -g $RG_DATA --account-name $ST \
  --enable-versioning true --enable-delete-retention true --delete-retention-days 14 \
  --enable-container-delete-retention true --container-delete-retention-days 14
export ST_ID=$(az storage account show -g $RG_DATA -n $ST --query id -o tsv)

az role assignment create --assignee-object-id $ADMINS_ID --assignee-principal-type Group --role "Storage Blob Data Owner" --scope $ST_ID
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group --role "Storage Blob Data Contributor" --scope $ST_ID
for id in api worker provisioner appcontroller connsvc; do
  az role assignment create --assignee-object-id "$(pid $id)" --assignee-principal-type ServicePrincipal \
    --role "Storage Blob Data Contributor" --scope $ST_ID
done
az storage container create --account-name $ST -n platform  --auth-mode login
az storage container create --account-name $ST -n migration --auth-mode login
```

In dev, Key Vault, ACR and Storage keep public endpoints protected by Entra RBAC (no keys). Staging and production use private endpoints (§20).

---

## 9. AKS cluster

### 9.1 Create

```bash
az role assignment create --assignee-object-id "$(pid aks)" --assignee-principal-type ServicePrincipal --role "Network Contributor" --scope $VNET_ID
az role assignment create --assignee-object-id "$(pid aks)" --assignee-principal-type ServicePrincipal --role "Network Contributor" \
  --scope $(az group show -n $RG_CORE --query id -o tsv)     # lets AKS use the static ingress IP in rg-core

az aks create -g $RG_AKS -n $AKS -l $LOCATION \
  --node-resource-group rg-$PREFIX-$ENV-aks-nodes \
  --tier free \
  --os-sku AzureLinux \
  --nodepool-name system --node-count 1 --node-vm-size Standard_D2s_v5 \
  --vnet-subnet-id $SNET_AKS_ID \
  --network-plugin azure --network-plugin-mode overlay --pod-cidr 192.168.0.0/16 \
  --service-cidr 172.16.0.0/16 --dns-service-ip 172.16.0.10 \
  --network-dataplane cilium --network-policy cilium \
  --outbound-type userAssignedNATGateway \
  --assign-identity $(az identity show -g $RG_CORE -n id-$PREFIX-$ENV-aks --query id -o tsv) \
  --enable-oidc-issuer --enable-workload-identity \
  --enable-aad --enable-azure-rbac --aad-admin-group-object-ids $ADMINS_ID \
  --attach-acr $ACR \
  --enable-addons monitoring,azure-keyvault-secrets-provider --workspace-resource-id $LAW_ID \
  --enable-azure-monitor-metrics --azure-monitor-workspace-resource-id $AMW_ID --grafana-resource-id $GRAFANA_ID \
  --enable-keda \
  --generate-ssh-keys

az aks update -g $RG_AKS -n $AKS --attach-acr $ACR_APPS
export AKS_ID=$(az aks show -g $RG_AKS -n $AKS --query id -o tsv)
export AKS_OIDC=$(az aks show -g $RG_AKS -n $AKS --query oidcIssuerProfile.issuerUrl -o tsv)
```

### 9.2 Node pools

```bash
az aks nodepool add -g $RG_AKS --cluster-name $AKS -n platform --mode User --os-sku AzureLinux \
  --node-vm-size Standard_D4s_v5 --enable-cluster-autoscaler --min-count 1 --max-count 4 \
  --labels hb/pool=platform --vnet-subnet-id $SNET_AKS_ID

az aks nodepool add -g $RG_AKS --cluster-name $AKS -n apps --mode User --os-sku AzureLinux \
  --node-vm-size Standard_D4s_v5 --enable-cluster-autoscaler --min-count 1 --max-count 4 \
  --labels hb/pool=apps --vnet-subnet-id $SNET_AKS_ID

# Sandbox pool: every pod in its own lightweight VM (Pod Sandboxing).  (verify)
# The runtime value has been "KataMshvVmIsolation" in older CLI versions and "KataVmIsolation" in newer ones;
# the VM size must support nested virtualization.
az aks nodepool add -g $RG_AKS --cluster-name $AKS -n sandbox --mode User --os-sku AzureLinux \
  --workload-runtime KataVmIsolation \
  --node-vm-size Standard_D4s_v5 --enable-cluster-autoscaler --min-count 1 --max-count 4 \
  --labels hb/pool=sandbox --node-taints hb/pool=sandbox:NoSchedule --vnet-subnet-id $SNET_AKS_ID

# Keep user workloads off the system pool
az aks nodepool update -g $RG_AKS --cluster-name $AKS -n system --node-taints CriticalAddonsOnly=true:NoSchedule
```

### 9.3 Access

```bash
az role assignment create --assignee-object-id $ADMINS_ID --assignee-principal-type Group \
  --role "Azure Kubernetes Service RBAC Cluster Admin" --scope $AKS_ID
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group \
  --role "Azure Kubernetes Service Cluster User Role" --scope $AKS_ID

az aks get-credentials -g $RG_AKS -n $AKS --overwrite-existing
kubelogin convert-kubeconfig -l azurecli
kubectl get nodes -L hb/pool
```

### 9.4 Namespaces, service accounts, workload identity

```bash
kubectl create namespace hb-platform
kubectl create namespace hb-system
kubectl label namespace hb-platform pod-security.kubernetes.io/enforce=baseline
kubectl label namespace hb-system   pod-security.kubernetes.io/enforce=baseline

for id in api worker connsvc provisioner migrator appcontroller; do
  kubectl -n hb-platform create serviceaccount sa-$id
  kubectl -n hb-platform annotate serviceaccount sa-$id azure.workload.identity/client-id="$(cid $id)" --overwrite
  az identity federated-credential create -g $RG_CORE --identity-name id-$PREFIX-$ENV-$id -n fc-$AKS-$id \
    --issuer "$AKS_OIDC" --subject "system:serviceaccount:hb-platform:sa-$id" --audiences api://AzureADTokenExchange
done

# Developers may deploy into hb-platform in dev
az role assignment create --assignee-object-id $DEVS_ID --assignee-principal-type Group \
  --role "Azure Kubernetes Service RBAC Writer" --scope "$AKS_ID/namespaces/hb-platform"
```

Pods that use an identity need the label `azure.workload.identity/use: "true"` and `serviceAccountName: sa-<id>`.

The Provisioner also needs Kubernetes rights to create tenant namespaces, quotas, network policies and service accounts. Give its service account a dedicated `ClusterRole` (namespaces, resourcequotas, limitranges, networkpolicies, serviceaccounts, deployments, services, secrets in `t-*`) through Kubernetes RBAC; the manifest ships with the `tenant-env` chart in WS2.

### 9.5 Cluster add-ons

```bash
helm repo add jetstack https://charts.jetstack.io && helm repo update
helm install cert-manager jetstack/cert-manager -n cert-manager --create-namespace --set crds.enabled=true

# Platform ingress (Gateway API, Envoy Gateway). Pin the current stable version from the project's releases.
helm install eg oci://docker.io/envoyproxy/gateway-helm --version <stable-version> -n envoy-gateway-system --create-namespace
```

Configure the Envoy Gateway's load-balancer Service to use the static IP from §4 with the annotations `service.beta.kubernetes.io/azure-load-balancer-resource-group: rg-hb-dev-core` and `service.beta.kubernetes.io/azure-pip-name: pip-hb-dev-ingress` (set through an `EnvoyProxy` resource). The tenant app edge (Caddy or Gateway API, spike SP-3) and the egress proxy are installed in WS6 and WS1.

---

## 10. PostgreSQL Flexible Server

### 10.1 Private DNS zone

```bash
az network private-dns zone create -g $RG_CORE -n $PG_DNS_ZONE
az network private-dns link vnet create -g $RG_CORE -z $PG_DNS_ZONE -n link-$VNET -v $VNET_ID -e false
export PG_DNS_ID=$(az network private-dns zone show -g $RG_CORE -n $PG_DNS_ZONE --query id -o tsv)
```

### 10.2 Servers

```bash
PG_PW="$(openssl rand -base64 30 | tr -d '/+=')"
az keyvault secret set --vault-name $KV -n pg-break-glass-password --value "$PG_PW" -o none

# Control plane (dev: burstable; prod: General Purpose with zone-redundant HA)
az postgres flexible-server create -g $RG_DATA -n $PG_CONTROL -l $LOCATION \
  --version 16 --tier Burstable --sku-name Standard_B2ms --storage-size 64 \
  --subnet $SNET_PG_ID --private-dns-zone $PG_DNS_ID \
  --microsoft-entra-auth Enabled --password-auth Enabled \
  --admin-user hbadmin --admin-password "$PG_PW" \
  --backup-retention 7 --yes

# Tenant pool server (General Purpose so built-in PgBouncer and realistic load tests work)
az postgres flexible-server create -g $RG_DATA -n $PG_POOL -l $LOCATION \
  --version 16 --tier GeneralPurpose --sku-name Standard_D2ds_v5 --storage-size 128 \
  --subnet $SNET_PG_ID --private-dns-zone $PG_DNS_ID \
  --microsoft-entra-auth Enabled --password-auth Enabled \
  --admin-user hbadmin --admin-password "$PG_PW" \
  --backup-retention 7 --yes
unset PG_PW
```

If your CLI version rejects `--microsoft-entra-auth`, it uses the older name `--active-directory-auth` **(verify)**.

### 10.3 Entra admin, extensions, PgBouncer, databases

```bash
for srv in $PG_CONTROL $PG_POOL; do
  az postgres flexible-server microsoft-entra-admin create -g $RG_DATA -s $srv \
    --display-name "grp-$PREFIX-$ENV-pg-admins" --object-id $PGADMINS_ID --type Group     # older CLI: "ad-admin create" (verify)
  az postgres flexible-server parameter set -g $RG_DATA --server-name $srv \
    --name azure.extensions --value "VECTOR,PGCRYPTO,PG_TRGM,UUID-OSSP,BTREE_GIN"
done
az postgres flexible-server parameter set -g $RG_DATA --server-name $PG_POOL --name pgbouncer.enabled --value true

az postgres flexible-server db create -g $RG_DATA -s $PG_CONTROL -d hb_control
az postgres flexible-server db create -g $RG_DATA -s $PG_CONTROL -d hb_gitea
az postgres flexible-server db create -g $RG_DATA -s $PG_POOL    -d t_devacme01
az postgres flexible-server db create -g $RG_DATA -s $PG_POOL    -d t_devbeta001
```

### 10.4 Connecting from your laptop (servers are private)

The servers have no public address. Reach them through a small forwarding pod in the cluster:

```bash
kubectl -n hb-system run pg-forward --image=alpine/socat --restart=Never -- \
  tcp-listen:5432,fork,reuseaddr tcp-connect:$PG_POOL.postgres.database.azure.com:5432
kubectl -n hb-system port-forward pod/pg-forward 15432:5432 &

export PGPASSWORD=$(az account get-access-token --resource-type oss-rdbms --query accessToken -o tsv)
psql "host=localhost port=15432 dbname=postgres user=grp-$PREFIX-$ENV-pg-admins sslmode=require"
```

(Members of an Entra admin group sign in with the **group name** as the user name and an Entra access token as the password.) Delete the pod when done: `kubectl -n hb-system delete pod pg-forward`.

### 10.5 Map workload identities to database roles

Connected to `postgres` on each server as the Entra admin:

```sql
-- once per server: Entra principals for the workloads
SELECT * FROM pgaadauth_create_principal('id-hb-dev-worker', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-api', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-connsvc', false, false);
SELECT * FROM pgaadauth_create_principal('id-hb-dev-migrator', false, false);

-- group roles used by the tech spec (§5.2)
CREATE ROLE hb_runtime  NOLOGIN;
CREATE ROLE hb_dataapi  NOLOGIN;
CREATE ROLE hb_migrator NOLOGIN;
GRANT hb_runtime  TO "id-hb-dev-worker", "id-hb-dev-api", "id-hb-dev-connsvc";
GRANT hb_migrator TO "id-hb-dev-migrator";
```

Schema-level grants (`platform`, `business`, `custom`) are created by the migrations in WS2 and are not run by hand.

### 10.6 Two dev tenants by hand (until the Provisioner exists)

```bash
for key in devacme01 devbeta001; do
  az identity create -g $RG_CORE -n id-$PREFIX-$ENV-t-$key -l $LOCATION
  az keyvault key create --vault-name $KV_TENANTS -n t-$key --kty RSA --size 3072 -o none
  az storage container create --account-name $ST -n t-$key --auth-mode login
  kubectl create namespace t-$key
  kubectl label namespace t-$key pod-security.kubernetes.io/enforce=restricted
  kubectl -n t-$key create serviceaccount data-api
  kubectl -n t-$key annotate serviceaccount data-api \
    azure.workload.identity/client-id="$(az identity show -g $RG_CORE -n id-$PREFIX-$ENV-t-$key --query clientId -o tsv)"
  az identity federated-credential create -g $RG_CORE --identity-name id-$PREFIX-$ENV-t-$key -n fc-data-api \
    --issuer "$AKS_OIDC" --subject "system:serviceaccount:t-$key:data-api" --audiences api://AzureADTokenExchange
  # key-scoped access: this tenant's Data API may use only its own key
  az role assignment create --assignee-object-id "$(az identity show -g $RG_CORE -n id-$PREFIX-$ENV-t-$key --query principalId -o tsv)" \
    --assignee-principal-type ServicePrincipal --role "Key Vault Crypto User" \
    --scope "$KVT_ID/keys/t-$key"
done
```

Then, on the pool server as Entra admin, in each tenant database:

```sql
SELECT * FROM pgaadauth_create_principal('id-hb-dev-t-devacme01', false, false);   -- run in postgres DB
GRANT hb_dataapi TO "id-hb-dev-t-devacme01";
-- and only CONNECT on its own database:
REVOKE CONNECT ON DATABASE t_devacme01 FROM PUBLIC;
GRANT  CONNECT ON DATABASE t_devacme01 TO "id-hb-dev-t-devacme01", hb_runtime, hb_migrator;
```

Repeat for `devbeta001`.

---

## 11. Azure Managed Redis

```bash
az redisenterprise create -g $RG_DATA -n $REDIS -l $LOCATION \
  --sku Balanced_B1 --minimum-tls-version 1.2 --clustering-policy EnterpriseCluster      # (verify) SKU names and policy options
export REDIS_ID=$(az redisenterprise show -g $RG_DATA -n $REDIS --query id -o tsv)

# Private endpoint + DNS
az network private-endpoint create -g $RG_DATA -n pe-$REDIS -l $LOCATION --subnet $SNET_PE_ID \
  --private-connection-resource-id $REDIS_ID --group-id redisEnterprise --connection-name pec-$REDIS
REDIS_ZONE="privatelink.redis.azure.net"        # (verify) private DNS zone name for Azure Managed Redis
az network private-dns zone create -g $RG_CORE -n $REDIS_ZONE
az network private-dns link vnet create -g $RG_CORE -z $REDIS_ZONE -n link-$VNET -v $VNET_ID -e false
az network private-endpoint dns-zone-group create -g $RG_DATA --endpoint-name pe-$REDIS -n default \
  --private-dns-zone $(az network private-dns zone show -g $RG_CORE -n $REDIS_ZONE --query id -o tsv) --zone-name redis

# Connection URL into Key Vault (host format and port 10000: verify in the resource's overview)
REDIS_HOST=$(az redisenterprise show -g $RG_DATA -n $REDIS --query hostName -o tsv)
REDIS_KEY=$(az redisenterprise database list-keys -g $RG_DATA --cluster-name $REDIS --query primaryKey -o tsv)
az keyvault secret set --vault-name $KV -n redis-url --value "rediss://:$REDIS_KEY@$REDIS_HOST:10000/0" -o none
unset REDIS_KEY
```

Spike SP-2 decides whether Arq works with this clustering policy. If it does not, recreate with the non-clustered option your SKU offers, or (temporary fallback) use Azure Cache for Redis Standard C1: `az redis create -g $RG_DATA -n redis-$PREFIX-$ENV-c -l $LOCATION --sku Standard --vm-size c1`.

---

## 12. DNS and Front Door

```bash
az network dns zone create -g $RG_EDGE -n $DNS_ZONE
az network dns zone show -g $RG_EDGE -n $DNS_ZONE --query nameServers -o tsv
```

Add those name servers as **NS records for `azdev`** at the current DNS provider of `hirebuddha.com`. Production DNS is not touched.

```bash
INGRESS_IP=$(az network public-ip show -g $RG_CORE -n pip-$PREFIX-$ENV-ingress --query ipAddress -o tsv)
az network dns record-set a add-record -g $RG_EDGE -z $DNS_ZONE -n origin -a $INGRESS_IP

az afd profile create -g $RG_EDGE --profile-name afd-$PREFIX-$ENV --sku Standard_AzureFrontDoor
az afd endpoint create -g $RG_EDGE --profile-name afd-$PREFIX-$ENV --endpoint-name ep-$PREFIX-$ENV-$SUFFIX --enabled-state Enabled
az afd origin-group create -g $RG_EDGE --profile-name afd-$PREFIX-$ENV --origin-group-name og-platform \
  --probe-request-type GET --probe-protocol Https --probe-path /health --probe-interval-in-seconds 60 \
  --sample-size 4 --successful-samples-required 3 --additional-latency-in-milliseconds 50
az afd origin create -g $RG_EDGE --profile-name afd-$PREFIX-$ENV --origin-group-name og-platform --origin-name aks-ingress \
  --host-name origin.$DNS_ZONE --origin-host-header origin.$DNS_ZONE --http-port 80 --https-port 443 --priority 1 --weight 1000 --enabled-state Enabled

ZONE_ID=$(az network dns zone show -g $RG_EDGE -n $DNS_ZONE --query id -o tsv)
for host in app api gateway connect; do
  az afd custom-domain create -g $RG_EDGE --profile-name afd-$PREFIX-$ENV --custom-domain-name cd-$host \
    --host-name $host.$DNS_ZONE --certificate-type ManagedCertificate --minimum-tls-version TLS12 --azure-dns-zone $ZONE_ID
done
```

Then create one route on the endpoint linking the four custom domains to `og-platform` (HTTPS only, redirect HTTP), and CNAME records `app`, `api`, `gateway`, `connect` → the Front Door endpoint host name (`az afd endpoint show … --query hostName`). The platform ingress needs a certificate for `origin.$DNS_ZONE` (cert-manager with a DNS-01 Azure DNS issuer, or Let's Encrypt HTTP-01).

Spike SP-7 checks the telephony WebSockets through Front Door; if they misbehave, point `gateway.$DNS_ZONE` directly at the ingress IP instead of Front Door.

Tenant apps: `*.apps.$DNS_ZONE` will point at the tenant app edge IP created in WS6.

---

## 13. AI models on Azure

```bash
az cognitiveservices account create -g $RG_CORE -n $AI -l <region-with-the-models> \
  --kind AIServices --sku S0 --custom-domain $AI --yes
AI_ID=$(az cognitiveservices account show -g $RG_CORE -n $AI --query id -o tsv)
for id in api worker; do
  az role assignment create --assignee-object-id "$(pid $id)" --assignee-principal-type ServicePrincipal \
    --role "Cognitive Services User" --scope $AI_ID
done
```

* **GPT models:** deploy the models you use today (`az cognitiveservices account deployment create …` or the Foundry portal). Store the endpoint as `azure-openai-endpoint`.
* **Claude (spike SP-5):** in the Microsoft Foundry portal, open the model catalog, deploy the Claude models in a region that offers them, and note the endpoint and deployment names. If the region you need does not offer them, use Anthropic's API (key in Key Vault) until it does.

---

## 14. Google federation for Gemini (no key files)

Run with `gcloud` against the Vertex AI project (`GCP_PROJECT`, `GCP_PROJECT_NUMBER`):

```bash
gcloud iam workload-identity-pools create hb-azure-$ENV --project=$GCP_PROJECT --location=global \
  --display-name="HireBuddha Azure $ENV"

gcloud iam workload-identity-pools providers create-oidc aks-$ENV --project=$GCP_PROJECT --location=global \
  --workload-identity-pool=hb-azure-$ENV --issuer-uri="$AKS_OIDC" \
  --allowed-audiences="api://AzureADTokenExchange" --attribute-mapping="google.subject=assertion.sub"

gcloud iam service-accounts create hb-vertex-$ENV --project=$GCP_PROJECT
gcloud projects add-iam-policy-binding $GCP_PROJECT \
  --member="serviceAccount:hb-vertex-$ENV@$GCP_PROJECT.iam.gserviceaccount.com" --role="roles/aiplatform.user"

for sa in sa-api sa-worker; do
  gcloud iam service-accounts add-iam-policy-binding hb-vertex-$ENV@$GCP_PROJECT.iam.gserviceaccount.com \
    --project=$GCP_PROJECT --role="roles/iam.workloadIdentityUser" \
    --member="principal://iam.googleapis.com/projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/hb-azure-$ENV/subject/system:serviceaccount:hb-platform:$sa"
done

gcloud iam workload-identity-pools create-cred-config \
  projects/$GCP_PROJECT_NUMBER/locations/global/workloadIdentityPools/hb-azure-$ENV/providers/aks-$ENV \
  --service-account="hb-vertex-$ENV@$GCP_PROJECT.iam.gserviceaccount.com" \
  --credential-source-file=/var/run/secrets/azure/tokens/azure-identity-token \
  --output-file=google-wif-$ENV.json
```

`google-wif-dev.json` contains **no secret** (it only says where to find the pod's projected token). Store it as a ConfigMap in `hb-platform` and mount it; set `GOOGLE_WIF_CREDENTIAL_FILE` to its path (tech spec §12.4). Spike SP-4 confirms Gemini, Gemini Live and embeddings all work this way.

---

## 15. GitHub

### 15.1 Deploying from GitHub Actions (no stored Azure secret)

```bash
az identity federated-credential create -g $RG_CORE --identity-name id-$PREFIX-$ENV-ci -n gh-azure-$ENV \
  --issuer https://token.actions.githubusercontent.com \
  --subject "repo:<github-org>/hire-buddha-app:environment:azure-$ENV" --audiences api://AzureADTokenExchange
az role assignment create --assignee-object-id "$(pid ci)" --assignee-principal-type ServicePrincipal \
  --role "Azure Kubernetes Service Cluster User Role" --scope $AKS_ID
az role assignment create --assignee-object-id "$(pid ci)" --assignee-principal-type ServicePrincipal \
  --role "Azure Kubernetes Service RBAC Writer" --scope "$AKS_ID/namespaces/hb-platform"
```

In the GitHub repository create the environment **azure-dev** with variables `AZURE_CLIENT_ID` (= `cid ci`), `AZURE_TENANT_ID`, `AZURE_SUBSCRIPTION_ID`, `ACR_NAME`, `AKS_NAME`, `AKS_RESOURCE_GROUP`. Workflows use `azure/login` with OIDC, `az acr build` or `docker push`, then `helm upgrade --install`.

### 15.2 Dev GitHub App for tenant connections

In the GitHub organisation: **Settings → Developer settings → GitHub Apps → New GitHub App** named "HireBuddha Dev":

| Setting | Value |
|---------|-------|
| Callback / setup URL | `https://connect.azdev.hirebuddha.com/oauth/callback/github` |
| Webhook URL | `https://gateway.azdev.hirebuddha.com/webhook/provider/github` |
| Webhook secret | generate; store as `github-webhook-secret` |
| Repository permissions | Contents: read & write · Pull requests: read & write · Checks: read & write · Issues: read · Metadata: read |
| Events | Push, Pull request, Issues, Check suite, Installation |
| Where can it be installed | Any account (needed for tenants) |

Generate a private key and store it as `github-app-private-key`; store the App ID as `github-app-id`.

---

## 16. First deployment smoke test

```bash
# A pod that proves workload identity + Key Vault access
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata:
  name: wi-test
  namespace: hb-platform
  labels: { azure.workload.identity/use: "true" }
spec:
  serviceAccountName: sa-worker
  nodeSelector: { hb/pool: platform }
  containers:
  - name: az
    image: mcr.microsoft.com/azure-cli
    command: ["sleep", "3600"]
EOF
kubectl -n hb-platform exec -it wi-test -- bash -c \
  'az login --service-principal -u $AZURE_CLIENT_ID -t $AZURE_TENANT_ID --federated-token "$(cat $AZURE_FEDERATED_TOKEN_FILE)" -o none && az keyvault secret show --vault-name '"$KV"' -n internal-token --query name -o tsv'
kubectl -n hb-platform delete pod wi-test
```

```bash
# A micro-VM sandbox pod
cat <<'EOF' | kubectl apply -f -
apiVersion: v1
kind: Pod
metadata: { name: kata-test, namespace: t-devacme01 }
spec:
  runtimeClassName: kata-vm-isolation          # (verify) runtime class name created by Pod Sandboxing
  nodeSelector: { hb/pool: sandbox }
  tolerations: [{ key: hb/pool, operator: Equal, value: sandbox, effect: NoSchedule }]
  securityContext: { runAsNonRoot: true, runAsUser: 1000, seccompProfile: { type: RuntimeDefault } }
  containers:
  - name: c
    image: mcr.microsoft.com/azurelinux/base/core:3.0
    command: ["sh", "-c", "uname -r; sleep 600"]
    securityContext: { allowPrivilegeEscalation: false, capabilities: { drop: ["ALL"] } }
EOF
kubectl -n t-devacme01 logs kata-test     # kernel differs from the node's kernel → runs in its own VM
kubectl -n t-devacme01 delete pod kata-test
```

---

## 17. Developer workflow

* **Local first:** `docker compose up` in `backend/` (PostgreSQL 16 + Redis) and the usual services, as today. `scripts/dev_tenants.py` (WS2) creates `hb_control`, `t_devacme01`, `t_devbeta001` locally.
* **Azure dev:** merges to `main` deploy automatically. To inspect: `az aks get-credentials`, `kubectl -n hb-platform get pods`, logs in Log Analytics or `kubectl logs`.
* **Databases:** §10.4 port-forward; never open a public firewall rule.
* **Secrets:** read from Key Vault (`az keyvault secret show`) only when needed; never copy into `.env` files that might be committed.
* **Costs:** see §19.

---

## 18. Verification checklist

| # | Check | Expected |
|---|-------|----------|
| 1 | `kubectl get nodes -L hb/pool` | system, platform, apps, sandbox pools |
| 2 | Workload identity pod (§16) | Reads `internal-token` name from Key Vault |
| 3 | `kubectl run curl --rm -it --image=curlimages/curl -n hb-system -- curl -s https://ifconfig.me` | The NAT gateway IP from §4 |
| 4 | `psql` through port-forward (§10.4), then in `t_devacme01`: `CREATE EXTENSION IF NOT EXISTS vector;` | Succeeds |
| 5 | From a pod: `redis-cli -h <host> -p 10000 --tls -a <key> PING` | `PONG` |
| 6 | Kata pod (§16) | Pod runs on the sandbox pool; kernel differs from host |
| 7 | Pod with `GOOGLE_WIF_CREDENTIAL_FILE` mounted calls Vertex AI (a one-line `google-genai` request) | A Gemini answer, no key file |
| 8 | `https://app.azdev.hirebuddha.com/health` after the first deployment | 200 through Front Door |
| 9 | GitHub Actions run on `main` | Image in ACR, release in `hb-platform` |
| 10 | Managed Grafana shows Kubernetes dashboards; Log Analytics has container logs | Data present |

Record every resource name and ID in `infra/azure/env/dev.env` (non-secret) and tell the team which spikes (SP-1…SP-10) are unblocked.

---

## 19. Keeping dev costs down

* Stop when not in use: `az aks stop -g $RG_AKS -n $AKS` / `az aks start …`; `az postgres flexible-server stop -g $RG_DATA -n <server>` (Azure restarts a stopped server automatically after 7 days).
* Autoscaler minimums are 1; the sandbox pool can be set to `--min-count 0` once SP-1 is done.
* Front Door Standard and Managed Redis cost money even when idle; delete and recreate them in dev if they will be idle for long.
* Create a monthly **budget with alerts** on the subscription (Cost Management → Budgets) and tag everything `env=dev`.

---

## 20. Staging and production: what is different

| Area | Dev (this guide) | Staging / production (from IaC, WS0) |
|------|------------------|---------------------------------------|
| Subscriptions | One dev subscription | Production in its own subscription; staging may share a non-prod subscription |
| VNet | 10.40/16 | 10.41/16 (staging), 10.42/16 (prod) |
| Key Vault, Storage, ACR | Public endpoints + RBAC | **Private endpoints**; ACR Premium (private link, geo-replication); public access disabled |
| AKS | Free tier, single zone, public API server | Standard tier (uptime SLA), node pools across 3 zones, API server VNet integration or authorised IP ranges |
| PostgreSQL | Burstable control, 1 pool server, 7-day backups | General Purpose with zone-redundant HA, several pool servers, 35-day PITR, geo-redundant backup |
| Redis | One instance | Zone-redundant, sized from load tests |
| Storage | LRS | ZRS or GZRS |
| Front Door | Standard | Premium with WAF managed rules |
| Security | Basics | Microsoft Defender for Cloud, Azure Policy for AKS (allowed registries, no privileged pods), diagnostic settings for every resource, break-glass accounts, alerts to on-call |
| Domains | `*.azdev.hirebuddha.com` | Staging: `*.staging.hirebuddha.com`; production: today's `app.`, `api.`, `gateway.` hostnames at switch-over (WS9) |

---

## 21. Troubleshooting

| Symptom | Likely cause | Fix |
|---------|--------------|-----|
| `AuthorizationFailed` right after a role assignment | Propagation delay | Wait 5–10 minutes and retry |
| AKS create fails on outbound type | NAT gateway not attached to the node subnet, or AKS identity lacks Network Contributor | Re-run the subnet update and role assignment in §4/§9.1 |
| Pods cannot resolve `*.postgres.database.azure.com` | Private DNS zone not linked to the VNet | §10.1 link command |
| `password authentication failed` with Entra | Token expired (≈1 h) or wrong user name | Fetch a new token; group members use the group name as user |
| Kata pod stays `Pending` | Wrong runtime class name, missing toleration, or VM size without nested virtualization | `kubectl get runtimeclass`; check §9.2 notes |
| Workload identity pod has no `AZURE_FEDERATED_TOKEN_FILE` | Missing pod label or service-account annotation | Label `azure.workload.identity/use: "true"`; annotate the service account |
| Front Door custom domain stuck "Pending" | Validation TXT record missing or NS delegation not done | Check the `azdev` NS records at the parent DNS provider |
| Google federation `invalid_grant` | Audience or issuer mismatch | Provider `--allowed-audiences` must be `api://AzureADTokenExchange` and the issuer must equal `$AKS_OIDC` exactly |

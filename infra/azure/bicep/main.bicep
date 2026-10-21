// HireBuddha Azure environment (Phase 14 WS0 0.2), built in slices
// (implementation plan WS0, "Dev environment in slices"):
//
// * Slice 1, Foundation — the Azure setup guide (docs/phase14/04_*) §4–§11 as
//   code: resource groups, network with a fixed egress IP, monitoring,
//   workload identities, platform Key Vault, platform registry, Blob storage,
//   AKS (system + platform pools), the control-plane Flexible Server and
//   Azure Managed Redis.
// * Slice 2, Tenancy (deployTenancy) — the tenant pool server, the
//   tenant-keys vault and the resource group of the tenants' own identities,
//   with the provisioner's rights on each (tech spec §5.1, §5.2, §10.4).
//
// * Working hours (scheduleEnabled; dev) — the cluster and the PostgreSQL
//   servers stop outside them (two Logic Apps; budget).
// * Budget (budgetAmount) — a monthly cost budget with e-mail alerts (D50).
// * Promotion (promotionSourceRegistry) — this environment's CI identity may
//   read another environment's registry, so production deploys the images dev
//   ran (D51).
//
// Later slices (public entry, tenant runtime, observability extras) add
// modules here; each is codified before it is built.
//
//   az deployment sub what-if  -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/dev.bicepparam
//   az deployment sub create   -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/dev.bicepparam
//
// Entra groups (admins, developers, pg-admins) are created outside this
// template (they are directory objects, guide §5); their object ids come in
// as parameters.

targetScope = 'subscription'

@description('Environment: dev, staging or prod.')
@allowed(['dev', 'staging', 'prod'])
param env string

@description('Azure region (open item O11; the guide assumes Central India).')
param location string = 'centralindia'

@description('Name prefix of every resource.')
param prefix string = 'hb'

@description('4 lowercase hex characters that make global names unique (guide §2). Keep it.')
@minLength(4)
@maxLength(4)
param suffix string

@description('VNet address space; dev 10.40/16, staging 10.41/16, prod 10.42/16 (tech spec §4.1).')
param vnetAddressPrefix string = '10.40.0.0/16'

@description('Object id of the Entra group grp-<prefix>-<env>-admins.')
param adminsGroupObjectId string

@description('Object id of the Entra group grp-<prefix>-<env>-developers.')
param developersGroupObjectId string

@description('Object id and display name of the Entra group that administers PostgreSQL.')
param pgAdminsGroupObjectId string
param pgAdminsGroupName string

@description('GitHub repository (owner/name) whose environment azure-<env> may deploy (guide §15.1).')
param githubRepository string

@description('The same repository with GitHub\'s immutable ids (owner@<owner id>/name@<repo id>), as its OIDC subjects now name it.')
param githubRepositoryIds string = ''

@description('Break-glass password of the PostgreSQL administrator; workloads use Entra tokens.')
@secure()
param pgBreakGlassPassword string

@description('Tags on every resource group.')
param tags object = {}

@description('AKS node sizes and counts.')
param systemPoolVmSize string = 'Standard_D2s_v5'
param platformPoolVmSize string = 'Standard_D4s_v5'
param platformPoolMinCount int = 1
param platformPoolMaxCount int = 4

@description('Flexible Server SKU of the control server (dev: burstable).')
param controlServerSku object = {
  name: 'Standard_B2s'
  tier: 'Burstable'
}

@description('Slice 2: the tenant pool server, tenant-keys vault and tenant identities.')
param deployTenancy bool = false

@description('Flexible Server SKU of the tenant pool server (General Purpose: built-in PgBouncer, SP-6).')
param poolServerSku object = {
  name: 'Standard_D2ds_v5'
  tier: 'GeneralPurpose'
}

@description('Tenant-keys vault SKU: premium for HSM-backed KEKs (TENANT_KEK_HSM).')
@allowed(['standard', 'premium'])
param tenantKeysVaultSku string = 'standard'

@description('Stop the cluster and the PostgreSQL servers outside working hours (dev).')
param scheduleEnabled bool = false
param scheduleWeekDays array = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
@minValue(0)
@maxValue(23)
param scheduleStartHour int = 9
@minValue(0)
@maxValue(23)
param scheduleStopHour int = 21
param scheduleTimeZone string = 'India Standard Time'

@description('Azure Managed Redis SKU (dev: no HA).')
param redisSku string = 'Balanced_B0'

@description('Redis clustering policy. Spike SP-2: arq transactions need NoCluster (a cache of 25 GB or less).')
@allowed(['NoCluster', 'EnterpriseCluster', 'OSSCluster'])
param redisClusteringPolicy string = 'NoCluster'

@description('AKS tier: Free (no uptime SLA) or Standard. D49: production starts on Free, as dev.')
@allowed(['Free', 'Standard'])
param aksTier string = 'Free'

@description('Zone-redundant HA for the PostgreSQL servers. Burstable servers cannot have it (D49: production starts on Burstable).')
param databaseHighAvailability bool = env == 'prod'

@description('Geo-redundant backups for the PostgreSQL servers.')
param databaseGeoRedundantBackup bool = env == 'prod'

@description('Redis high availability (a replica).')
param redisHighAvailability bool = env == 'prod'

@description('Monthly cost budget for this environment\'s resource groups (0: none). D50.')
param budgetAmount int = 0

@description('Who gets the budget alerts.')
param budgetContactEmails array = []

@description('First day of the month the budget starts.')
param budgetStartDate string = utcNow('yyyy-MM-01')

@description('Another environment\'s registry this environment\'s CI identity may read: {subscriptionId, resourceGroup, name}; empty for none. D51: production imports dev\'s images.')
param promotionSourceRegistry object = {}

var names = {
  rgCore: 'rg-${prefix}-${env}-core'
  rgData: 'rg-${prefix}-${env}-data'
  rgAks: 'rg-${prefix}-${env}-aks'
  vnet: 'vnet-${prefix}-${env}'
  aks: 'aks-${prefix}-${env}'
  kv: 'kv-${prefix}-${env}-${suffix}'
  acr: 'acr${prefix}${env}${suffix}'
  storage: 'st${prefix}${env}${suffix}'
  pgControl: 'psql-${prefix}-${env}-control'
  pgDnsZone: '${prefix}-${env}.private.postgres.database.azure.com'
  redis: 'redis-${prefix}-${env}-${suffix}'
  rgTenants: 'rg-${prefix}-${env}-tenants'
  pgPool: 'psql-${prefix}-${env}-pool-01'
  kvTenantKeys: 'kv-${prefix}-${env}-tk-${suffix}'
  law: 'log-${prefix}-${env}'
  appi: 'appi-${prefix}-${env}'
}

var rgTags = union(tags, { env: env, app: 'hirebuddha', owner: 'platform' })

resource rgCore 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: names.rgCore
  location: location
  tags: rgTags
}

resource rgData 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: names.rgData
  location: location
  tags: rgTags
}

resource rgAks 'Microsoft.Resources/resourceGroups@2024-03-01' = {
  name: names.rgAks
  location: location
  tags: rgTags
}

module network 'modules/network.bicep' = {
  scope: rgCore
  name: 'network'
  params: {
    location: location
    prefix: prefix
    env: env
    vnetName: names.vnet
    addressPrefix: vnetAddressPrefix
  }
}

module monitoring 'modules/monitoring.bicep' = {
  scope: rgCore
  name: 'monitoring'
  params: {
    location: location
    workspaceName: names.law
    appInsightsName: names.appi
  }
}

module identities 'modules/identities.bicep' = {
  scope: rgCore
  name: 'identities'
  params: {
    location: location
    prefix: prefix
    env: env
  }
}

module keyVault 'modules/keyvault.bicep' = {
  scope: rgCore
  name: 'keyvault'
  params: {
    location: location
    name: names.kv
    adminsGroupObjectId: adminsGroupObjectId
    developersGroupObjectId: developersGroupObjectId
    secretReaderPrincipalIds: identities.outputs.platformPrincipalIds
    cryptoUserPrincipalIds: [identities.outputs.principalIds.api]
    appInsightsConnectionString: monitoring.outputs.appInsightsConnectionString
  }
}

module registry 'modules/registry.bicep' = {
  scope: rgCore
  name: 'registry'
  params: {
    location: location
    name: names.acr
    pushPrincipalIds: [identities.outputs.principalIds.ci]
    developersGroupObjectId: developersGroupObjectId
  }
}

module storage 'modules/storage.bicep' = {
  scope: rgData
  name: 'storage'
  params: {
    location: location
    name: names.storage
    adminsGroupObjectId: adminsGroupObjectId
    developersGroupObjectId: developersGroupObjectId
    dataContributorPrincipalIds: [
      identities.outputs.principalIds.api
      identities.outputs.principalIds.worker
      identities.outputs.principalIds.provisioner
      identities.outputs.principalIds.appcontroller
      identities.outputs.principalIds.connsvc
    ]
  }
}

// Before the cluster: its control-plane identity joins the node subnet and NAT gateway.
module aksNetworkAccess 'modules/aks-network-access.bicep' = {
  scope: rgCore
  name: 'aks-network-access'
  params: {
    controlPlanePrincipalId: identities.outputs.principalIds.aks
  }
  dependsOn: [network]
}

module aks 'modules/aks.bicep' = {
  scope: rgAks
  name: 'aks'
  dependsOn: [aksNetworkAccess]
  params: {
    location: location
    name: names.aks
    nodeResourceGroup: 'rg-${prefix}-${env}-aks-nodes'
    nodeSubnetId: network.outputs.aksNodeSubnetId
    controlPlaneIdentityId: identities.outputs.ids.aks
    logAnalyticsWorkspaceId: monitoring.outputs.workspaceId
    adminsGroupObjectId: adminsGroupObjectId
    systemPoolVmSize: systemPoolVmSize
    platformPoolVmSize: platformPoolVmSize
    platformPoolMinCount: platformPoolMinCount
    platformPoolMaxCount: platformPoolMaxCount
    tier: aksTier
  }
}

// After the cluster: its kubelet identity pulls from the platform registry,
// and GitHub Actions may deploy to it.
module aksAccess 'modules/aks-access.bicep' = {
  scope: rgCore
  name: 'aks-access'
  params: {
    acrName: names.acr
    kubeletPrincipalId: aks.outputs.kubeletPrincipalId
  }
  dependsOn: [registry]
}

module aksCiAccess 'modules/aks-ci-access.bicep' = {
  scope: rgAks
  name: 'aks-ci-access'
  params: {
    clusterName: aks.outputs.name
    ciPrincipalId: identities.outputs.principalIds.ci
  }
}

module workloadFederation 'modules/federation.bicep' = {
  scope: rgCore
  name: 'federation'
  params: {
    prefix: prefix
    env: env
    oidcIssuerUrl: aks.outputs.oidcIssuerUrl
    namespace: 'hb-platform'
    githubRepository: githubRepository
    githubRepositoryIds: githubRepositoryIds
  }
  // The identities it federates are looked up by name; they exist once the
  // cluster does (its control plane uses one), which oidcIssuerUrl waits for.
}

module postgres 'modules/postgres.bicep' = {
  scope: rgData
  name: 'postgres-control'
  params: {
    location: location
    serverName: names.pgControl
    dnsZoneName: names.pgDnsZone
    vnetId: network.outputs.vnetId
    delegatedSubnetId: network.outputs.postgresSubnetId
    sku: controlServerSku
    entraAdminObjectId: pgAdminsGroupObjectId
    entraAdminName: pgAdminsGroupName
    breakGlassPassword: pgBreakGlassPassword
    databases: ['hb_control', 'hb_gitea']
    highAvailability: databaseHighAvailability
    // Decision D45: weekly exports (hb-backup CronJob) beside point-in-time restore at its minimum.
    backupRetentionDays: 7
    geoRedundantBackup: databaseGeoRedundantBackup
  }
}

module redis 'modules/redis.bicep' = {
  scope: rgData
  name: 'redis'
  params: {
    location: location
    name: names.redis
    sku: redisSku
    clusteringPolicy: redisClusteringPolicy
    privateEndpointSubnetId: network.outputs.privateEndpointSubnetId
    vnetId: network.outputs.vnetId
    highAvailability: redisHighAvailability
  }
}

// ── Slice 2: tenancy ───────────────────────────────────────────────────────

resource rgTenants 'Microsoft.Resources/resourceGroups@2024-03-01' = if (deployTenancy) {
  name: names.rgTenants
  location: location
  tags: rgTags
}

// Tenant databases (t_<key>) live here; the provisioner is an Entra admin of
// it (create database, extensions, roles). Same subnet and private DNS zone as
// the control server, which it waits for (the zone is declared by both).
module postgresPool 'modules/postgres.bicep' = if (deployTenancy) {
  scope: rgData
  name: 'postgres-pool-01'
  params: {
    location: location
    serverName: names.pgPool
    dnsZoneName: names.pgDnsZone
    vnetId: network.outputs.vnetId
    delegatedSubnetId: network.outputs.postgresSubnetId
    sku: poolServerSku
    entraAdminObjectId: pgAdminsGroupObjectId
    entraAdminName: pgAdminsGroupName
    additionalAdmins: [
      { objectId: identities.outputs.principalIds.provisioner, name: 'id-${prefix}-${env}-provisioner' }
    ]
    breakGlassPassword: pgBreakGlassPassword
    databases: []
    highAvailability: databaseHighAvailability
    backupRetentionDays: 7  // D45, as the control server
    geoRedundantBackup: databaseGeoRedundantBackup
    enablePgBouncer: poolServerSku.tier != 'Burstable'
  }
  dependsOn: [postgres]
}

module tenantKeys 'modules/tenantkeys.bicep' = if (deployTenancy) {
  scope: rgCore
  name: 'tenant-keys'
  params: {
    location: location
    name: names.kvTenantKeys
    skuName: tenantKeysVaultSku
    adminsGroupObjectId: adminsGroupObjectId
    cryptoOfficerPrincipalIds: [identities.outputs.principalIds.provisioner]
    cryptoUserPrincipalIds: [
      identities.outputs.principalIds.api
      identities.outputs.principalIds.worker
      identities.outputs.principalIds.connsvc
    ]
  }
}

module tenantIdentitiesAccess 'modules/tenant-identities-access.bicep' = if (deployTenancy) {
  scope: rgTenants
  name: 'tenant-identities-access'
  params: {
    provisionerPrincipalId: identities.outputs.principalIds.provisioner
  }
}

// ── Working hours ─────────────────────────────────────────────────────────

var scheduledServers = deployTenancy ? [names.pgControl, names.pgPool] : [names.pgControl]

module scheduleRole 'modules/dev-schedule-role.bicep' = if (scheduleEnabled) {
  name: 'schedule-role'
  params: {
    prefix: prefix
    env: env
  }
}

module schedule 'modules/dev-schedule.bicep' = if (scheduleEnabled) {
  scope: rgCore
  name: 'schedule'
  params: {
    location: location
    prefix: prefix
    env: env
    aksId: aks.outputs.id
    postgresServerIds: [for server in scheduledServers: resourceId(subscription().subscriptionId, names.rgData, 'Microsoft.DBforPostgreSQL/flexibleServers', server)]
    timeZone: scheduleTimeZone
    weekDays: scheduleWeekDays
    startHour: scheduleStartHour
    stopHour: scheduleStopHour
  }
  dependsOn: [postgres, postgresPool]
}

module scheduleAksAccess 'modules/dev-schedule-access.bicep' = if (scheduleEnabled) {
  scope: rgAks
  name: 'schedule-access-aks'
  params: {
    roleDefinitionId: scheduleRole!.outputs.roleDefinitionId
    principalIds: schedule!.outputs.principalIds
    aksName: names.aks
  }
}

module scheduleDataAccess 'modules/dev-schedule-access.bicep' = if (scheduleEnabled) {
  scope: rgData
  name: 'schedule-access-data'
  params: {
    roleDefinitionId: scheduleRole!.outputs.roleDefinitionId
    principalIds: schedule!.outputs.principalIds
    postgresServerNames: scheduledServers
  }
}

// ── Budget (D50) and image promotion (D51) ──────────────────────────────────

module budget 'modules/budget.bicep' = if (budgetAmount > 0) {
  name: 'budget'
  params: {
    name: 'budget-${prefix}-${env}-monthly'
    amount: budgetAmount
    contactEmails: budgetContactEmails
    startDate: budgetStartDate
    // Only this environment's spend: production shares the subscription with dev.
    resourceGroups: [names.rgCore, names.rgData, names.rgAks, 'rg-${prefix}-${env}-aks-nodes', names.rgTenants]
  }
}

module promotionSourceAccess 'modules/registry-pull.bicep' = if (!empty(promotionSourceRegistry)) {
  scope: resourceGroup(promotionSourceRegistry.?subscriptionId ?? subscription().subscriptionId,
    promotionSourceRegistry.?resourceGroup ?? '')
  name: 'promotion-source-pull'
  params: {
    registryName: promotionSourceRegistry.?name ?? ''
    principalIds: [identities.outputs.principalIds.ci]
  }
}

// Values the next steps need (guide §2: record them in infra/azure/env/<env>.env).
output resourceGroups object = {
  core: rgCore.name
  data: rgData.name
  aks: rgAks.name
}
output egressIp string = network.outputs.egressIpAddress
output ingressIpName string = network.outputs.ingressIpName
output keyVaultName string = keyVault.outputs.name
output keyVaultUri string = keyVault.outputs.uri
output acrLoginServer string = registry.outputs.loginServer
output storageBlobEndpoint string = storage.outputs.blobEndpoint
output aksName string = aks.outputs.name
output aksOidcIssuerUrl string = aks.outputs.oidcIssuerUrl
output postgresControlFqdn string = postgres.outputs.fqdn
output redisHostName string = redis.outputs.hostName
output identityClientIds object = identities.outputs.clientIds
output postgresPoolFqdn string = deployTenancy ? postgresPool!.outputs.fqdn : ''
output tenantKeysVaultUri string = deployTenancy ? tenantKeys!.outputs.uri : ''
output tenantIdentitiesResourceGroup string = deployTenancy ? names.rgTenants : ''

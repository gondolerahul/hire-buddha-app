// Azure production — slices 1 and 2, the same size as dev (decision D49, owner 21 Oct 2026).
// In dev's subscription (owner, 21 Oct 2026), beside it: its own resource groups
// (rg-hb-prod-*), VNet and names. Directory object ids, the break-glass password
// and the alert address come from the environment of whoever deploys:
//   export HB_ADMINS_GROUP_ID=...  HB_DEVELOPERS_GROUP_ID=...
//   export HB_PGADMINS_GROUP_ID=...  HB_PG_BREAK_GLASS_PASSWORD=$(openssl rand -base64 32)
//   export HB_BUDGET_EMAIL=...
//   az deployment sub what-if -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/prod.bicepparam
using '../bicep/main.bicep'

param env = 'prod'
param location = 'centralindia'
param prefix = 'hb'
param suffix = 'e7b3'   // names that must be unique in Azure (Key Vault, registry, storage)
param vnetAddressPrefix = '10.42.0.0/16'

param adminsGroupObjectId = readEnvironmentVariable('HB_ADMINS_GROUP_ID')
param developersGroupObjectId = readEnvironmentVariable('HB_DEVELOPERS_GROUP_ID')
param pgAdminsGroupObjectId = readEnvironmentVariable('HB_PGADMINS_GROUP_ID')
param pgAdminsGroupName = 'grp-hb-prod-pg-admins'
param pgBreakGlassPassword = readEnvironmentVariable('HB_PG_BREAK_GLASS_PASSWORD')

param githubRepository = readEnvironmentVariable('HB_GITHUB_REPOSITORY', 'gondolerahul/hire-buddha-app')
param githubRepositoryIds = 'gondolerahul@158562688/hire-buddha-app@1332013197'   // GitHub's OIDC subject (ids)

// D49: dev's sizes. AKS Free tier (no uptime SLA), one zone; Burstable databases
// (no HA, no read replicas, no built-in PgBouncer); no Front Door or Defender.
param aksTier = 'Free'
param systemPoolVmSize = 'Standard_D2s_v5'
param platformPoolVmSize = 'Standard_D4s_v5'
param platformPoolMinCount = 1
param platformPoolMaxCount = 2              // D50: the autoscaler's cap
param controlServerSku = {
  name: 'Standard_B2s'
  tier: 'Burstable'
}
param redisSku = 'Balanced_B0'
param redisClusteringPolicy = 'NoCluster'   // SP-2
param databaseHighAvailability = false      // Burstable cannot have it
param databaseGeoRedundantBackup = false    // D49: as dev; D45's weekly exports go to Blob
param redisHighAvailability = false

param deployTenancy = true
param poolServerSku = {
  name: 'Standard_B2s'
  tier: 'Burstable'
}
param tenantKeysVaultSku = 'standard'

// Production runs around the clock (no working hours).
param scheduleEnabled = false

// D50: budget alerts at 80 % / 100 % actual and 100 % forecast, on production's
// resource groups only. About ₹50,000 a month at list price around the clock;
// lower once the reservations apply.
param budgetAmount = 55000
param budgetContactEmails = [readEnvironmentVariable('HB_BUDGET_EMAIL')]

// D51: production's CI identity reads dev's registry and imports the images dev ran.
param promotionSourceRegistry = {
  resourceGroup: 'rg-hb-dev-core'   // same subscription
  name: 'acrhbdevac48'
}

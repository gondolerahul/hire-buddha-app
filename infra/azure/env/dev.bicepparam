// Azure dev — slice 1 (Phase 14 WS0 0.3). Names follow the setup guide (§2).
// Directory object ids and the break-glass password come from the environment
// of whoever deploys, never from this file:
//   export HB_SUFFIX=<4 hex>  HB_ADMINS_GROUP_ID=...  HB_DEVELOPERS_GROUP_ID=...
//   export HB_PGADMINS_GROUP_ID=...  HB_PG_BREAK_GLASS_PASSWORD=$(openssl rand -base64 32)
//   az deployment sub what-if -l centralindia -f infra/azure/bicep/main.bicep -p infra/azure/env/dev.bicepparam
using '../bicep/main.bicep'

param env = 'dev'
param location = 'centralindia'
param prefix = 'hb'
param suffix = readEnvironmentVariable('HB_SUFFIX')
param vnetAddressPrefix = '10.40.0.0/16'

param adminsGroupObjectId = readEnvironmentVariable('HB_ADMINS_GROUP_ID')
param developersGroupObjectId = readEnvironmentVariable('HB_DEVELOPERS_GROUP_ID')
param pgAdminsGroupObjectId = readEnvironmentVariable('HB_PGADMINS_GROUP_ID')
param pgAdminsGroupName = 'grp-hb-dev-pg-admins'
param pgBreakGlassPassword = readEnvironmentVariable('HB_PG_BREAK_GLASS_PASSWORD')

param githubRepository = readEnvironmentVariable('HB_GITHUB_REPOSITORY', 'gondolerahul/hire-buddha-app')
param githubRepositoryIds = 'gondolerahul@158562688/hire-buddha-app@1332013197'   // GitHub's OIDC subject (ids)

// Dev sizes (≈ $550/month for slice 1, implementation plan WS0).
param systemPoolVmSize = 'Standard_D2s_v5'
param platformPoolVmSize = 'Standard_D4s_v5'
param platformPoolMinCount = 1
param platformPoolMaxCount = 3
param controlServerSku = {
  name: 'Standard_B2s'
  tier: 'Burstable'
}
param redisSku = 'Balanced_B0'
param redisClusteringPolicy = 'NoCluster'   // arq's WATCH/MULTI fails CROSSSLOT under EnterpriseCluster (SP-2)

// Slice 2, tenancy (owner, 20 Oct): the pool server on Burstable B2s
// (≈ ₹7,700/month; no built-in PgBouncer). Scale it in place to General
// Purpose Standard_D2ds_v5 (≈ ₹18,400/month) for spike SP-6. Software KEKs in dev.
param deployTenancy = true
param poolServerSku = {
  name: 'Standard_B2s'
  tier: 'Burstable'
}
param tenantKeysVaultSku = 'standard'

// Working hours (owner, 20 Oct): Mon–Sat 09:00–21:00 IST; the cluster and both
// PostgreSQL servers are stopped nights and Sundays (budget ₹50,000/month).
param scheduleEnabled = true
param scheduleWeekDays = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
param scheduleStartHour = 9
param scheduleStopHour = 21
param scheduleTimeZone = 'India Standard Time'

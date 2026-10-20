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

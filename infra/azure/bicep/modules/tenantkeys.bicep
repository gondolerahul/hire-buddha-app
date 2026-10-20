// The tenant-keys vault (slice 2; tech spec §10.4): one key-encryption key
// per tenant (`t-<key>`, RSA; RSA-HSM on Premium), separate from the platform
// vault to isolate throttling and blast radius. Purge protection on: deleting
// a tenant's KEK is how offboarding crypto-shreds its secrets, and the vault's
// retention period is the window to undo a mistake. Keys are made by the
// provisioner at run time, never by this template.

param location string
param name string
@description('standard (software keys: dev) or premium (HSM-backed keys: TENANT_KEK_HSM).')
@allowed(['standard', 'premium'])
param skuName string = 'standard'
param adminsGroupObjectId string
@description('Creates, rotates and deletes the tenant KEKs: the provisioner.')
param cryptoOfficerPrincipalIds array
@description('Wrap and unwrap DEKs with them: API, workers, Connection Service.')
param cryptoUserPrincipalIds array

var roles = {
  administrator: '00482a5a-887f-4fb3-b363-3b7fe8e74483'
  cryptoOfficer: '14b46e9e-c2b7-41b4-b07b-48a6ebf60603'
  cryptoUser: '12338af0-0e69-4776-bea7-57ae8d297424'
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: skuName }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 90
    publicNetworkAccess: 'Enabled' // dev: Entra RBAC only; staging/prod use a private endpoint (guide §20)
  }
}

resource admins 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, adminsGroupObjectId, roles.administrator)
  properties: {
    principalId: adminsGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.administrator)
  }
}

resource cryptoOfficers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in cryptoOfficerPrincipalIds: {
  scope: vault
  name: guid(vault.id, principalId, roles.cryptoOfficer)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cryptoOfficer)
  }
}]

resource cryptoUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in cryptoUserPrincipalIds: {
  scope: vault
  name: guid(vault.id, principalId, roles.cryptoUser)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cryptoUser)
  }
}]

output name string = vault.name
output uri string = vault.properties.vaultUri

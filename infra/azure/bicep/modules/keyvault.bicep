// The platform Key Vault (guide §7): RBAC, purge protection, no access
// policies. The tenant-keys vault is slice 2 (WS2). Secrets from third
// parties are set by people, never by this template; only the values Azure
// itself produces are written here.

param location string
param name string
param adminsGroupObjectId string
param developersGroupObjectId string
param secretReaderPrincipalIds array
param cryptoUserPrincipalIds array
@secure()
param appInsightsConnectionString string

var roles = {
  administrator: '00482a5a-887f-4fb3-b363-3b7fe8e74483'
  secretsUser: '4633458b-17de-408a-b874-0445c86b69e6'
  cryptoUser: '12338af0-0e69-4776-bea7-57ae8d297424'
}

resource vault 'Microsoft.KeyVault/vaults@2023-07-01' = {
  name: name
  location: location
  properties: {
    tenantId: subscription().tenantId
    sku: { family: 'A', name: 'standard' }
    enableRbacAuthorization: true
    enablePurgeProtection: true
    enableSoftDelete: true
    softDeleteRetentionInDays: 30
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

resource developers 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: vault
  name: guid(vault.id, developersGroupObjectId, roles.secretsUser)
  properties: {
    principalId: developersGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.secretsUser)
  }
}

resource secretReaders 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in secretReaderPrincipalIds: {
  scope: vault
  name: guid(vault.id, principalId, roles.secretsUser)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.secretsUser)
  }
}]

// The API signs Data API tokens with a Key Vault key (tech spec §9.3).
resource cryptoUsers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in cryptoUserPrincipalIds: {
  scope: vault
  name: guid(vault.id, principalId, roles.cryptoUser)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.cryptoUser)
  }
}]

resource signingKey 'Microsoft.KeyVault/vaults/keys@2023-07-01' = {
  parent: vault
  name: 'data-api-signing'
  properties: {
    kty: 'RSA'
    keySize: 2048
    keyOps: ['sign', 'verify']
  }
}

resource appInsightsSecret 'Microsoft.KeyVault/vaults/secrets@2023-07-01' = {
  parent: vault
  name: 'appinsights-connection-string'
  properties: {
    value: appInsightsConnectionString
  }
}

output name string = vault.name
output uri string = vault.properties.vaultUri
output id string = vault.id

// Blob storage for every platform file (tech spec §12.1, guide §8): no shared
// keys, no public blobs, versioning and 14-day soft delete. Containers per
// tenant (t-<key>) are created by the Provisioner (WS2); the azure_blob
// adapter creates a missing one on first write until then.

param location string
param name string
param adminsGroupObjectId string
param developersGroupObjectId string
param dataContributorPrincipalIds array

var roles = {
  owner: 'b7e6dc6d-f1e8-4753-8033-0f276bb0955b'
  // Includes generateUserDelegationKey: the adapter signs download links with it.
  contributor: 'ba92f5b4-2d11-453d-a403-e96b0029c9fe'
}

resource account 'Microsoft.Storage/storageAccounts@2023-05-01' = {
  name: name
  location: location
  kind: 'StorageV2'
  sku: { name: 'Standard_LRS' }
  properties: {
    minimumTlsVersion: 'TLS1_2'
    allowBlobPublicAccess: false
    allowSharedKeyAccess: false
    supportsHttpsTrafficOnly: true
    defaultToOAuthAuthentication: true
    publicNetworkAccess: 'Enabled' // dev: Entra RBAC only; staging/prod use a private endpoint (guide §20)
  }
}

resource blobService 'Microsoft.Storage/storageAccounts/blobServices@2023-05-01' = {
  parent: account
  name: 'default'
  properties: {
    isVersioningEnabled: true
    deleteRetentionPolicy: { enabled: true, days: 14 }
    containerDeleteRetentionPolicy: { enabled: true, days: 14 }
  }
}

resource containers 'Microsoft.Storage/storageAccounts/blobServices/containers@2023-05-01' = [for container in ['platform', 'migration']: {
  parent: blobService
  name: container
  properties: { publicAccess: 'None' }
}]

resource admins 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, adminsGroupObjectId, roles.owner)
  properties: {
    principalId: adminsGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.owner)
  }
}

resource developers 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: account
  name: guid(account.id, developersGroupObjectId, roles.contributor)
  properties: {
    principalId: developersGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}

resource workloads 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in dataContributorPrincipalIds: {
  scope: account
  name: guid(account.id, principalId, roles.contributor)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roles.contributor)
  }
}]

output blobEndpoint string = account.properties.primaryEndpoints.blob
output id string = account.id

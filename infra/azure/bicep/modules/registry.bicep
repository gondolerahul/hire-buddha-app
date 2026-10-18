// The platform image registry (guide §8). Admin user off: CI pushes with its
// managed identity, AKS pulls with its kubelet identity. The tenant-apps
// registry is slice 4 (WS6).

param location string
param name string
param pushPrincipalIds array
param developersGroupObjectId string

var acrPush = '8311e382-0749-4cb8-b61a-304f252e45ec'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: name
  location: location
  sku: { name: 'Standard' }
  properties: {
    adminUserEnabled: false
    publicNetworkAccess: 'Enabled'
  }
}

resource pushers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in pushPrincipalIds: {
  scope: registry
  name: guid(registry.id, principalId, acrPush)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPush)
  }
}]

resource developersPush 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  scope: registry
  name: guid(registry.id, developersGroupObjectId, acrPush)
  properties: {
    principalId: developersGroupObjectId
    principalType: 'Group'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPush)
  }
}

output loginServer string = registry.properties.loginServer
output id string = registry.id

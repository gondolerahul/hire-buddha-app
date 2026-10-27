// The platform image registry (guide §8). Admin user off: CI pushes with its
// managed identity, AKS pulls with its kubelet identity. The tenant-apps
// registry is slice 4 (WS6).

param location string
param name string
param pushPrincipalIds array
param developersGroupObjectId string
@description('Who may delete repositories: the provisioner, which removes the app images of a closed business (docs/phase15/13 §6 step 5).')
param deletePrincipalIds array = []

var acrPush = '8311e382-0749-4cb8-b61a-304f252e45ec'
var acrDelete = 'c2f4ef07-c644-48eb-af81-4b1b4947fb11'

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

resource deleters 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in deletePrincipalIds: {
  scope: registry
  name: guid(registry.id, principalId, acrDelete)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrDelete)
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

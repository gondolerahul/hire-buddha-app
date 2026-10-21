// Another environment's CI identity may read this registry (decision D51):
// production's deploy imports the exact images dev ran (`az acr import`)
// instead of building them again.

param registryName string
param principalIds array

var acrPull = '7f951dda-4ed3-4680-a7ca-43fe172d538d'

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource pull 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: {
  scope: registry
  name: guid(registry.id, principalId, acrPull)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', acrPull)
  }
}]

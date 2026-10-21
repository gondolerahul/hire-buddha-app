// Slice 4 (D53): the platform registry also holds tenants' app images, built by
// ACR Tasks for the workers (build_app) and the API (a build of an open pull
// request); the cluster's kubelet already pulls from it.

param registryName string
param principalIds array

var tasksContributor = 'fb382eab-e894-4461-af04-94435c366c3f' // Container Registry Tasks Contributor

resource registry 'Microsoft.ContainerRegistry/registries@2023-07-01' existing = {
  name: registryName
}

resource tasks 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in principalIds: {
  scope: registry
  name: guid(registry.id, principalId, tasksContributor)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', tasksContributor)
  }
}]

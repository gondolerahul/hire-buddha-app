// The dev schedule's start/stop role on the resources of one resource group:
// the AKS cluster (rg-*-aks) or the PostgreSQL servers (rg-*-data).

param roleDefinitionId string
param principalIds array
param aksName string = ''
param postgresServerNames array = []

resource aks 'Microsoft.ContainerService/managedClusters@2024-09-01' existing = if (!empty(aksName)) {
  name: empty(aksName) ? 'none' : aksName
}

resource onAks 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for principalId in (empty(aksName) ? [] : principalIds): {
  scope: aks
  name: guid(aks.id, principalId, roleDefinitionId)
  properties: {
    principalId: principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleDefinitionId
  }
}]

resource servers 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' existing = [for name in postgresServerNames: {
  name: name
}]

// Every (server, principal) pair.
var pairs = flatten(map(range(0, length(postgresServerNames)), s => map(principalIds, p => { server: s, principalId: p })))

resource onServers 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for pair in pairs: {
  scope: servers[pair.server]
  name: guid(servers[pair.server].id, pair.principalId, roleDefinitionId)
  properties: {
    principalId: pair.principalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: roleDefinitionId
  }
}]

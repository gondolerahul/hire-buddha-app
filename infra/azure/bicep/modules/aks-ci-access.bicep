// GitHub Actions (id-<prefix>-<env>-ci) may get cluster credentials and deploy
// (guide §15.1). The guide scopes the writer role to the hb-platform
// namespace, which ARM cannot express; here it is cluster-wide (dev), and
// staging/prod narrow it with `az role assignment create --scope <cluster>/namespaces/<ns>`.

param clusterName string
param ciPrincipalId string

var roles = {
  clusterUser: '4abbcc35-e782-43d8-92c5-2d3f1bd2253f'
  rbacWriter: 'a7ffa36f-339b-4b5c-8bdf-e2c188b2c0eb'
}

resource cluster 'Microsoft.ContainerService/managedClusters@2024-09-01' existing = {
  name: clusterName
}

resource ciRoles 'Microsoft.Authorization/roleAssignments@2022-04-01' = [for role in items(roles): {
  scope: cluster
  name: guid(cluster.id, ciPrincipalId, role.value)
  properties: {
    principalId: ciPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', role.value)
  }
}]

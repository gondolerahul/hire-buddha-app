// GitHub Actions (id-<prefix>-<env>-ci) may get cluster credentials and deploy
// (guide §15.1). RBAC Writer does not cover custom resources (the chart's
// SecretProviderClass and HTTPRoute: the first pipeline deploy was refused,
// 21 Oct 2026), so the CI identity also holds "Azure Kubernetes Service RBAC
// Admin" on the hb-platform namespace only — a scope ARM cannot express, given
// by CLI on dev and production:
//   az role assignment create --assignee-object-id <ci principal> --assignee-principal-type ServicePrincipal \
//     --role "Azure Kubernetes Service RBAC Admin" --scope <cluster id>/namespaces/hb-platform

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

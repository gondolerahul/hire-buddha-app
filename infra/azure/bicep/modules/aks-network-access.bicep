// What the AKS control-plane identity needs in the core resource group before
// the cluster exists: join the node subnet and its NAT gateway, and attach the
// ingress IP to the gateway's load balancer (guide §9.5).

param controlPlanePrincipalId string

var networkContributor = '4d97b98b-1d4f-4787-a291-c67834d212e7'

resource access 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, controlPlanePrincipalId, networkContributor)
  properties: {
    principalId: controlPlanePrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', networkContributor)
  }
}

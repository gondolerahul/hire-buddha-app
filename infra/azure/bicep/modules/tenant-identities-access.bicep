// Where each tenant's own identity lives (slice 2; tech spec §5.2, §6.2
// `identity_ready`): `id-<prefix>-<env>-t-<key>` for its Data API, federated
// to `t-<key>/data-api` in the cluster. The provisioner creates them at run
// time, so it may manage identities (and their federated credentials) in this
// resource group only.

param provisionerPrincipalId string

var managedIdentityContributor = 'e40ec5ca-96e0-45a2-b4ff-59039f2c2b59'

resource provisioner 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(resourceGroup().id, provisionerPrincipalId, managedIdentityContributor)
  properties: {
    principalId: provisionerPrincipalId
    principalType: 'ServicePrincipal'
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', managedIdentityContributor)
  }
}

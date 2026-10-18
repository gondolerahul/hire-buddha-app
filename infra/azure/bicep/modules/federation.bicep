// Federated credentials (guide §9.4, §15.1): each platform service account
// sa-<id> in hb-platform may sign in as id-<prefix>-<env>-<id>, and GitHub
// Actions in the repository's azure-<env> environment as id-<prefix>-<env>-ci.
// No secret is stored for any of them.

param prefix string
param env string
param oidcIssuerUrl string
param namespace string
param githubRepository string

var workloads = ['api', 'worker', 'connsvc', 'provisioner', 'migrator', 'appcontroller']

resource identities 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = [for id in workloads: {
  name: 'id-${prefix}-${env}-${id}'
}]

@batchSize(1) // federated credentials of one identity cannot be written in parallel
resource podFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = [for (id, i) in workloads: {
  parent: identities[i]
  name: 'fc-aks-${prefix}-${env}-${id}'
  properties: {
    issuer: oidcIssuerUrl
    subject: 'system:serviceaccount:${namespace}:sa-${id}'
    audiences: ['api://AzureADTokenExchange']
  }
}]

resource ci 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' existing = {
  name: 'id-${prefix}-${env}-ci'
}

resource githubFederation 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = {
  parent: ci
  name: 'gh-azure-${env}'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepository}:environment:azure-${env}'
    audiences: ['api://AzureADTokenExchange']
  }
}

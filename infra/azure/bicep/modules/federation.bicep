// Federated credentials (guide §9.4, §15.1): each platform service account
// sa-<id> in hb-platform may sign in as id-<prefix>-<env>-<id>, and GitHub
// Actions in the repository's azure-<env> environment as id-<prefix>-<env>-ci.
// No secret is stored for any of them.

param prefix string
param env string
param oidcIssuerUrl string
param namespace string
param githubRepository string
@description('The repository as GitHub\'s OIDC subjects name it with immutable ids (owner@<owner id>/name@<repo id>); empty for none.')
param githubRepositoryIds string = ''

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

// GitHub's subjects now carry immutable ids ("repo:owner@123/name@456:environment:…"):
// a second credential for that form (21 Oct 2026: the plain one was refused, AADSTS700213).
resource githubFederationIds 'Microsoft.ManagedIdentity/userAssignedIdentities/federatedIdentityCredentials@2023-01-31' = if (!empty(githubRepositoryIds)) {
  parent: ci
  name: 'gh-azure-${env}-ids'
  properties: {
    issuer: 'https://token.actions.githubusercontent.com'
    subject: 'repo:${githubRepositoryIds}:environment:azure-${env}'
    audiences: ['api://AzureADTokenExchange']
  }
  dependsOn: [githubFederation]
}

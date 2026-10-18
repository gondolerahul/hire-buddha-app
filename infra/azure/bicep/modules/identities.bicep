// One user-assigned managed identity per platform service (tech spec §5.2,
// §12.2; guide §5). Pods use them through AKS workload identity; GitHub
// Actions uses "ci" through OIDC. Tenant Data API identities are created per
// tenant by the Provisioner (WS2).

param location string
param prefix string
param env string

var services = ['aks', 'api', 'worker', 'connsvc', 'provisioner', 'migrator', 'appcontroller', 'ci']

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = [for service in services: {
  name: 'id-${prefix}-${env}-${service}'
  location: location
}]

// By service name (the order of `services`).
output ids object = {
  aks: identity[0].id
  api: identity[1].id
  worker: identity[2].id
  connsvc: identity[3].id
  provisioner: identity[4].id
  migrator: identity[5].id
  appcontroller: identity[6].id
  ci: identity[7].id
}
output principalIds object = {
  aks: identity[0].properties.principalId
  api: identity[1].properties.principalId
  worker: identity[2].properties.principalId
  connsvc: identity[3].properties.principalId
  provisioner: identity[4].properties.principalId
  migrator: identity[5].properties.principalId
  appcontroller: identity[6].properties.principalId
  ci: identity[7].properties.principalId
}
output clientIds object = {
  aks: identity[0].properties.clientId
  api: identity[1].properties.clientId
  worker: identity[2].properties.clientId
  connsvc: identity[3].properties.clientId
  provisioner: identity[4].properties.clientId
  migrator: identity[5].properties.clientId
  appcontroller: identity[6].properties.clientId
  ci: identity[7].properties.clientId
}

// The workloads that read platform secrets (guide §7).
output platformPrincipalIds array = [
  identity[1].properties.principalId // api
  identity[2].properties.principalId // worker
  identity[3].properties.principalId // connsvc
  identity[4].properties.principalId // provisioner
  identity[5].properties.principalId // migrator
  identity[6].properties.principalId // appcontroller
]

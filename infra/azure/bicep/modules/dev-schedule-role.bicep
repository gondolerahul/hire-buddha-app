// The only rights the dev schedule needs (budget, 20 Oct): read, start and
// stop clusters and PostgreSQL servers. Assigned on the cluster and the
// servers only (dev-schedule-access.bicep), never wider.

targetScope = 'subscription'

param prefix string
param env string

resource role 'Microsoft.Authorization/roleDefinitions@2022-04-01' = {
  name: guid(subscription().id, prefix, env, 'start-stop')
  properties: {
    roleName: '${prefix}-${env} start/stop'
    description: 'Start and stop the ${env} AKS cluster and PostgreSQL servers on a schedule.'
    type: 'CustomRole'
    assignableScopes: [subscription().id]
    permissions: [
      {
        actions: [
          'Microsoft.ContainerService/managedClusters/read'
          'Microsoft.ContainerService/managedClusters/start/action'
          'Microsoft.ContainerService/managedClusters/stop/action'
          'Microsoft.DBforPostgreSQL/flexibleServers/read'
          'Microsoft.DBforPostgreSQL/flexibleServers/start/action'
          'Microsoft.DBforPostgreSQL/flexibleServers/stop/action'
        ]
        notActions: []
      }
    ]
  }
}

output roleDefinitionId string = role.id

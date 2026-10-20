// Dev runs only in working hours (budget, owner's choice of 20 Oct): two
// Logic Apps on a timer. Start: the PostgreSQL servers (waiting until they
// are up), then the AKS cluster. Stop: the cluster, then the servers. Each
// app signs in to Azure Resource Manager with its own managed identity, which
// holds only the start/stop role on those resources (dev-schedule-access).
//
// Start or stop by hand at any time: the Logic App's "Run trigger" in the
// portal, or `az aks start|stop` and `az postgres flexible-server start|stop`.

param location string
param prefix string
param env string
param aksId string
@description('Resource ids of the PostgreSQL servers to start and stop.')
param postgresServerIds array
@description('Windows time zone name of the schedule.')
param timeZone string = 'India Standard Time'
param weekDays array = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday']
param startHour int = 9
param stopHour int = 21

var armEndpoint = environment().resourceManager  // https://management.azure.com/
var arm = endsWith(armEndpoint, '/') ? take(armEndpoint, length(armEndpoint) - 1) : armEndpoint
var auth = { type: 'ManagedServiceIdentity', audience: armEndpoint }

func trigger(weekDays array, hour int, timeZone string) object => {
  Recurrence: {
    type: 'Recurrence'
    recurrence: {
      frequency: 'Week'
      interval: 1
      timeZone: timeZone
      schedule: { weekDays: weekDays, hours: [hour], minutes: [0] }
    }
  }
}

// One action per server; a server already in the wanted state answers an
// error, which the next step tolerates (runAfter Succeeded or Failed).
var startServers = toObject(range(0, length(postgresServerIds)), i => 'Start_server_${i}', i => {
  type: 'Http'
  inputs: { method: 'POST', uri: '${arm}${postgresServerIds[i]}/start?api-version=2024-08-01', authentication: auth }
  runAfter: {}
})
var stopServers = toObject(range(0, length(postgresServerIds)), i => 'Stop_server_${i}', i => {
  type: 'Http'
  inputs: { method: 'POST', uri: '${arm}${postgresServerIds[i]}/stop?api-version=2024-08-01', authentication: auth }
  runAfter: { Stop_cluster: ['Succeeded', 'Failed', 'TimedOut'] }
})

resource startApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-${prefix}-${env}-start'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: trigger(weekDays, startHour, timeZone)
      actions: union(startServers, {
        Start_cluster: {
          type: 'Http'
          inputs: { method: 'POST', uri: '${arm}${aksId}/start?api-version=2024-09-01', authentication: auth }
          runAfter: toObject(objectKeys(startServers), k => k, k => ['Succeeded', 'Failed', 'TimedOut'])
        }
      })
    }
  }
}

resource stopApp 'Microsoft.Logic/workflows@2019-05-01' = {
  name: 'logic-${prefix}-${env}-stop'
  location: location
  identity: { type: 'SystemAssigned' }
  properties: {
    state: 'Enabled'
    definition: {
      '$schema': 'https://schema.management.azure.com/providers/Microsoft.Logic/schemas/2016-06-01/workflowdefinition.json#'
      contentVersion: '1.0.0.0'
      triggers: trigger(weekDays, stopHour, timeZone)
      actions: union({
        Stop_cluster: {
          type: 'Http'
          inputs: { method: 'POST', uri: '${arm}${aksId}/stop?api-version=2024-09-01', authentication: auth }
          runAfter: {}
        }
      }, stopServers)
    }
  }
}

output principalIds array = [startApp.identity.principalId, stopApp.identity.principalId]

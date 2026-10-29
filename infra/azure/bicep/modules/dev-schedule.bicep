// Dev runs only in working hours (budget, owner's choice of 20 Oct): two
// Logic Apps on a timer. Start: the PostgreSQL servers (waiting until they
// are up), then the AKS cluster if it is stopped. Stop: the cluster, then —
// only once it is stopped — the servers. Each app signs in to Azure Resource
// Manager with its own managed identity, which holds only the start/stop role
// on those resources (dev-schedule-access).
//
// The servers are never stopped under a running cluster: on 28 Oct 2026 AKS
// refused the 21:00 stop (a node pool upgrade was running), the app stopped the
// servers anyway, and the platform ran all night against stopped databases
// (the API restarted 133 times; a deploy's migrations failed). Now a refused
// stop is asked again while the cluster becomes idle, for up to an hour; if the
// cluster is still running then, the servers stay up that night.
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
@description('How often, and how many times, a stop AKS refused (an operation in progress) is asked again.')
param stopRetryMinutes int = 5
param stopRetries int = 12

var armEndpoint = environment().resourceManager  // https://management.azure.com/
var arm = endsWith(armEndpoint, '/') ? take(armEndpoint, length(armEndpoint) - 1) : armEndpoint
var auth = { type: 'ManagedServiceIdentity', audience: armEndpoint }
var aksApi = 'api-version=2024-09-01'

// The cluster as the last Read_cluster saw it.
var power = '@body(\'Read_cluster\')?[\'properties\']?[\'powerState\']?[\'code\']'
var provisioning = '@body(\'Read_cluster\')?[\'properties\']?[\'provisioningState\']'

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

func clusterCall(method string, uri string, auth object, runAfter object) object => {
  type: 'Http'
  inputs: { method: method, uri: uri, authentication: auth }
  runAfter: runAfter
}

// One action per server; a server already in the wanted state answers an
// error, which the next step tolerates (runAfter Succeeded or Failed).
var startServers = toObject(range(0, length(postgresServerIds)), i => 'Start_server_${i}', i => {
  type: 'Http'
  inputs: { method: 'POST', uri: '${arm}${postgresServerIds[i]}/start?api-version=2024-08-01', authentication: auth }
  runAfter: {}
})
// Inside If_cluster_stopped: each runs first in its branch.
var stopServers = toObject(range(0, length(postgresServerIds)), i => 'Stop_server_${i}', i => {
  type: 'Http'
  inputs: { method: 'POST', uri: '${arm}${postgresServerIds[i]}/stop?api-version=2024-08-01', authentication: auth }
  runAfter: {}
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
        Read_cluster: clusterCall('GET', '${arm}${aksId}?${aksApi}', auth,
                                  toObject(objectKeys(startServers), k => k, k => ['Succeeded', 'Failed', 'TimedOut']))
        // A cluster that never stopped (a refused stop) is left running: starting it is an error.
        If_cluster_stopped: {
          type: 'If'
          expression: { and: [ { equals: [ power, 'Stopped' ] } ] }
          actions: {
            Start_cluster: clusterCall('POST', '${arm}${aksId}/start?${aksApi}', auth, {})
          }
          else: { actions: {} }
          runAfter: { Read_cluster: ['Succeeded'] }
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
      actions: {
        Stop_cluster: clusterCall('POST', '${arm}${aksId}/stop?${aksApi}', auth, {})
        // Until AKS reports the cluster stopped: every few minutes read it, and
        // ask again when it is running with nothing in progress (a stop refused
        // during an upgrade).
        Until_cluster_stopped: {
          type: 'Until'
          expression: '@equals(body(\'Read_cluster\')?[\'properties\']?[\'powerState\']?[\'code\'], \'Stopped\')'
          limit: { count: stopRetries, timeout: 'PT2H' }
          actions: {
            Wait: {
              type: 'Wait'
              inputs: { interval: { count: stopRetryMinutes, unit: 'Minute' } }
              runAfter: {}
            }
            Read_cluster: clusterCall('GET', '${arm}${aksId}?${aksApi}', auth, { Wait: ['Succeeded'] })
            If_running_and_idle: {
              type: 'If'
              expression: { and: [ { equals: [ power, 'Running' ] }, { equals: [ provisioning, 'Succeeded' ] } ] }
              actions: {
                Stop_cluster_again: clusterCall('POST', '${arm}${aksId}/stop?${aksApi}', auth, {})
              }
              else: { actions: {} }
              runAfter: { Read_cluster: ['Succeeded'] }
            }
          }
          runAfter: { Stop_cluster: ['Succeeded', 'Failed', 'TimedOut'] }
        }
        // The servers only under a stopped cluster; otherwise they stay up tonight.
        If_cluster_stopped: {
          type: 'If'
          expression: { and: [ { equals: [ power, 'Stopped' ] } ] }
          actions: stopServers
          else: { actions: {} }
          runAfter: { Until_cluster_stopped: ['Succeeded', 'Failed', 'TimedOut'] }
        }
      }
    }
  }
}

output principalIds array = [startApp.identity.principalId, stopApp.identity.principalId]

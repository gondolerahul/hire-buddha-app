// Slice 4, the tenant runtime (WS6; decision D53, owner 21 Oct 2026): two node
// pools on the existing cluster, added as agentPools so the cluster itself is
// not re-sent.
//
// * sandbox — agents' scratch code: AKS Pod Sandboxing (every pod its own Kata
//   micro-VM; the VM size must support nested virtualization), scaling to zero.
//   Pods choose it with nodeSelector hb/pool=sandbox and its toleration.
// * apps — tenants' published apps (the App Controller's Deployments, the
//   tenant edge, Gitea): one small node, more under load.

param clusterName string
param nodeSubnetId string
param sandboxVmSize string
param sandboxMinCount int
param sandboxMaxCount int
param appsVmSize string
param appsMinCount int
param appsMaxCount int

resource cluster 'Microsoft.ContainerService/managedClusters@2024-09-01' existing = {
  name: clusterName
}

resource sandbox 'Microsoft.ContainerService/managedClusters/agentPools@2024-09-01' = {
  parent: cluster
  name: 'sandbox'
  properties: {
    mode: 'User'
    type: 'VirtualMachineScaleSets'
    vmSize: sandboxVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    workloadRuntime: 'KataMshvVmIsolation'
    enableAutoScaling: true
    count: sandboxMinCount
    minCount: sandboxMinCount
    maxCount: sandboxMaxCount
    vnetSubnetID: nodeSubnetId
    nodeLabels: { 'hb/pool': 'sandbox' }
    nodeTaints: ['hb/pool=sandbox:NoSchedule']
  }
}

resource apps 'Microsoft.ContainerService/managedClusters/agentPools@2024-09-01' = {
  parent: cluster
  name: 'apps'
  properties: {
    mode: 'User'
    type: 'VirtualMachineScaleSets'
    vmSize: appsVmSize
    osType: 'Linux'
    osSKU: 'AzureLinux'
    enableAutoScaling: true
    count: appsMinCount
    minCount: appsMinCount
    maxCount: appsMaxCount
    vnetSubnetID: nodeSubnetId
    nodeLabels: { 'hb/pool': 'apps' }
    nodeTaints: ['hb/pool=apps:NoSchedule']
  }
  dependsOn: [sandbox] // one pool at a time
}

// The AKS cluster of slice 1 (tech spec §4.2, guide §9): system and platform
// pools on Azure Linux, Azure CNI Overlay with Cilium, OIDC issuer and
// workload identity, Entra ID with Azure RBAC for Kubernetes, the Key Vault
// CSI driver, Container Insights, KEDA, and outbound through the NAT gateway.
// The apps and sandbox (Kata) pools are slice 4 (WS6).

param location string
param name string
param nodeResourceGroup string
param nodeSubnetId string
param controlPlaneIdentityId string
param logAnalyticsWorkspaceId string
param adminsGroupObjectId string
param systemPoolVmSize string
param platformPoolVmSize string
param platformPoolMinCount int
param platformPoolMaxCount int
@description('Free for dev; Standard (uptime SLA) for staging and prod.')
@allowed(['Free', 'Standard'])
param tier string = 'Free'
param systemPoolCount int = 1
// When AKS may upgrade the cluster and its node images: one weekly window,
// at least 4 hours, for both channels. Without one, Azure upgrades at any hour:
// on 28 Oct 2026 a node image upgrade began at 20:57 IST, the 21:00 stop of the
// dev schedule was refused, and dev ran all night against stopped databases.
// Dev's window must fall inside its working hours (a stopped cluster is not upgraded).
@allowed(['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday'])
param maintenanceDay string = 'Sunday'
@description('HH:mm, in maintenanceUtcOffset.')
param maintenanceStartTime string = '02:00'
@minValue(4)
param maintenanceDurationHours int = 4
param maintenanceUtcOffset string = '+05:30'

resource cluster 'Microsoft.ContainerService/managedClusters@2024-09-01' = {
  name: name
  location: location
  sku: { name: 'Base', tier: tier }
  identity: {
    type: 'UserAssigned'
    userAssignedIdentities: { '${controlPlaneIdentityId}': {} }
  }
  properties: {
    dnsPrefix: name
    nodeResourceGroup: nodeResourceGroup
    enableRBAC: true
    disableLocalAccounts: true
    aadProfile: {
      managed: true
      enableAzureRBAC: true
      adminGroupObjectIDs: [adminsGroupObjectId]
      tenantID: tenant().tenantId
    }
    oidcIssuerProfile: { enabled: true }
    securityProfile: {
      workloadIdentity: { enabled: true }
    }
    networkProfile: {
      networkPlugin: 'azure'
      networkPluginMode: 'overlay'
      networkDataplane: 'cilium'
      networkPolicy: 'cilium'
      podCidr: '192.168.0.0/16'
      serviceCidr: '10.0.0.0/16'
      dnsServiceIP: '10.0.0.10'
      loadBalancerSku: 'standard'
      outboundType: 'userAssignedNATGateway'
    }
    addonProfiles: {
      azureKeyvaultSecretsProvider: {
        enabled: true
        config: {
          enableSecretRotation: 'true'
          rotationPollInterval: '2m'
        }
      }
      omsagent: {
        enabled: true
        config: { logAnalyticsWorkspaceResourceID: logAnalyticsWorkspaceId }
      }
    }
    workloadAutoScalerProfile: {
      keda: { enabled: true }
    }
    autoUpgradeProfile: {
      upgradeChannel: 'patch'
      nodeOSUpgradeChannel: 'NodeImage'
    }
    agentPoolProfiles: [
      {
        name: 'system'
        mode: 'System'
        type: 'VirtualMachineScaleSets'
        count: systemPoolCount
        vmSize: systemPoolVmSize
        osType: 'Linux'
        osSKU: 'AzureLinux'
        vnetSubnetID: nodeSubnetId
        // Keep user workloads off the system pool.
        nodeTaints: ['CriticalAddonsOnly=true:NoSchedule']
      }
      {
        name: 'platform'
        mode: 'User'
        type: 'VirtualMachineScaleSets'
        enableAutoScaling: true
        count: platformPoolMinCount
        minCount: platformPoolMinCount
        maxCount: platformPoolMaxCount
        vmSize: platformPoolVmSize
        osType: 'Linux'
        osSKU: 'AzureLinux'
        vnetSubnetID: nodeSubnetId
        nodeLabels: { 'hb/pool': 'platform' }
      }
    ]
  }
}

var maintenanceWindow = {
  schedule: { weekly: { intervalWeeks: 1, dayOfWeek: maintenanceDay } }
  durationHours: maintenanceDurationHours
  startTime: maintenanceStartTime
  utcOffset: maintenanceUtcOffset
}

// Kubernetes patch versions (upgradeChannel: patch).
resource autoUpgradeWindow 'Microsoft.ContainerService/managedClusters/maintenanceConfigurations@2024-09-01' = {
  parent: cluster
  name: 'aksManagedAutoUpgradeSchedule'
  properties: { maintenanceWindow: maintenanceWindow }
}

// Node images (nodeOSUpgradeChannel: NodeImage), weekly as AKS releases them.
resource nodeOsUpgradeWindow 'Microsoft.ContainerService/managedClusters/maintenanceConfigurations@2024-09-01' = {
  parent: cluster
  name: 'aksManagedNodeOSUpgradeSchedule'
  properties: { maintenanceWindow: maintenanceWindow }
}

output name string = cluster.name
output id string = cluster.id
output oidcIssuerUrl string = cluster.properties.oidcIssuerProfile.issuerURL
output kubeletPrincipalId string = cluster.properties.identityProfile.kubeletidentity.objectId

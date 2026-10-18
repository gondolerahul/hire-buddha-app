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

output name string = cluster.name
output id string = cluster.id
output oidcIssuerUrl string = cluster.properties.oidcIssuerProfile.issuerURL
output kubeletPrincipalId string = cluster.properties.identityProfile.kubeletidentity.objectId

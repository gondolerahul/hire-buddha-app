// Azure Managed Redis (tech spec §12.3, guide §11): TLS on port 10000,
// reachable only through a private endpoint. Arq's queues live here, so
// nothing may be evicted. Clustering policy (spike SP-2): arq's WATCH/MULTI
// transactions fail with CROSSSLOT under EnterpriseCluster, so a cache of
// 25 GB or less runs NoCluster. The policy cannot be changed in place: the
// database is deleted and redeployed (its access key changes; reset redis-url).

param location string
param name string
param sku string
param clusteringPolicy string
param privateEndpointSubnetId string
param vnetId string
@description('Dev runs without high availability (implementation plan, slice 1).')
param highAvailability bool = false

resource cluster 'Microsoft.Cache/redisEnterprise@2025-07-01' = {
  name: name
  location: location
  sku: { name: sku }
  properties: {
    minimumTlsVersion: '1.2'
    // Reached only through the private endpoint below.
    publicNetworkAccess: 'Disabled'
    highAvailability: highAvailability ? 'Enabled' : 'Disabled'
  }
}

resource database 'Microsoft.Cache/redisEnterprise/databases@2025-07-01' = {
  parent: cluster
  name: 'default'
  properties: {
    clientProtocol: 'Encrypted'
    port: 10000
    clusteringPolicy: clusteringPolicy
    evictionPolicy: 'NoEviction'
    // The redis-url secret carries the access key until Entra auth for the
    // Redis clients is built; the endpoint is private either way.
    accessKeysAuthentication: 'Enabled'
  }
}

resource dnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: 'privatelink.redis.azure.net'
  location: 'global'
}

resource dnsLink 'Microsoft.Network/privateDnsZones/virtualNetworkLinks@2024-06-01' = {
  parent: dnsZone
  name: 'vnet'
  location: 'global'
  properties: {
    virtualNetwork: { id: vnetId }
    registrationEnabled: false
  }
}

resource endpoint 'Microsoft.Network/privateEndpoints@2024-05-01' = {
  name: 'pe-${name}'
  location: location
  properties: {
    subnet: { id: privateEndpointSubnetId }
    privateLinkServiceConnections: [
      {
        name: 'redis'
        properties: {
          privateLinkServiceId: cluster.id
          groupIds: ['redisEnterprise']
        }
      }
    ]
  }
  dependsOn: [database]
}

resource dnsGroup 'Microsoft.Network/privateEndpoints/privateDnsZoneGroups@2024-05-01' = {
  parent: endpoint
  name: 'default'
  properties: {
    privateDnsZoneConfigs: [
      {
        name: 'redis'
        properties: { privateDnsZoneId: dnsZone.id }
      }
    ]
  }
}

output hostName string = cluster.properties.hostName
output id string = cluster.id

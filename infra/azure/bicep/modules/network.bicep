// VNet, subnets, NAT gateway with a fixed egress IP, and the ingress IP
// (tech spec §4.1, guide §4). Every outbound call leaves through ONE address:
// the one partners allow-list.

param location string
param prefix string
param env string
param vnetName string
param addressPrefix string

// 10.4x.0.0/16 -> the subnet plan of tech spec §4.1.
var octets = split(split(addressPrefix, '/')[0], '.')
var base = '${octets[0]}.${octets[1]}'

resource egressIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${prefix}-${env}-egress'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

// The platform gateway's load balancer (Front Door origin) uses this address.
resource ingressIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: 'pip-${prefix}-${env}-ingress'
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

resource nat 'Microsoft.Network/natGateways@2024-05-01' = {
  name: 'ng-${prefix}-${env}'
  location: location
  sku: { name: 'Standard' }
  properties: {
    idleTimeoutInMinutes: 10
    publicIpAddresses: [{ id: egressIp.id }]
  }
}

resource vnet 'Microsoft.Network/virtualNetworks@2024-05-01' = {
  name: vnetName
  location: location
  properties: {
    addressSpace: { addressPrefixes: [addressPrefix] }
    subnets: [
      {
        name: 'snet-aks-nodes'
        properties: {
          addressPrefix: '${base}.0.0/20'
          natGateway: { id: nat.id }
        }
      }
      {
        name: 'snet-pg'
        properties: {
          addressPrefix: '${base}.16.0/24'
          delegations: [
            {
              name: 'postgres'
              properties: { serviceName: 'Microsoft.DBforPostgreSQL/flexibleServers' }
            }
          ]
        }
      }
      {
        name: 'snet-pe'
        properties: {
          addressPrefix: '${base}.17.0/24'
          privateEndpointNetworkPolicies: 'Disabled'
        }
      }
      {
        name: 'snet-ops'
        properties: {
          addressPrefix: '${base}.18.0/27'
          natGateway: { id: nat.id }
        }
      }
    ]
  }
}

output vnetId string = vnet.id
output aksNodeSubnetId string = '${vnet.id}/subnets/snet-aks-nodes'
output postgresSubnetId string = '${vnet.id}/subnets/snet-pg'
output privateEndpointSubnetId string = '${vnet.id}/subnets/snet-pe'
output egressIpAddress string = egressIp.properties.ipAddress
output ingressIpName string = ingressIp.name

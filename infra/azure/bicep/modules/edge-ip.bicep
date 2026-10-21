// Slice 4 (D53): the tenant app edge's static IP (Caddy, on-demand TLS):
// *.apps.<domain> and tenants' custom domains (an apex A record) point here.

param location string
param name string

resource edgeIp 'Microsoft.Network/publicIPAddresses@2024-05-01' = {
  name: name
  location: location
  sku: { name: 'Standard' }
  properties: {
    publicIPAllocationMethod: 'Static'
    publicIPAddressVersion: 'IPv4'
  }
}

output name string = edgeIp.name
output address string = edgeIp.properties.ipAddress

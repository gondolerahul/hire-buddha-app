// One Azure Database for PostgreSQL Flexible Server (tech spec §5.1, guide
// §10): PostgreSQL 16, private access only (delegated subnet + private DNS),
// Microsoft Entra ID authentication for every workload, a password admin for
// break-glass only, the allow-listed extensions. Slice 1 builds the control
// server; slice 2 adds the tenant pool server with this same module.

param location string
param serverName string
param dnsZoneName string
param vnetId string
param delegatedSubnetId string
param sku object
param entraAdminObjectId string
param entraAdminName string
@secure()
param breakGlassPassword string
param databases array
param highAvailability bool
param backupRetentionDays int
param geoRedundantBackup bool
param storageSizeGB int = 64
param enablePgBouncer bool = false

// Tech spec §5.1 (P-01): the only extensions migrations may rely on.
var extensions = 'VECTOR,PGCRYPTO,PG_TRGM,UUID-OSSP,BTREE_GIN'

resource dnsZone 'Microsoft.Network/privateDnsZones@2024-06-01' = {
  name: dnsZoneName
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

resource server 'Microsoft.DBforPostgreSQL/flexibleServers@2024-08-01' = {
  name: serverName
  location: location
  sku: {
    name: sku.name
    tier: sku.tier
  }
  properties: {
    version: '16'
    administratorLogin: 'hbbreakglass'
    administratorLoginPassword: breakGlassPassword
    authConfig: {
      activeDirectoryAuth: 'Enabled'
      passwordAuth: 'Enabled'
      tenantId: tenant().tenantId
    }
    network: {
      delegatedSubnetResourceId: delegatedSubnetId
      privateDnsZoneArmResourceId: dnsZone.id
      publicNetworkAccess: 'Disabled'
    }
    storage: {
      storageSizeGB: storageSizeGB
      autoGrow: 'Enabled'
    }
    backup: {
      backupRetentionDays: backupRetentionDays
      geoRedundantBackup: geoRedundantBackup ? 'Enabled' : 'Disabled'
    }
    highAvailability: {
      mode: highAvailability ? 'ZoneRedundant' : 'Disabled'
    }
  }
  dependsOn: [dnsLink]
}

// One change at a time: the server refuses concurrent updates.
resource allowedExtensions 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = {
  parent: server
  name: 'azure.extensions'
  properties: {
    value: extensions
    source: 'user-override'
  }
}

resource pgBouncer 'Microsoft.DBforPostgreSQL/flexibleServers/configurations@2024-08-01' = if (enablePgBouncer) {
  parent: server
  name: 'pgbouncer.enabled'
  properties: {
    value: 'true'
    source: 'user-override'
  }
  dependsOn: [allowedExtensions]
}

resource entraAdmin 'Microsoft.DBforPostgreSQL/flexibleServers/administrators@2024-08-01' = {
  parent: server
  name: entraAdminObjectId
  properties: {
    principalType: 'Group'
    principalName: entraAdminName
    tenantId: tenant().tenantId
  }
  dependsOn: [allowedExtensions, pgBouncer]
}

@batchSize(1)
resource database 'Microsoft.DBforPostgreSQL/flexibleServers/databases@2024-08-01' = [for name in databases: {
  parent: server
  name: name
  properties: {
    charset: 'UTF8'
    collation: 'en_US.utf8'
  }
  dependsOn: [entraAdmin]
}]

output fqdn string = server.properties.fullyQualifiedDomainName
output id string = server.id

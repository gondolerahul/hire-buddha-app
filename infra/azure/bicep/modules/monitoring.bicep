// Log Analytics (Container Insights, logs) and workspace-based Application
// Insights (traces) — guide §6. Managed Prometheus and Grafana are slice 5.

param location string
param workspaceName string
param appInsightsName string
param retentionInDays int = 30

resource workspace 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: workspaceName
  location: location
  properties: {
    sku: { name: 'PerGB2018' }
    retentionInDays: retentionInDays
  }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: appInsightsName
  location: location
  kind: 'web'
  properties: {
    Application_Type: 'web'
    WorkspaceResourceId: workspace.id
    IngestionMode: 'LogAnalytics'
  }
}

output workspaceId string = workspace.id
#disable-next-line outputs-should-not-contain-secrets // not a credential: it only addresses ingestion; stored in Key Vault anyway
output appInsightsConnectionString string = appInsights.properties.ConnectionString

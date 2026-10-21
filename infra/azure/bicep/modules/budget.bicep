// A monthly cost budget with e-mail alerts (decision D50): 80 % and 100 % of
// actual spend, 100 % of the forecast. Counts only the given resource groups
// when there are any — production shares its subscription with dev (owner,
// 21 Oct 2026) — else the whole subscription.
targetScope = 'subscription'

param name string
@description('Monthly amount in the billing currency of the subscription.')
param amount int
param contactEmails array
@description('First day of the month the budget starts (yyyy-MM-01).')
param startDate string
@description('Resource groups the budget counts; empty for the whole subscription.')
param resourceGroups array = []

var notify = {
  actual80: { threshold: 80, thresholdType: 'Actual' }
  actual100: { threshold: 100, thresholdType: 'Actual' }
  forecast100: { threshold: 100, thresholdType: 'Forecasted' }
}

resource budget 'Microsoft.Consumption/budgets@2023-11-01' = {
  name: name
  properties: {
    category: 'Cost'
    amount: amount
    timeGrain: 'Monthly'
    timePeriod: {
      startDate: startDate
    }
    filter: empty(resourceGroups) ? null : {
      dimensions: {
        name: 'ResourceGroupName'
        operator: 'In'
        values: resourceGroups
      }
    }
    notifications: toObject(items(notify), n => n.key, n => {
      enabled: true
      operator: 'GreaterThanOrEqualTo'
      threshold: n.value.threshold
      thresholdType: n.value.thresholdType
      contactEmails: contactEmails
    })
  }
}

// PitchMind on Azure: Event Hubs + Container Apps, Managed Identity everywhere, no keys.
//
// Deployed in passes by infra/deploy.ps1:
//   1. pythonImage = '' and webImage = ''  -> shared resources only (registry, Event Hubs, identity, logs)
//   2. pythonImage set                     -> the six pipeline stages (one image, one app per stage)
//   3. webImage set                        -> the frontend, built with the gateway's WebSocket URL
//
// Azure for Students only allows a few regions: keep `location` = polandcentral (or italynorth).

targetScope = 'resourceGroup'

@description('Region for every resource (subscription policy allows polandcentral, italynorth, austriaeast, belgiumcentral, denmarkeast).')
param location string = 'polandcentral'

@description('Short prefix for resource names.')
param prefix string = 'pitchmind'

@description('Python stages image, e.g. <acr>.azurecr.io/pitchmind-pipeline:<tag>. Empty = do not deploy the stages yet.')
param pythonImage string = ''

@description('Frontend image, e.g. <acr>.azurecr.io/pitchmind-web:<tag>. Empty = do not deploy the frontend yet.')
param webImage string = ''

@description('Agents model backend: mock (offline, no Azure OpenAI quota needed) or foundry.')
@allowed(['mock', 'foundry'])
param llm string = 'mock'

@description('Microsoft Foundry project endpoint (only used when llm = foundry).')
param foundryProjectEndpoint string = ''

@description('Foundry deployment for the writer agents (llm = foundry).')
param foundryModelStrong string = ''

@description('Foundry deployment for persona, language and verifier (llm = foundry).')
param foundryModelFast string = ''

@description('Resource group of the Foundry resource; when set (and llm = foundry) the app identity gets Azure AI User on it.')
param foundryResourceGroup string = ''

@description('Agent calls per minute (llm = foundry); keep under the deployment limit. Phi-4 (20K tokens/min): 10.')
param agentRpm string = '10'

@description('Seconds allowed for one agent call (llm = foundry); small serverless models can take 10-30 s.')
param agentTimeoutS string = '30'

@description('Match speed for the always-on demo match (1 = real time).')
param matchSpeed string = '6'

var suffix = take(uniqueString(resourceGroup().id), 6)
var acrName = toLower('${prefix}${suffix}')
var ehName = '${prefix}-eh-${suffix}'
var tags = { project: 'pitchmind', hackathon: 'inside-the-game' }
var useFoundry = llm == 'foundry'
// https://<account>.services.ai.azure.com/api/projects/<project> -> <account>
var foundryAccountName = empty(foundryProjectEndpoint) ? '' : split(split(foundryProjectEndpoint, '//')[1], '.')[0]

// Who reads which topic: every stage has its own consumer group on each hub it reads.
var hubs = [
  { name: 'match-events', groups: ['stats', 'moments', 'agents', 'render', 'gateway'] }
  { name: 'match-stats', groups: ['moments', 'agents', 'gateway'] }
  { name: 'match-moments', groups: ['agents', 'render', 'gateway'] }
  { name: 'match-insights', groups: ['render', 'gateway'] }
  { name: 'match-overlays', groups: ['gateway'] }
]
var consumerGroups = flatten(map(hubs, h => map(h.groups, g => { hub: h.name, group: g })))
var stages = ['simulator', 'stats', 'moments', 'agents', 'render']

// --------------------------------------------------------------------------- observability

resource logs 'Microsoft.OperationalInsights/workspaces@2023-09-01' = {
  name: '${prefix}-logs-${suffix}'
  location: location
  tags: tags
  properties: { sku: { name: 'PerGB2018' }, retentionInDays: 30 }
}

resource appInsights 'Microsoft.Insights/components@2020-02-02' = {
  name: '${prefix}-ai-${suffix}'
  location: location
  tags: tags
  kind: 'web'
  properties: { Application_Type: 'web', WorkspaceResourceId: logs.id }
}

// --------------------------------------------------------------------------- identity + registry

resource identity 'Microsoft.ManagedIdentity/userAssignedIdentities@2023-01-31' = {
  name: '${prefix}-id-${suffix}'
  location: location
  tags: tags
}

resource acr 'Microsoft.ContainerRegistry/registries@2023-07-01' = {
  name: acrName
  location: location
  tags: tags
  sku: { name: 'Basic' }
  properties: { adminUserEnabled: false }
}

var acrPullRole = subscriptionResourceId('Microsoft.Authorization/roleDefinitions', '7f951dda-4ed3-4680-a7ca-43fe172d538d')
resource acrPull 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(acr.id, identity.id, acrPullRole)
  scope: acr
  properties: { roleDefinitionId: acrPullRole, principalId: identity.properties.principalId, principalType: 'ServicePrincipal' }
}

// --------------------------------------------------------------------------- Event Hubs

resource eventHubs 'Microsoft.EventHub/namespaces@2024-01-01' = {
  name: ehName
  location: location
  tags: tags
  sku: { name: 'Standard', tier: 'Standard', capacity: 1 } // Standard: consumer groups per stage
  properties: { disableLocalAuth: true, minimumTlsVersion: '1.2' } // Entra ID only, no SAS keys
}

resource hub 'Microsoft.EventHub/namespaces/eventhubs@2024-01-01' = [
  for h in hubs: {
    parent: eventHubs
    name: h.name
    properties: { partitionCount: 2, messageRetentionInDays: 1 }
  }
]

resource groups 'Microsoft.EventHub/namespaces/eventhubs/consumergroups@2024-01-01' = [
  for cg in consumerGroups: {
    name: '${ehName}/${cg.hub}/${cg.group}'
    dependsOn: [hub]
  }
]

// Least privilege: the stages only send and receive data (no management rights).
var ehDataRoles = [
  'a638d3c7-ab3a-418d-83e6-5f17a39d4fde' // Azure Event Hubs Data Receiver
  '2b629674-e913-4c01-ae53-ef4638d8f975' // Azure Event Hubs Data Sender
]
resource ehData 'Microsoft.Authorization/roleAssignments@2022-04-01' = [
  for roleId in ehDataRoles: {
    name: guid(eventHubs.id, identity.id, roleId)
    scope: eventHubs
    properties: {
      roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', roleId)
      principalId: identity.properties.principalId
      principalType: 'ServicePrincipal'
    }
  }
]

// The agents call Foundry models with the same identity (Entra ID, no API key).
module foundryAccess 'foundry-access.bicep' = if (useFoundry && !empty(foundryResourceGroup) && !empty(foundryAccountName)) {
  name: 'foundry-access-${suffix}'
  scope: resourceGroup(foundryResourceGroup)
  params: {
    foundryAccountName: foundryAccountName
    principalId: identity.properties.principalId
  }
}

// --------------------------------------------------------------------------- Container Apps

resource environment 'Microsoft.App/managedEnvironments@2024-03-01' = {
  name: '${prefix}-env-${suffix}'
  location: location
  tags: tags
  properties: {
    appLogsConfiguration: {
      destination: 'log-analytics'
      logAnalyticsConfiguration: { customerId: logs.properties.customerId, sharedKey: logs.listKeys().primarySharedKey }
    }
  }
}

var commonEnv = [
  { name: 'BUS_BACKEND', value: 'eventhubs' }
  { name: 'EVENTHUB_NAMESPACE', value: '${ehName}.servicebus.windows.net' }
  { name: 'AZURE_CLIENT_ID', value: identity.properties.clientId } // DefaultAzureCredential -> this identity
  { name: 'SEGMENTS', value: 'demo' }
  { name: 'LLM', value: llm }
  { name: 'SPEED', value: matchSpeed }
  { name: 'FOUNDRY_PROJECT_ENDPOINT', value: foundryProjectEndpoint }
  { name: 'FOUNDRY_MODEL_STRONG', value: foundryModelStrong }
  { name: 'FOUNDRY_MODEL_FAST', value: foundryModelFast }
  // Real models get a rate limit and patient timeouts; the instant offline mock keeps the defaults.
  { name: 'PITCHMIND_RPM', value: useFoundry ? agentRpm : '0' }
  { name: 'PITCHMIND_AGENT_TIMEOUT_S', value: useFoundry ? agentTimeoutS : '8' }
  { name: 'PITCHMIND_MOMENT_DEADLINE_S', value: useFoundry ? '120' : '12' }
  { name: 'APPLICATIONINSIGHTS_CONNECTION_STRING', secretRef: 'appinsights' }
]

var registry = [{ server: acr.properties.loginServer, identity: identity.id }]
var userIdentity = { type: 'UserAssigned', userAssignedIdentities: { '${identity.id}': {} } }

// Background stages: no ingress, exactly one replica each (they hold live match state).
resource stageApps 'Microsoft.App/containerApps@2024-03-01' = [
  for stage in stages: if (!empty(pythonImage)) {
    name: '${prefix}-${stage}'
    location: location
    tags: union(tags, { stage: stage })
    identity: userIdentity
    dependsOn: [acrPull, ehData, groups]
    properties: {
      environmentId: environment.id
      configuration: {
        registries: registry
        secrets: [{ name: 'appinsights', value: appInsights.properties.ConnectionString }]
      }
      template: {
        containers: [
          {
            name: stage
            image: pythonImage
            args: [stage]
            env: commonEnv
            resources: { cpu: json('0.25'), memory: '0.5Gi' }
          }
        ]
        scale: { minReplicas: 1, maxReplicas: 1 }
      }
    }
  }
]

// Gateway: public WebSocket endpoint for the frontend (single replica: it keeps the catch-up state).
resource gateway 'Microsoft.App/containerApps@2024-03-01' = if (!empty(pythonImage)) {
  name: '${prefix}-gateway'
  location: location
  tags: union(tags, { stage: 'gateway' })
  identity: userIdentity
  dependsOn: [acrPull, ehData, groups]
  properties: {
    environmentId: environment.id
    configuration: {
      registries: registry
      secrets: [{ name: 'appinsights', value: appInsights.properties.ConnectionString }]
      ingress: { external: true, targetPort: 8765, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'gateway'
          image: pythonImage
          args: ['gateway']
          env: concat(commonEnv, [{ name: 'PORT', value: '8765' }])
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 1, maxReplicas: 1 }
    }
  }
}

// Frontend: stateless, scales to zero when nobody is watching.
resource web 'Microsoft.App/containerApps@2024-03-01' = if (!empty(webImage)) {
  name: '${prefix}-web'
  location: location
  tags: union(tags, { stage: 'web' })
  identity: userIdentity
  dependsOn: [acrPull]
  properties: {
    environmentId: environment.id
    configuration: {
      registries: registry
      ingress: { external: true, targetPort: 3000, transport: 'auto', allowInsecure: false }
    }
    template: {
      containers: [
        {
          name: 'web'
          image: webImage
          resources: { cpu: json('0.25'), memory: '0.5Gi' }
        }
      ]
      scale: { minReplicas: 0, maxReplicas: 2 }
    }
  }
}

output acrName string = acr.name
output acrLoginServer string = acr.properties.loginServer
output eventHubsNamespace string = '${ehName}.servicebus.windows.net'
output identityPrincipalId string = identity.properties.principalId
// Null-safe: the apps do not exist yet in the first deployment pass.
output gatewayFqdn string = gateway.?properties.configuration.ingress.fqdn ?? ''
output webFqdn string = web.?properties.configuration.ingress.fqdn ?? ''

// Lets the app identity call the models of an existing Microsoft Foundry resource,
// which may live in another resource group. Deployed by main.bicep when llm = foundry.

targetScope = 'resourceGroup'

@description('Name of the Foundry (Cognitive Services) account, e.g. pitchmind.')
param foundryAccountName string

@description('Object id of the app identity.')
param principalId string

var azureAiUser = '53ca6127-db72-4b80-b1b0-d745d6d5456d' // Azure AI User: call deployed models, no management rights

resource foundry 'Microsoft.CognitiveServices/accounts@2024-10-01' existing = {
  name: foundryAccountName
}

resource access 'Microsoft.Authorization/roleAssignments@2022-04-01' = {
  name: guid(foundry.id, principalId, azureAiUser)
  scope: foundry
  properties: {
    roleDefinitionId: subscriptionResourceId('Microsoft.Authorization/roleDefinitions', azureAiUser)
    principalId: principalId
    principalType: 'ServicePrincipal'
  }
}

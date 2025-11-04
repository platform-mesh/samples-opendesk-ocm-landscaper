REGISTRY ?= mcp-blueprints.common.repositories.cloud.sap/ocm

.PHONY: print-registry
print-registry: ## Print the registry URL
	@echo $(REGISTRY)

## OCM

OCM_VERSION_RAW=$(shell git describe --tags --always --dirty --match 'ocm-*')
OCM_VERSION=$(patsubst ocm-%,%,$(OCM_VERSION_RAW))

print-ocm-version: ## Print the OCM version
	@echo $(OCM_VERSION)
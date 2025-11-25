OCM_VERSION_RAW=$(shell git describe --tags --abbrev=0 --match 'ocm-*' 2>/dev/null || echo 'ocm-0.0.0')
OCM_VERSION_RAW_BUMPED=$(shell echo $(OCM_VERSION_RAW) | awk -F. '/[0-9]+\./{$$NF++;print}' OFS=.)

OCM_VERSION=$(patsubst ocm-%,%,$(if $(filter ocm-0.0.0,$(OCM_VERSION_RAW)),ocm-0.0.1,$(OCM_VERSION_RAW)))
OCM_VERSION_BUMPED=$(patsubst ocm-%,%,$(OCM_VERSION_RAW_BUMPED))

print-ocm-version: ## Print the OCM version
	@echo $(OCM_VERSION)

print-ocm-version-bumped: ## Print the OCM version with patch version increased
	@echo $(OCM_VERSION_BUMPED)

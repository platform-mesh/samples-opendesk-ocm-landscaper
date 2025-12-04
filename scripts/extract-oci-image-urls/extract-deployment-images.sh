#!/bin/bash

# Script to extract OCI image URLs and Helm chart labels from all deployments and statefulsets across namespaces
# Excludes kube-system namespace by default

set -euo pipefail

# Colors for output formatting
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# Function to print usage
usage() {
    echo "Usage: $0 [OPTIONS]"
    echo "Options:"
    echo "  -h, --help          Show this help message"
    echo "  -n, --namespace     Specify a specific namespace (default: all except excluded namespaces)"
    echo "  -e, --exclude NS    Exclude specific namespace (default: kube-system, can be used multiple times)"
    echo "  -o, --output FORMAT Output format: table (default), csv, json, yaml"
    echo "  -f, --file PATH     Output results to specified file (automatically detects format from extension)"
    echo ""
    echo "Examples:"
    echo "  $0                              # All deployments and statefulsets except kube-system"
    echo "  $0 -n default                   # Only default namespace"
    echo "  $0 -e kube-system -e monitoring # Exclude kube-system and monitoring namespaces"
    echo "  $0 -e ''                        # Include all namespaces (no exclusions)"
    echo "  $0 -o csv                       # Output in CSV format"
    echo "  $0 -f images.yaml               # Output to YAML file"
    echo "  $0 -o json -f results.json      # Output to JSON file"
}

# Default values
SPECIFIC_NAMESPACE=""
EXCLUDED_NAMESPACES=("kube-system")
OUTPUT_FORMAT="table"
OUTPUT_FILE=""

# Parse command line arguments
while [[ $# -gt 0 ]]; do
    case $1 in
        -h|--help)
            usage
            exit 0
            ;;
        -n|--namespace)
            SPECIFIC_NAMESPACE="$2"
            shift 2
            ;;
        -e|--exclude)
            if [[ "$2" == "" ]]; then
                # Empty string means clear all exclusions
                EXCLUDED_NAMESPACES=()
            else
                EXCLUDED_NAMESPACES+=("$2")
            fi
            shift 2
            ;;
        -o|--output)
            OUTPUT_FORMAT="$2"
            shift 2
            ;;
        -f|--file)
            OUTPUT_FILE="$2"
            # Auto-detect format from file extension if not explicitly set
            if [[ "$OUTPUT_FORMAT" == "table" ]]; then
                case "${OUTPUT_FILE##*.}" in
                    yaml|yml)
                        OUTPUT_FORMAT="yaml"
                        ;;
                    json)
                        OUTPUT_FORMAT="json"
                        ;;
                    csv)
                        OUTPUT_FORMAT="csv"
                        ;;
                esac
            fi
            shift 2
            ;;
        *)
            echo -e "${RED}Unknown option: $1${NC}" >&2
            usage
            exit 1
            ;;
    esac
done

# Validate output format
if [[ ! "$OUTPUT_FORMAT" =~ ^(table|csv|json|yaml)$ ]]; then
    echo -e "${RED}Error: Invalid output format '$OUTPUT_FORMAT'. Use 'table', 'csv', 'json', or 'yaml'${NC}" >&2
    exit 1
fi

# Check if kubectl is available
if ! command -v kubectl &> /dev/null; then
    echo -e "${RED}Error: kubectl is not installed or not in PATH${NC}" >&2
    exit 1
fi

# Check if kubectl can connect to cluster
if ! kubectl cluster-info &> /dev/null; then
    echo -e "${RED}Error: Cannot connect to Kubernetes cluster. Check your kubeconfig.${NC}" >&2
    exit 1
fi

echo -e "${BLUE}Extracting resource information from deployments and statefulsets...${NC}" >&2

# Function to get namespaces
get_namespaces() {
    if [[ -n "$SPECIFIC_NAMESPACE" ]]; then
        echo "$SPECIFIC_NAMESPACE"
    else
        local all_namespaces
        all_namespaces=$(kubectl get namespaces -o jsonpath='{.items[*].metadata.name}')
        
        if [[ ${#EXCLUDED_NAMESPACES[@]} -eq 0 ]]; then
            # No exclusions, return all namespaces
            echo "$all_namespaces"
        else
            # Filter out excluded namespaces
            local filtered_namespaces=""
            for ns in $all_namespaces; do
                local exclude=false
                for excluded in "${EXCLUDED_NAMESPACES[@]}"; do
                    if [[ "$ns" == "$excluded" ]]; then
                        exclude=true
                        break
                    fi
                done
                if [[ "$exclude" == "false" ]]; then
                    filtered_namespaces="$filtered_namespaces $ns"
                fi
            done
            echo "$filtered_namespaces"
        fi
    fi
}

# Function to extract images from deployments and statefulsets
extract_images() {
    local namespace=$1
    local resource_data
    
    # Get all deployments in the namespace with their container images
    resource_data=$(kubectl get deployments -n "$namespace" -o json 2>/dev/null || echo '{"items":[]}')
    
    # Parse the JSON and extract required information from deployments
    echo "$resource_data" | jq -r --arg ns "$namespace" --arg type "Deployment" '
        .items[] |
        .metadata.name as $resource_name |
        (.metadata.labels["helm.sh/chart"] // "") as $helm_chart |
        (.metadata.labels["app.kubernetes.io/instance"] // "") as $app_instance |
        .spec.template.spec.containers[]? |
        [$resource_name, $ns, $type, .name, .image, $helm_chart, $app_instance] |
        @tsv
    ' 2>/dev/null || true
    
    # Get all statefulsets in the namespace with their container images
    resource_data=$(kubectl get statefulsets -n "$namespace" -o json 2>/dev/null || echo '{"items":[]}')
    
    # Parse the JSON and extract required information from statefulsets
    echo "$resource_data" | jq -r --arg ns "$namespace" --arg type "StatefulSet" '
        .items[] |
        .metadata.name as $resource_name |
        (.metadata.labels["helm.sh/chart"] // "") as $helm_chart |
        (.metadata.labels["app.kubernetes.io/instance"] // "") as $app_instance |
        .spec.template.spec.containers[]? |
        [$resource_name, $ns, $type, .name, .image, $helm_chart, $app_instance] |
        @tsv
    ' 2>/dev/null || true
}

# Function to parse OCI image URL into components
parse_oci_image() {
    local image_url="$1"
    local registry=""
    local image=""
    local version=""
    local pin=""
    
    # Handle different image URL formats:
    # registry.io/namespace/image:tag@sha256:digest
    # registry.io/image:tag
    # image:tag
    # image@sha256:digest
    
    if [[ "$image_url" =~ ^([^/]+\.[^/]+)/(.+)$ ]]; then
        # Has registry (contains dot in first part)
        registry="${BASH_REMATCH[1]}"
        image_url="${BASH_REMATCH[2]}"
    fi
    
    # Check for digest pin (@sha256:...)
    if [[ "$image_url" =~ ^(.+)@(sha256:[a-f0-9]+)$ ]]; then
        image_url="${BASH_REMATCH[1]}"
        pin="${BASH_REMATCH[2]}"
    fi
    
    # Check for version tag (:version)
    if [[ "$image_url" =~ ^(.+):([^:]+)$ ]]; then
        image="${BASH_REMATCH[1]}"
        version="${BASH_REMATCH[2]}"
    else
        image="$image_url"
        version="latest"
    fi
    
    # Prepend registry if it exists
    if [[ -n "$registry" ]]; then
        image="$registry/$image"
    fi
    
    # Return as tab-separated values
    echo -e "$image\t$version\t$pin"
}

# Collect all data
echo -e "${YELLOW}Scanning namespaces...${NC}" >&2

declare -a results=()
namespaces=$(get_namespaces)

for namespace in $namespaces; do
    echo -e "${YELLOW}Processing namespace: $namespace${NC}" >&2
    
    # Check if namespace exists and is accessible
    if ! kubectl get namespace "$namespace" &>/dev/null; then
        echo -e "${RED}Warning: Cannot access namespace '$namespace'${NC}" >&2
        continue
    fi
    
    while IFS=$'\t' read -r resource_name ns resource_type container_name image_url helm_chart app_instance; do
        if [[ -n "$resource_name" ]]; then
            # Parse OCI image components for YAML format
            IFS=$'\t' read -r oci_image oci_version oci_pin < <(parse_oci_image "$image_url")
            results+=("$resource_name	$ns	$resource_type	$container_name	$image_url	$oci_image	$oci_version	$oci_pin	$helm_chart	$app_instance")
        fi
    done < <(extract_images "$namespace")
done

echo -e "${GREEN}Scan completed. Found ${#results[@]} container images.${NC}" >&2

# Function to output results
output_results() {
    case "$OUTPUT_FORMAT" in
        "table")
            echo ""
            printf "%-30s %-15s %-15s %-25s %-30s %-25s %s\n" "RESOURCE NAME" "NAMESPACE" "TYPE" "CONTAINER NAME" "HELM CHART" "APP INSTANCE" "OCI IMAGE URL"
            printf "%-30s %-15s %-15s %-25s %-30s %-25s %s\n" "------------------------------" "---------------" "---------------" "-------------------------" "------------------------------" "-------------------------" "--------------------------------------------------"
            
            for result in "${results[@]}"; do
                IFS=$'\t' read -r resource_name namespace resource_type container_name image_url oci_image oci_version oci_pin helm_chart app_instance <<< "$result"
                printf "%-30s %-15s %-15s %-25s %-30s %-25s %s\n" "$resource_name" "$namespace" "$resource_type" "$container_name" "$helm_chart" "$app_instance" "$image_url"
            done
            ;;
            
        "csv")
            echo "resource_name,namespace,resource_type,container_name,helm_chart,app_instance,oci_image_url"
            for result in "${results[@]}"; do
                IFS=$'\t' read -r resource_name namespace resource_type container_name image_url oci_image oci_version oci_pin helm_chart app_instance <<< "$result"
                # Escape commas and quotes in CSV
                resource_name=$(echo "$resource_name" | sed 's/"/"""/g; s/.*/"&"/')
                namespace=$(echo "$namespace" | sed 's/"/"""/g; s/.*/"&"/')
                resource_type=$(echo "$resource_type" | sed 's/"/"""/g; s/.*/"&"/')
                container_name=$(echo "$container_name" | sed 's/"/"""/g; s/.*/"&"/')
                helm_chart=$(echo "$helm_chart" | sed 's/"/"""/g; s/.*/"&"/')
                app_instance=$(echo "$app_instance" | sed 's/"/"""/g; s/.*/"&"/')
                image_url=$(echo "$image_url" | sed 's/"/"""/g; s/.*/"&"/')
                echo "$resource_name,$namespace,$resource_type,$container_name,$helm_chart,$app_instance,$image_url"
            done
            ;;
            
        "json")
            echo "["
            first=true
            for result in "${results[@]}"; do
                IFS=$'\t' read -r resource_name namespace resource_type container_name image_url oci_image oci_version oci_pin helm_chart app_instance <<< "$result"
                if [[ "$first" == "true" ]]; then
                    first=false
                else
                    echo ","
                fi
                printf '  {"resource_name": "%s", "namespace": "%s", "resource_type": "%s", "container_name": "%s", "helm_chart": "%s", "app_instance": "%s", "oci_image_url": "%s"}' \
                    "$(echo "$resource_name" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$namespace" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$resource_type" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$container_name" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$helm_chart" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$app_instance" | sed 's/\\/\\\\/g; s/"/\\"/g')" \
                    "$(echo "$image_url" | sed 's/\\/\\\\/g; s/"/\\"/g')"
            done
            echo ""
            echo "]"
            ;;
            
        "yaml")
            echo "images:"
            for result in "${results[@]}"; do
                IFS=$'\t' read -r resource_name namespace resource_type container_name image_url oci_image oci_version oci_pin helm_chart app_instance <<< "$result"
                echo "- resourceName: \"$resource_name\""
                echo "  namespace: \"$namespace\""
                echo "  resourceType: \"$resource_type\""
                echo "  containerName: \"$container_name\""
                echo "  helmChart: \"$helm_chart\""
                echo "  appInstance: \"$app_instance\""
                echo "  ociUrl: \"$oci_image\""
                echo "  ociVersion: \"$oci_version\""
                if [[ -n "$oci_pin" ]]; then
                    echo "  ociPin: \"$oci_pin\""
                else
                    echo "  ociPin: \"\""
                fi
            done
            ;;
    esac
}

# Output results in requested format
if [[ -n "$OUTPUT_FILE" ]]; then
    output_results > "$OUTPUT_FILE"
    echo -e "${GREEN}Results written to: $OUTPUT_FILE${NC}" >&2
else
    output_results
fi

# Summary
if [[ "$OUTPUT_FORMAT" == "table" ]]; then
    echo ""
    echo -e "${GREEN}Summary:${NC}"
    echo -e "  Total deployments and statefulsets with containers: ${#results[@]}"
    echo -e "  Namespaces scanned: $(echo "$namespaces" | wc -w | tr -d ' ')"
    if [[ ${#EXCLUDED_NAMESPACES[@]} -gt 0 ]] && [[ -z "$SPECIFIC_NAMESPACE" ]]; then
        echo -e "  Excluded namespaces: ${EXCLUDED_NAMESPACES[*]}"
    fi
fi
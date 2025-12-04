#!/usr/bin/env python3
"""
Enhanced script to create a summary table of HelmRelease to OCIRepository to Resource mappings
from a KRO Resource Graph Definition file.
"""

import yaml
import re
from pathlib import Path
import sys


def analyze_kro_mappings(yaml_file_path):
    """Analyze KRO file and return complete mappings chain."""
    
    # Load YAML
    with open(yaml_file_path, 'r', encoding='utf-8') as file:
        data = yaml.safe_load(file)
    
    resources = data['spec']['resources']
    
    # Find HelmReleases, OCIRepositories, and Resources
    helm_releases = []
    oci_repositories = []
    resource_definitions = []
    
    for resource in resources:
        if 'template' in resource and isinstance(resource['template'], dict):
            kind = resource['template'].get('kind')
            if kind == 'HelmRelease':
                helm_releases.append(resource)
            elif kind == 'OCIRepository':
                oci_repositories.append(resource)
            elif kind == 'Resource' and resource['template'].get('apiVersion') == 'delivery.ocm.software/v1alpha1':
                resource_definitions.append(resource)
    
    # Create mappings
    oci_by_id = {repo['id']: repo for repo in oci_repositories if 'id' in repo}
    resource_by_id = {res['id']: res for res in resource_definitions if 'id' in res}
    
    # Parse template expressions
    def parse_helm_to_oci(chart_ref):
        pattern = r'\$\{\s*([a-zA-Z][a-zA-Z0-9]*)\s*\.metadata\.name\s*\}'
        match = re.search(pattern, chart_ref)
        return match.group(1) if match else None
    
    def parse_oci_to_resource(url):
        pattern = r'\$\{\s*([a-zA-Z][a-zA-Z0-9]*)\s*\.status\.additional\.\?registry\s*\}'
        match = re.search(pattern, url)
        return match.group(1) if match else None
    
    def extract_resource_reference_info(resource):
        result = {'referencePath': None, 'resourceName': None}
        try:
            resource_spec = resource['template']['spec']['resource']['byReference']
            if 'referencePath' in resource_spec and resource_spec['referencePath']:
                reference_path = resource_spec['referencePath']
                if isinstance(reference_path, list) and len(reference_path) > 0:
                    result['referencePath'] = reference_path[0].get('name')
            if 'resource' in resource_spec:
                result['resourceName'] = resource_spec['resource'].get('name')
        except (KeyError, TypeError, IndexError):
            pass
        return result
    
    # Find mappings
    complete_mappings = []
    unmapped_helm = []
    
    for hr in helm_releases:
        chart_ref = hr.get('template', {}).get('spec', {}).get('chartRef', {}).get('name', '')
        oci_var_name = parse_helm_to_oci(chart_ref)
        
        if oci_var_name and oci_var_name in oci_by_id:
            oci_repo = oci_by_id[oci_var_name]
            oci_url = oci_repo.get('template', {}).get('spec', {}).get('url', '')
            resource_var_name = parse_oci_to_resource(oci_url)
            
            if resource_var_name and resource_var_name in resource_by_id:
                resource_def = resource_by_id[resource_var_name]
                resource_ref_info = extract_resource_reference_info(resource_def)
                complete_mappings.append((hr, oci_repo, resource_def, resource_ref_info))
            else:
                complete_mappings.append((hr, oci_repo, None, None))
        else:
            unmapped_helm.append(hr)
    
    return complete_mappings, unmapped_helm, len(helm_releases), len(oci_repositories), len(resource_definitions)


def print_summary_table(mappings, unmapped, total_helm, total_oci, total_resources):
    """Print a comprehensive summary table."""
    
    print("KRO Complete Chain Mapping Summary")
    print("=" * 160)
    print(f"Total HelmReleases: {total_helm}")
    print(f"Total OCIRepositories: {total_oci}")
    print(f"Total Resources: {total_resources}")
    print(f"Complete chains mapped: {len([m for m in mappings if m[2] is not None])}")
    print(f"Partial chains (missing Resource): {len([m for m in mappings if m[2] is None])}")
    print(f"Unmapped HelmReleases: {len(unmapped)}")
    print()
    
    if mappings:
        print("Complete Chain Mappings: HelmRelease → OCIRepository → Resource")
        print("-" * 160)
        print(f"{'#':<3} {'HelmRelease':<35} {'OCIRepository':<35} {'Resource':<35} {'RefPath/ResName':<50}")
        print("-" * 160)
        
        for i, (hr, oci, resource, ref_info) in enumerate(mappings, 1):
            hr_id = hr.get('id', 'Unknown')[:34]
            oci_id = oci.get('id', 'Unknown')[:34]
            
            if resource:
                resource_id = resource.get('id', 'Unknown')[:34]
                ref_path = ref_info['referencePath'] if ref_info else 'Unknown'
                res_name = ref_info['resourceName'] if ref_info else 'Unknown'
                ref_display = f"{ref_path}/{res_name}"[:49]
            else:
                resource_id = '[Not mapped]'
                ref_display = '[Not mapped]'
            
            print(f"{i:<3} {hr_id:<35} {oci_id:<35} {resource_id:<35} {ref_display:<50}")
    
    if unmapped:
        print(f"\nUnmapped HelmReleases:")
        print("-" * 30)
        for hr in unmapped:
            hr_id = hr.get('id', 'Unknown')
            chart_ref = hr.get('template', {}).get('spec', {}).get('chartRef', {}).get('name', '')
            print(f"  - {hr_id}")
            print(f"    Chart Ref: {chart_ref}")


def main():
    # Default path
    default_yaml_path = "/home/vm/projects/SAP/poc-bmi-opendesk-ocm-k8s-toolkit/ocm/k8s-manifests/kro-rgd.yaml"
    
    yaml_path = sys.argv[1] if len(sys.argv) > 1 else default_yaml_path
    
    if not Path(yaml_path).exists():
        print(f"Error: File not found: {yaml_path}")
        sys.exit(1)
    
    try:
        mappings, unmapped, total_helm, total_oci, total_resources = analyze_kro_mappings(yaml_path)
        print_summary_table(mappings, unmapped, total_helm, total_oci, total_resources)
    except Exception as e:
        print(f"Error analyzing file: {e}")
        sys.exit(1)


if __name__ == "__main__":
    main()
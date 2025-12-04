#!/usr/bin/env python3
"""
Script to analyze KRO Resource Graph Definition and map HelmRelease resources 
to their corresponding OCIRepository resources, and OCIRepository resources
to their corresponding Resource resources.

This script parses the YAML file and finds relationships between:
1. HelmRelease resources and OCIRepository resources (via chartRef.name field)
2. OCIRepository resources and Resource resources (via url field template expressions)
"""

import yaml
import re
import sys
from typing import Dict, List, Tuple, Optional
from pathlib import Path


class KROAnalyzer:
    def __init__(self, yaml_file_path: str):
        self.yaml_file_path = yaml_file_path
        self.data = self._load_yaml()
        self.resources = self._extract_resources()
        
    def _load_yaml(self) -> Dict:
        """Load and parse the YAML file."""
        try:
            with open(self.yaml_file_path, 'r', encoding='utf-8') as file:
                return yaml.safe_load(file)
        except Exception as e:
            print(f"Error loading YAML file: {e}")
            sys.exit(1)
    
    def _extract_resources(self) -> List[Dict]:
        """Extract all resources from the spec."""
        try:
            return self.data['spec']['resources']
        except KeyError:
            print("Error: Unable to find spec.resources in the YAML structure")
            sys.exit(1)
    
    def find_helm_releases(self) -> List[Dict]:
        """Find all HelmRelease resources in the schema."""
        helm_releases = []
        
        for resource in self.resources:
            if isinstance(resource, dict) and 'template' in resource:
                template = resource['template']
                if (isinstance(template, dict) and 
                    template.get('kind') == 'HelmRelease'):
                    helm_releases.append(resource)
        
        return helm_releases
    
    def find_oci_repositories(self) -> List[Dict]:
        """Find all OCIRepository resources in the schema."""
        oci_repositories = []
        
        for resource in self.resources:
            if isinstance(resource, dict) and 'template' in resource:
                template = resource['template']
                if (isinstance(template, dict) and 
                    template.get('kind') == 'OCIRepository'):
                    oci_repositories.append(resource)
        
        return oci_repositories
    
    def find_resources(self) -> List[Dict]:
        """Find all Resource resources in the schema."""
        resources = []
        
        for resource in self.resources:
            if isinstance(resource, dict) and 'template' in resource:
                template = resource['template']
                if (isinstance(template, dict) and 
                    template.get('kind') == 'Resource' and
                    template.get('apiVersion') == 'delivery.ocm.software/v1alpha1'):
                    resources.append(resource)
        
        return resources
    
    def extract_chart_ref_name(self, helm_release: Dict) -> Optional[str]:
        """Extract the chartRef.name from a HelmRelease resource."""
        try:
            chart_ref = helm_release['template']['spec']['chartRef']
            if 'name' in chart_ref:
                return chart_ref['name']
        except KeyError:
            pass
        return None
    
    def extract_oci_metadata_name(self, oci_repository: Dict) -> Optional[str]:
        """Extract the metadata.name from an OCIRepository resource."""
        try:
            return oci_repository['template']['metadata']['name']
        except KeyError:
            return None
    
    def extract_oci_url(self, oci_repository: Dict) -> Optional[str]:
        """Extract the url from an OCIRepository resource."""
        try:
            return oci_repository['template']['spec']['url']
        except KeyError:
            return None
    
    def extract_resource_reference_info(self, resource: Dict) -> Dict[str, Optional[str]]:
        """
        Extract reference information from a Resource.
        Returns a dict with referencePath and resource name.
        """
        result = {
            'referencePath': None,
            'resourceName': None
        }
        
        try:
            resource_spec = resource['template']['spec']['resource']['byReference']
            
            # Extract referencePath name
            if 'referencePath' in resource_spec and resource_spec['referencePath']:
                reference_path = resource_spec['referencePath']
                if isinstance(reference_path, list) and len(reference_path) > 0:
                    result['referencePath'] = reference_path[0].get('name')
            
            # Extract resource name
            if 'resource' in resource_spec:
                result['resourceName'] = resource_spec['resource'].get('name')
                
        except (KeyError, TypeError, IndexError):
            pass
            
        return result
    
    def parse_template_expression(self, expression: str) -> Optional[str]:
        """
        Parse template expressions like '${ opendeskhomeOCIRepository.metadata.name }'
        to extract the variable name (e.g., 'opendeskhomeOCIRepository').
        """
        if not isinstance(expression, str):
            return None
            
        # Match template expressions like ${ variableName.metadata.name }
        pattern = r'\$\{\s*([a-zA-Z][a-zA-Z0-9]*)\s*\.metadata\.name\s*\}'
        match = re.search(pattern, expression)
        
        if match:
            return match.group(1)
        
        return None
    
    def parse_oci_url_template(self, url: str) -> Optional[str]:
        """
        Parse OCIRepository URL template expressions like 
        'oci://${ opendeskhomeResourceChart.status.additional.?registry }/${ opendeskhomeResourceChart.status.additional.?repository }'
        to extract the Resource variable name (e.g., 'opendeskhomeResourceChart').
        """
        if not isinstance(url, str):
            return None
            
        # Match template expressions like ${ variableName.status.additional.?registry }
        pattern = r'\$\{\s*([a-zA-Z][a-zA-Z0-9]*)\s*\.status\.additional\.\?registry\s*\}'
        match = re.search(pattern, url)
        
        if match:
            return match.group(1)
        
        return None
    
    def map_helm_to_oci(self) -> List[Tuple[Dict, Dict]]:
        """
        Map HelmRelease resources to their corresponding OCIRepository resources.
        Returns a list of tuples: (helm_release, oci_repository)
        """
        helm_releases = self.find_helm_releases()
        oci_repositories = self.find_oci_repositories()
        
        # Create a mapping of OCIRepository IDs to their resources
        oci_by_id = {repo['id']: repo for repo in oci_repositories if 'id' in repo}
        
        mappings = []
        
        for helm_release in helm_releases:
            chart_ref_name = self.extract_chart_ref_name(helm_release)
            
            if chart_ref_name:
                # Parse the template expression to get the OCIRepository variable name
                oci_var_name = self.parse_template_expression(chart_ref_name)
                
                if oci_var_name and oci_var_name in oci_by_id:
                    corresponding_oci = oci_by_id[oci_var_name]
                    mappings.append((helm_release, corresponding_oci))
        
        return mappings
    
    def map_oci_to_resource(self) -> List[Tuple[Dict, Dict]]:
        """
        Map OCIRepository resources to their corresponding Resource resources.
        Returns a list of tuples: (oci_repository, resource)
        """
        oci_repositories = self.find_oci_repositories()
        resources = self.find_resources()
        
        # Create a mapping of Resource IDs to their resources
        resource_by_id = {res['id']: res for res in resources if 'id' in res}
        
        mappings = []
        
        for oci_repository in oci_repositories:
            oci_url = self.extract_oci_url(oci_repository)
            
            if oci_url:
                # Parse the template expression to get the Resource variable name
                resource_var_name = self.parse_oci_url_template(oci_url)
                
                if resource_var_name and resource_var_name in resource_by_id:
                    corresponding_resource = resource_by_id[resource_var_name]
                    mappings.append((oci_repository, corresponding_resource))
        
        return mappings
    
    def print_analysis(self):
        """Print a detailed analysis of HelmRelease to OCIRepository to Resource mappings."""
        print("KRO Resource Graph Definition Analysis")
        print("=" * 70)
        print(f"Analyzing file: {self.yaml_file_path}")
        print()
        
        helm_releases = self.find_helm_releases()
        oci_repositories = self.find_oci_repositories()
        resources = self.find_resources()
        helm_to_oci_mappings = self.map_helm_to_oci()
        oci_to_resource_mappings = self.map_oci_to_resource()
        
        print(f"Found {len(helm_releases)} HelmRelease resources")
        print(f"Found {len(oci_repositories)} OCIRepository resources")
        print(f"Found {len(resources)} Resource resources")
        print(f"Found {len(helm_to_oci_mappings)} HelmRelease → OCIRepository mappings")
        print(f"Found {len(oci_to_resource_mappings)} OCIRepository → Resource mappings")
        print()
        
        # Create a mapping of OCIRepository IDs to Resource info for easier lookup
        oci_to_resource_map = {}
        for oci_repo, resource in oci_to_resource_mappings:
            oci_id = oci_repo.get('id')
            if oci_id:
                resource_ref_info = self.extract_resource_reference_info(resource)
                oci_to_resource_map[oci_id] = {
                    'resource': resource,
                    'reference_info': resource_ref_info
                }
        
        print("Complete Chain: HelmRelease → OCIRepository → Resource")
        print("-" * 70)
        
        for i, (helm_release, oci_repository) in enumerate(helm_to_oci_mappings, 1):
            helm_id = helm_release.get('id', 'Unknown')
            oci_id = oci_repository.get('id', 'Unknown')
            
            helm_name = self._get_resource_name(helm_release)
            oci_name = self._get_resource_name(oci_repository)
            oci_url = self.extract_oci_url(oci_repository)
            
            chart_ref_name = self.extract_chart_ref_name(helm_release)
            
            print(f"{i:2d}. HelmRelease: {helm_id}")
            print(f"    Resource Name: {helm_name}")
            print(f"    Chart Ref: {chart_ref_name}")
            print(f"    → OCIRepository: {oci_id}")
            print(f"      Resource Name: {oci_name}")
            print(f"      URL: {oci_url}")
            
            # Check if this OCIRepository maps to a Resource
            if oci_id in oci_to_resource_map:
                resource_info = oci_to_resource_map[oci_id]
                resource = resource_info['resource']
                ref_info = resource_info['reference_info']
                
                resource_id = resource.get('id', 'Unknown')
                resource_name = self._get_resource_name(resource)
                
                print(f"      → Resource: {resource_id}")
                print(f"        Resource Name: {resource_name}")
                print(f"        Reference Path: {ref_info['referencePath']}")
                print(f"        Resource Name: {ref_info['resourceName']}")
            else:
                print(f"      → Resource: [Not mapped]")
            
            # Check for includeWhen conditions
            helm_conditions = helm_release.get('includeWhen', [])
            oci_conditions = oci_repository.get('includeWhen', [])
            
            if helm_conditions or oci_conditions:
                print(f"    Conditions:")
                if helm_conditions:
                    print(f"      HelmRelease: {helm_conditions}")
                if oci_conditions:
                    print(f"      OCIRepository: {oci_conditions}")
            
            print()
        
        # Find unmapped HelmReleases
        mapped_helm_ids = {hr['id'] for hr, _ in helm_to_oci_mappings}
        unmapped_helm = [hr for hr in helm_releases if hr.get('id') not in mapped_helm_ids]
        
        if unmapped_helm:
            print("Unmapped HelmRelease resources:")
            print("-" * 30)
            for helm_release in unmapped_helm:
                helm_id = helm_release.get('id', 'Unknown')
                chart_ref_name = self.extract_chart_ref_name(helm_release)
                print(f"  - {helm_id}")
                print(f"    Chart Ref: {chart_ref_name}")
                print()
        
        # Find unmapped OCIRepositories
        mapped_oci_ids = {oci['id'] for oci, _ in oci_to_resource_mappings}
        unmapped_oci = [oci for oci in oci_repositories if oci.get('id') not in mapped_oci_ids]
        
        if unmapped_oci:
            print("Unmapped OCIRepository resources:")
            print("-" * 35)
            for oci_repository in unmapped_oci:
                oci_id = oci_repository.get('id', 'Unknown')
                oci_url = self.extract_oci_url(oci_repository)
                print(f"  - {oci_id}")
                print(f"    URL: {oci_url}")
                print()
    
    def _get_resource_name(self, resource: Dict) -> str:
        """Extract the resource name from template metadata."""
        try:
            return resource['template']['metadata']['name']
        except KeyError:
            return 'Unknown'
    
    def export_csv(self, output_file: str = None):
        """Export mappings to CSV format including Resource information."""
        if output_file is None:
            script_dir = Path(__file__).parent
            output_file = script_dir / "helm_oci_resource_mappings.csv"
        
        helm_to_oci_mappings = self.map_helm_to_oci()
        oci_to_resource_mappings = self.map_oci_to_resource()
        
        # Create a mapping of OCIRepository IDs to Resource info for easier lookup
        oci_to_resource_map = {}
        for oci_repo, resource in oci_to_resource_mappings:
            oci_id = oci_repo.get('id')
            if oci_id:
                resource_ref_info = self.extract_resource_reference_info(resource)
                oci_to_resource_map[oci_id] = {
                    'resource': resource,
                    'reference_info': resource_ref_info
                }
        
        try:
            import csv
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([
                    'HelmRelease_ID', 'HelmRelease_Name', 'ChartRef_Name',
                    'OCIRepository_ID', 'OCIRepository_Name', 'OCIRepository_URL',
                    'Resource_ID', 'Resource_Name', 'Resource_ReferencePath', 'Resource_ResourceName',
                    'HelmRelease_Conditions', 'OCIRepository_Conditions'
                ])
                
                for helm_release, oci_repository in helm_to_oci_mappings:
                    oci_id = oci_repository.get('id', '')
                    
                    # Get Resource information if available
                    resource_id = ''
                    resource_name = ''
                    resource_ref_path = ''
                    resource_resource_name = ''
                    
                    if oci_id in oci_to_resource_map:
                        resource_info = oci_to_resource_map[oci_id]
                        resource = resource_info['resource']
                        ref_info = resource_info['reference_info']
                        
                        resource_id = resource.get('id', '')
                        resource_name = self._get_resource_name(resource)
                        resource_ref_path = ref_info['referencePath'] or ''
                        resource_resource_name = ref_info['resourceName'] or ''
                    
                    writer.writerow([
                        helm_release.get('id', ''),
                        self._get_resource_name(helm_release),
                        self.extract_chart_ref_name(helm_release),
                        oci_id,
                        self._get_resource_name(oci_repository),
                        self.extract_oci_url(oci_repository),
                        resource_id,
                        resource_name,
                        resource_ref_path,
                        resource_resource_name,
                        str(helm_release.get('includeWhen', [])),
                        str(oci_repository.get('includeWhen', []))
                    ])
            
            print(f"Mappings exported to {output_file}")
        
        except Exception as e:
            print(f"Error exporting to CSV: {e}")


def main():
    """Main function to run the analysis."""
    # Default path to the KRO YAML file relative to scripts directory
    script_dir = Path(__file__).parent
    default_yaml_path = script_dir.parent.parent / "ocm" / "k8s-manifests" / "kro-rgd.yaml"
    
    # Check if file path is provided as argument
    if len(sys.argv) > 1:
        yaml_path = sys.argv[1]
    else:
        yaml_path = default_yaml_path
    
    # Check if file exists
    if not Path(yaml_path).exists():
        print(f"Error: File not found: {yaml_path}")
        print("Usage: python analyze_kro_helm_oci_mapping.py [path_to_kro_file.yaml]")
        sys.exit(1)
    
    # Create analyzer and run analysis
    analyzer = KROAnalyzer(yaml_path)
    analyzer.print_analysis()
    
    # Ask if user wants to export to CSV
    try:
        export_csv = input("\nExport results to CSV? (y/n): ").lower().strip()
        if export_csv in ['y', 'yes']:
            analyzer.export_csv()
    except KeyboardInterrupt:
        print("\nExiting...")


if __name__ == "__main__":
    main()
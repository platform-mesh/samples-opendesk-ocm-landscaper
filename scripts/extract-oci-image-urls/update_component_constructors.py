#!/usr/bin/env python3
"""
Script to update OCM component-constructor.yaml files with deployed container images.

This script:
1. Analyzes deployed images from cluster scan YAML
2. Correlates them with Helm chart mappings from KRO analysis CSV
3. Automatically adds ociImage resources to the appropriate component-constructor.yaml files
"""

import yaml
import csv
import re
import sys
import os
from pathlib import Path
from typing import Dict, List, Tuple, Optional
from dataclasses import dataclass


@dataclass
class DeployedImage:
    """Represents a deployed container image from the scan."""
    resource_name: str
    namespace: str
    resource_type: str
    container_name: str
    helm_chart: str
    app_instance: str
    oci_url: str
    oci_version: str
    oci_pin: str


@dataclass
class HelmMapping:
    """Represents a HelmRelease → OCIRepository → Resource mapping."""
    helm_release_id: str
    helm_release_name: str
    chart_ref_name: str
    oci_repository_id: str
    oci_repository_name: str
    oci_repository_url: str
    resource_id: str
    resource_name: str
    resource_reference_path: str
    resource_resource_name: str
    helm_release_conditions: str
    oci_repository_conditions: str


class ImageMappingAnalyzer:
    def __init__(self, scan_file_path: str, csv_file_path: str, ocm_apps_dir: str = None):
        self.scan_file_path = scan_file_path
        self.csv_file_path = csv_file_path
        # Default to relative path from scripts directory to ocm/apps
        script_dir = Path(__file__).parent
        default_ocm_apps = script_dir.parent.parent / "ocm" / "apps"
        self.ocm_apps_dir = ocm_apps_dir or str(default_ocm_apps)
        self.deployed_images = self._load_deployed_images()
        self.helm_mappings = self._load_helm_mappings()
        self.component_files = self._find_component_constructor_files()
        
    def _load_deployed_images(self) -> List[DeployedImage]:
        """Load deployed images from the scan YAML file."""
        try:
            with open(self.scan_file_path, 'r', encoding='utf-8') as file:
                data = yaml.safe_load(file)
            
            images = []
            for img_data in data.get('images', []):
                images.append(DeployedImage(
                    resource_name=img_data.get('resourceName', ''),
                    namespace=img_data.get('namespace', ''),
                    resource_type=img_data.get('resourceType', ''),
                    container_name=img_data.get('containerName', ''),
                    helm_chart=img_data.get('helmChart', ''),
                    app_instance=img_data.get('appInstance', ''),
                    oci_url=img_data.get('ociUrl', ''),
                    oci_version=img_data.get('ociVersion', ''),
                    oci_pin=img_data.get('ociPin', '')
                ))
            
            return images
        
        except Exception as e:
            print(f"Error loading scan file: {e}")
            sys.exit(1)
    
    def _load_helm_mappings(self) -> List[HelmMapping]:
        """Load Helm mappings from the CSV file."""
        try:
            mappings = []
            with open(self.csv_file_path, 'r', encoding='utf-8') as file:
                reader = csv.DictReader(file)
                for row in reader:
                    mappings.append(HelmMapping(
                        helm_release_id=row['HelmRelease_ID'],
                        helm_release_name=row['HelmRelease_Name'],
                        chart_ref_name=row['ChartRef_Name'],
                        oci_repository_id=row['OCIRepository_ID'],
                        oci_repository_name=row['OCIRepository_Name'],
                        oci_repository_url=row['OCIRepository_URL'],
                        resource_id=row['Resource_ID'],
                        resource_name=row['Resource_Name'],
                        resource_reference_path=row['Resource_ReferencePath'],
                        resource_resource_name=row['Resource_ResourceName'],
                        helm_release_conditions=row['HelmRelease_Conditions'],
                        oci_repository_conditions=row['OCIRepository_Conditions']
                    ))
            
            return mappings
        
        except Exception as e:
            print(f"Error loading CSV file: {e}")
            sys.exit(1)
    
    def _find_component_constructor_files(self) -> Dict[str, str]:
        """Find all component-constructor.yaml files in the OCM apps directory."""
        component_files = {}
        
        try:
            apps_path = Path(self.ocm_apps_dir)
            if not apps_path.exists():
                print(f"Warning: OCM apps directory not found: {self.ocm_apps_dir}")
                return {}
            
            for app_dir in apps_path.iterdir():
                if app_dir.is_dir():
                    component_file = app_dir / "component-constructor.yaml"
                    if component_file.exists():
                        component_files[app_dir.name] = str(component_file)
            
            print(f"Found {len(component_files)} component-constructor.yaml files:")
            for app_name, file_path in component_files.items():
                print(f"  - {app_name}: {file_path}")
            
            return component_files
        
        except Exception as e:
            print(f"Error finding component constructor files: {e}")
            return {}
    
    def _extract_chart_name_from_deployed(self, helm_chart: str) -> str:
        """
        Extract clean chart name from deployed image helm chart field.
        E.g., 'cert-manager-cainjector' -> 'cert-manager'
        E.g., 'collabora-online-1.1.41_6eb338d50269' -> 'collabora-online'
        """
        if not helm_chart:
            return ''
        
        # Remove version and hash suffixes (pattern: -version_hash)
        clean_chart = re.sub(r'-[\d\.]+_[a-f0-9]+$', '', helm_chart)
        
        # Remove standalone version numbers at the end
        clean_chart = re.sub(r'-[\d\.]+$', '', clean_chart)
        
        return clean_chart
    
    def _extract_chart_name_from_resource(self, resource_name: str) -> str:
        """
        Extract chart name from resource name.
        E.g., 'helm-chart-collabora-online' -> 'collabora-online'
        """
        if not resource_name:
            return ''
        
        # Remove 'helm-chart-' prefix
        if resource_name.startswith('helm-chart-'):
            return resource_name[11:]  # Remove 'helm-chart-' (11 characters)
        
        return resource_name
    
    def _normalize_app_instance_name(self, app_instance: str) -> str:
        """Normalize app instance name for comparison."""
        if not app_instance:
            return ''
        
        # Remove common prefixes/suffixes
        normalized = app_instance.replace('opendesk-', '').replace('-opendesk', '')
        
        # Handle specific cases
        if normalized == 'collabora-online':
            return 'collabora'
        elif normalized == 'clamav-simple':
            return 'clamav'
        elif normalized == 'matrix-user-verification-service':
            return 'matrix-user-verification'
        
        return normalized
    
    def find_correlations(self) -> List[Tuple[DeployedImage, Optional[HelmMapping], str]]:
        """
        Find correlations between deployed images and helm mappings.
        Returns list of tuples: (deployed_image, helm_mapping_or_none, match_reason)
        """
        correlations = []
        
        for deployed_image in self.deployed_images:
            best_match = None
            match_reason = "No match found"
            
            # Extract clean chart name from deployed image
            deployed_chart_name = self._extract_chart_name_from_deployed(deployed_image.helm_chart)
            normalized_app_instance = self._normalize_app_instance_name(deployed_image.app_instance)
            
            # Try to find matching helm mapping
            for mapping in self.helm_mappings:
                resource_chart_name = self._extract_chart_name_from_resource(mapping.resource_resource_name)
                
                # Method 1: Direct chart name match
                if deployed_chart_name and resource_chart_name:
                    if deployed_chart_name == resource_chart_name:
                        best_match = mapping
                        match_reason = f"Direct chart name match: {deployed_chart_name}"
                        break
                    
                    # Handle special cases for chart name variations
                    if self._are_chart_names_similar(deployed_chart_name, resource_chart_name):
                        best_match = mapping
                        match_reason = f"Similar chart names: {deployed_chart_name} ≈ {resource_chart_name}"
                        break
                
                # Method 2: App instance name match with component reference
                if normalized_app_instance and mapping.resource_reference_path:
                    if self._matches_component_pattern(normalized_app_instance, mapping.resource_reference_path):
                        if not best_match:  # Only if no direct chart match found
                            best_match = mapping
                            match_reason = f"App instance component match: {normalized_app_instance} in {mapping.resource_reference_path}"
                
                # Method 3: Resource name pattern matching
                if deployed_image.app_instance:
                    if self._matches_resource_pattern(deployed_image.app_instance, mapping.resource_resource_name):
                        if not best_match:  # Only if no better match found
                            best_match = mapping
                            match_reason = f"Resource pattern match: {deployed_image.app_instance} matches {mapping.resource_resource_name}"
            
            correlations.append((deployed_image, best_match, match_reason))
        
        return correlations
    
    def _are_chart_names_similar(self, name1: str, name2: str) -> bool:
        """Check if two chart names are similar (handle variations)."""
        # Handle common variations
        variations = {
            'cert-manager': ['cert-manager-cainjector', 'cert-manager-webhook'],
            'collabora-online': ['collabora'],
            'clamav-simple': ['clamav'],
            'ingress-nginx': ['nginx'],
            'opendesk-jitsi': ['jitsi'],
            'opendesk-nextcloud': ['nextcloud', 'aio', 'exporter'],
            'matrix-neoboard-widget': ['neoboard'],
            'matrix-neochoice-widget': ['neochoice'],
            'matrix-neodatefix-widget': ['neodatefix-widget'],
            'matrix-neodatefix-bot': ['neodatefix-bot'],
            'opendesk-element': ['element'],
            'opendesk-synapse': ['synapse'],
            'opendesk-synapse-web': ['synapse-web'],
            'opendesk-well-known': ['well-known'],
            'opendesk-static-files': ['static-files'],
            'opendesk-matrix-user-verification-service': ['matrix-user-verification'],
        }
        
        # Check direct variations
        for base_name, variants in variations.items():
            if (name1 == base_name and name2 in variants) or (name2 == base_name and name1 in variants):
                return True
            if name1 in variants and name2 in variants:
                return True
        
        # Check substring matching for similar names
        if len(name1) > 3 and len(name2) > 3:
            if name1 in name2 or name2 in name1:
                return True
        
        return False
    
    def _matches_component_pattern(self, app_instance: str, component_path: str) -> bool:
        """Check if app instance matches the component reference path pattern."""
        component_mappings = {
            'ums': 'nubus',
            'intercom': 'nubus',
            'keycloak': 'nubus',
            'nginx-s3-gateway': 'nubus',
            'dovecot': 'open-xchange',
            'open-xchange': 'open-xchange',
            'ox-connector': 'open-xchange',
            'nextcloud': 'nextcloud',
            'element': 'element',
            'synapse': 'element',
            'matrix': 'element',
            'collabora': 'collabora',
            'cryptpad': 'cryptpad',
            'jitsi': 'jitsi',
            'openproject': 'openproject',
            'xwiki': 'xwiki',
        }
        
        for app_pattern, component in component_mappings.items():
            if app_pattern in app_instance.lower() and component == component_path:
                return True
        
        return False
    
    def _matches_resource_pattern(self, app_instance: str, resource_name: str) -> bool:
        """Check if app instance matches resource name pattern."""
        if not app_instance or not resource_name:
            return False
        
        # Normalize both names
        app_normalized = app_instance.lower().replace('-', '').replace('_', '')
        resource_normalized = resource_name.lower().replace('-', '').replace('_', '').replace('helm', '').replace('chart', '')
        
        # Check if they contain similar keywords
        app_keywords = set(app_instance.lower().split('-'))
        resource_keywords = set(resource_name.lower().replace('helm-chart-', '').split('-'))
        
        # If more than half of keywords match, consider it a match
        if len(app_keywords & resource_keywords) >= min(2, len(app_keywords) * 0.5):
            return True
        
        return False
    
    def _generate_image_resource_name(self, deployed_image: DeployedImage) -> str:
        """Generate a descriptive name for the image resource."""
        # Extract meaningful parts from the deployed image
        resource_name = deployed_image.resource_name.lower()
        container_name = deployed_image.container_name.lower()
        
        # Remove common prefixes and suffixes
        resource_name = re.sub(r'^(opendesk-|ums-|matrix-)', '', resource_name)
        resource_name = re.sub(r'(-release|-deployment|-statefulset)$', '', resource_name)
        
        # Handle special cases
        if container_name != resource_name and container_name not in resource_name:
            if container_name in ['main', 'proxy', 'sidecar']:
                # Generic container names - use resource name
                name_part = resource_name
            else:
                # Specific container name - use it
                name_part = f"{resource_name}-{container_name}"
        else:
            name_part = resource_name
        
        # Clean up the name
        name_part = re.sub(r'[^a-z0-9-]', '-', name_part)
        name_part = re.sub(r'-+', '-', name_part)
        name_part = name_part.strip('-')
        
        return f"image-{name_part}"
    
    def _validate_semantic_version(self, version: str) -> str:
        """
        Validate if version follows semantic versioning pattern.
        First sanitize version by replacing disallowed characters with hyphens.
        If version doesn't match pattern, add '0.0.0-' prefix to make it valid.
        
        Args:
            version: Original version string
            
        Returns:
            Valid semantic version string
        """
        import re
        
        # First, replace any characters other than [.0-9a-zA-Z-] with hyphens
        sanitized_version = re.sub(r'[^.0-9a-zA-Z-]', '-', version)
        
        # OCM semantic version pattern
        semver_pattern = r'^[v]?(0|[1-9]\d*)(?:\.(0|[1-9]\d*))?(?:\.(0|[1-9]\d*))?(?:-((?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*)(?:\.(?:0|[1-9]\d*|\d*[a-zA-Z-][0-9a-zA-Z-]*))*))?(?:\+([0-9a-zA-Z-]+(?:\.[0-9a-zA-Z-]+)*))?$'
        
        # Check if sanitized version already matches semantic versioning
        if re.match(semver_pattern, sanitized_version):
            return sanitized_version
        
        # If not, add '0.0.0-' prefix to make it valid
        return f"0.0.0+{sanitized_version}"

    def _create_image_resource_entry(self, deployed_image: DeployedImage) -> Dict:
        """Create an OCM image resource entry for a deployed image."""
        resource_name = self._generate_image_resource_name(deployed_image)
        
        # Validate and fix version to comply with semantic versioning
        validated_version = self._validate_semantic_version(deployed_image.oci_version)
        
        # Build the image reference with digest if available (keep original version)
        if deployed_image.oci_pin and deployed_image.oci_pin.startswith('sha256:'):
            image_reference = f"{deployed_image.oci_url}:{deployed_image.oci_version}@{deployed_image.oci_pin}"
        else:
            image_reference = f"{deployed_image.oci_url}:{deployed_image.oci_version}"
        
        return {
            'name': resource_name,
            'type': 'ociImage',
            'version': validated_version,  # Use validated version here
            'access': {
                'type': 'ociArtifact',
                'imageReference': image_reference  # Keep original version in imageReference
            }
        }
    
    def _map_component_to_app_directory(self, component_path: str) -> Optional[str]:
        """Map component reference path to app directory name."""
        # Mapping from component reference paths to OCM app directory names
        component_mapping = {
            'opendesk-services': 'opendesk-services',
            'services-external': 'services-external',
            'nubus': 'nubus',
            'open-xchange': 'open-xchange',
            'nextcloud': 'nextcloud',
            'element': 'element',
            'collabora': 'collabora',
            'cryptpad': 'cryptpad',
            'jitsi': 'jitsi',
            'openproject': 'openproject',
            'opendesk-openproject-bootstrap': 'opendesk-openproject-bootstrap',
            'xwiki': 'xwiki'
        }
        
        return component_mapping.get(component_path)
    
    def _find_app_directory_for_chart(self, chart_resource_name: str) -> Optional[str]:
        """Find the app directory based on the chart resource name."""
        # More specific mapping based on chart names
        chart_to_app = {
            'helm-chart-opendesk-jitsi': 'jitsi',
            'helm-chart-collabora-online': 'collabora',
            'helm-chart-cryptpad': 'cryptpad',
            'helm-chart-opendesk-element': 'element',
            'helm-chart-opendesk-synapse': 'element',
            'helm-chart-opendesk-synapse-web': 'element',
            'helm-chart-opendesk-well-known': 'element',
            'helm-chart-matrix-neoboard-widget': 'element',
            'helm-chart-matrix-neochoice-widget': 'element',
            'helm-chart-matrix-neodatefix-widget': 'element',
            'helm-chart-matrix-neodatefix-bot': 'element',
            'helm-chart-opendesk-matrix-user-verification-service': 'element',
            'helm-chart-opendesk-nextcloud': 'nextcloud',
            'helm-chart-opendesk-nextcloud-management': 'nextcloud',
            'helm-chart-openproject': 'openproject',
            'helm-chart-opendesk-openproject-bootstrap': 'opendesk-openproject-bootstrap',
            'helm-chart-xwiki': 'xwiki',
            'helm-chart-nubus': 'nubus',
            'helm-chart-intercom-service': 'nubus',
            'helm-chart-nginx-s3-gateway': 'nubus',
            'helm-chart-opendesk-keycloak-bootstrap': 'nubus',
            'helm-chart-dovecot': 'open-xchange',
            'helm-chart-opendesk-open-xchange-bootstrap': 'open-xchange',
            'helm-chart-appsuite-public-sector': 'open-xchange',
            'helm-chart-ox-connector': 'open-xchange',
            'helm-chart-home': 'opendesk-services',
            'helm-chart-certificates': 'opendesk-services',
            'helm-chart-static-files': 'opendesk-services',
            'helm-chart-redis': 'services-external',
            'helm-chart-memcached': 'services-external',
            'helm-chart-postgresql': 'services-external',
            'helm-chart-mariadb': 'services-external',
            'helm-chart-postfix': 'services-external',
            'helm-chart-clamav': 'services-external',
            'helm-chart-minio': 'services-external'
        }
        
        return chart_to_app.get(chart_resource_name)
    
    def _match_image_to_helm_chart(self, deployed_image: DeployedImage, mapping: HelmMapping) -> str:
        """Determine which helm chart name an image belongs to based on the mapping."""
        if mapping and mapping.resource_resource_name:
            return mapping.resource_resource_name
        
        # Fallback: try to infer from the deployed image information
        helm_chart = deployed_image.helm_chart
        if helm_chart:
            # Try to match common patterns
            chart_name_mappings = {
                'mariadb': 'helm-chart-mariadb',
                'postgresql': 'helm-chart-postgresql', 
                'redis': 'helm-chart-redis',
                'memcached': 'helm-chart-memcached',
                'postfix': 'helm-chart-postfix',
                'clamav': 'helm-chart-clamav',
                'minio': 'helm-chart-minio',
                'collabora-online': 'helm-chart-collabora-online',
                'jitsi': 'helm-chart-opendesk-jitsi',
                'cryptpad': 'helm-chart-cryptpad',
                'element': 'helm-chart-opendesk-element',
                'synapse': 'helm-chart-opendesk-synapse',
                'nextcloud': 'helm-chart-opendesk-nextcloud',
                'openproject': 'helm-chart-openproject',
                'xwiki': 'helm-chart-xwiki',
                'nubus': 'helm-chart-nubus',
                'dovecot': 'helm-chart-dovecot',
            }
            
            # Check for direct matches or partial matches
            for pattern, chart_name in chart_name_mappings.items():
                if pattern in helm_chart.lower():
                    return chart_name
        
        # Default fallback - return the first helm chart resource name
        return None

    def _update_component_constructor_file(self, app_dir: str, image_data_list: List[Dict]) -> bool:
        """Update a component-constructor.yaml file with image resources while preserving formatting."""
        if app_dir not in self.component_files:
            print(f"Warning: No component-constructor.yaml found for app '{app_dir}'")
            return False
        
        file_path = self.component_files[app_dir]
        
        try:
            # Read the current file as text to preserve formatting and comments
            with open(file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
            
            # Also parse YAML to understand structure
            with open(file_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)
            
            if not data or 'components' not in data:
                print(f"Warning: Invalid component constructor file structure in {file_path}")
                return False
            
            # Find the first component (assuming single component per file)
            component = data['components'][0]
            if 'resources' not in component:
                print(f"Warning: No resources section found in {file_path}")
                return False
            
            # Group images by their corresponding helm chart
            images_by_chart = {}
            for item in image_data_list:
                deployed_image = item['deployed_image']
                mapping = item['mapping']
                chart_name = self._match_image_to_helm_chart(deployed_image, mapping)
                
                if chart_name:
                    if chart_name not in images_by_chart:
                        images_by_chart[chart_name] = []
                    images_by_chart[chart_name].append(item['image_resource'])
            
            # Find all helm chart resources and their positions in the text
            helm_charts_info = []
            for resource in component['resources']:
                if resource.get('type') == 'helmChart':
                    chart_name = resource.get('name', '')
                    helm_charts_info.append({
                        'name': chart_name,
                        'resource': resource
                    })
            
            # Remove existing ociImage resources from lines first
            new_lines = []
            i = 0
            while i < len(lines):
                line = lines[i]
                # Check if this line starts an ociImage resource
                if "- name:" in line and "image-" in line:
                    # Look ahead to see if this is an ociImage resource
                    is_oci_image = False
                    for j in range(i + 1, min(i + 10, len(lines))):
                        if "type: ociImage" in lines[j]:
                            is_oci_image = True
                            break
                        elif lines[j].strip().startswith('- name:'):
                            break
                    
                    if is_oci_image:
                        # Skip this entire resource
                        indent_level = len(line) - len(line.lstrip())
                        i += 1
                        while i < len(lines):
                            current_line = lines[i]
                            if current_line.strip() == '':
                                i += 1
                                continue
                            current_indent = len(current_line) - len(current_line.lstrip())
                            if current_indent <= indent_level and current_line.strip().startswith('- name:'):
                                break
                            if current_indent < indent_level and current_line.strip() and not current_line.strip().startswith('#'):
                                break
                            i += 1
                        continue
                
                new_lines.append(line)
                i += 1
            
            # Now find each helm chart and insert its corresponding images after it
            lines_to_insert = {}  # position -> list of lines to insert
            
            for chart_info in helm_charts_info:
                chart_name = chart_info['name']
                
                # Skip if no images for this chart
                if chart_name not in images_by_chart:
                    continue
                
                # Find this helm chart in the text
                chart_line_idx = None
                chart_end_idx = None
                
                for i, line in enumerate(new_lines):
                    if f"name: {chart_name}" in line and "helmChart" in ''.join(new_lines[max(0, i-2):i+5]):
                        chart_line_idx = i
                        # Find the end of this resource (next resource or end of resources)
                        indent_level = len(line) - len(line.lstrip())
                        for j in range(i + 1, len(new_lines)):
                            current_line = new_lines[j]
                            if current_line.strip() == '':
                                continue
                            current_indent = len(current_line) - len(current_line.lstrip())
                            # If we find a line with same or less indentation that starts with "- name:", it's the next resource
                            if (current_indent <= indent_level and current_line.strip().startswith('- name:')) or \
                               (current_indent < indent_level and current_line.strip() and not current_line.strip().startswith('#')):
                                chart_end_idx = j
                                break
                        if chart_end_idx is None:
                            chart_end_idx = len(new_lines)
                        break
                
                if chart_line_idx is not None:
                    # Generate YAML text for the images belonging to this chart
                    image_yaml_lines = []
                    
                    # Ensure there's a newline before adding the first image resource
                    # Check if the line at chart_end_idx-1 ends with a newline
                    if chart_end_idx > 0 and not new_lines[chart_end_idx - 1].endswith('\n'):
                        new_lines[chart_end_idx - 1] += '\n'
                    
                    for resource in images_by_chart[chart_name]:
                        base_indent = "      "  # Standard indentation for resources
                        
                        image_yaml_lines.append(f"{base_indent}- name: {resource['name']}\n")
                        image_yaml_lines.append(f"{base_indent}  type: {resource['type']}\n")
                        image_yaml_lines.append(f"{base_indent}  version: \"{resource['version']}\"\n")
                        image_yaml_lines.append(f"{base_indent}  access:\n")
                        image_yaml_lines.append(f"{base_indent}    type: {resource['access']['type']}\n")
                        image_yaml_lines.append(f"{base_indent}    imageReference: {resource['access']['imageReference']}\n")
                    
                    # Store the lines to be inserted at this position
                    lines_to_insert[chart_end_idx] = image_yaml_lines
            
            # Insert all the image resources at their respective positions (in reverse order to maintain indices)
            final_lines = new_lines.copy()
            for position in sorted(lines_to_insert.keys(), reverse=True):
                final_lines[position:position] = lines_to_insert[position]
            
            # Write back to file
            with open(file_path, 'w', encoding='utf-8') as f:
                f.writelines(final_lines)
            
            total_images = sum(len(imgs) for imgs in images_by_chart.values())
            print(f"✅ Updated {file_path} with {total_images} image resources grouped by {len(images_by_chart)} helm charts")
            return True
        
        except Exception as e:
            print(f"❌ Error updating {file_path}: {e}")
            return False
    
    def update_component_constructors(self) -> bool:
        """Update component-constructor.yaml files with deployed image information."""
        correlations = self.find_correlations()
        
        print("Updating Component Constructor Files")
        print("=" * 50)
        print(f"Analyzing {len(correlations)} deployed images...")
        print()
        
        # Group images by app directory
        app_images = {}
        matched_count = 0
        unmatched_count = 0
        
        for deployed_image, mapping, reason in correlations:
            if mapping:
                matched_count += 1
                # Try to find the app directory for this mapping
                app_dir = self._find_app_directory_for_chart(mapping.resource_resource_name)
                
                if not app_dir:
                    # Try mapping via component path
                    app_dir = self._map_component_to_app_directory(mapping.resource_reference_path)
                
                if app_dir:
                    if app_dir not in app_images:
                        app_images[app_dir] = []
                    
                    image_resource = self._create_image_resource_entry(deployed_image)
                    app_images[app_dir].append({
                        'image_resource': image_resource,
                        'deployed_image': deployed_image,
                        'mapping': mapping,
                        'reason': reason
                    })
                else:
                    print(f"⚠️  No app directory mapping found for {deployed_image.resource_name} "
                          f"(chart: {mapping.resource_resource_name}, component: {mapping.resource_reference_path}) [{reason}]")
            else:
                unmatched_count += 1
                print(f"⚠️  Unmatched image: {deployed_image.resource_name} ({deployed_image.helm_chart}) [{reason}]")
        
        # Collect and display association method statistics
        method_stats = {}
        for deployed_image, mapping, reason in correlations:
            if mapping:
                # Extract the main method from the reason
                if "Direct chart name match" in reason:
                    method = "Direct Chart Name"
                elif "Similar chart names" in reason:
                    method = "Similar Chart Names"
                elif "App instance component match" in reason:
                    method = "Component Path Match"
                elif "Resource pattern match" in reason:
                    method = "Resource Pattern"
                else:
                    method = "Other"
                method_stats[method] = method_stats.get(method, 0) + 1
        
        print(f"Summary: {matched_count} matched, {unmatched_count} unmatched")
        if method_stats:
            print("Association methods used:")
            for method, count in sorted(method_stats.items(), key=lambda x: x[1], reverse=True):
                print(f"  - {method}: {count} images")
        print(f"Found images for {len(app_images)} app directories:")
        for app_dir, images in app_images.items():
            print(f"  - {app_dir}: {len(images)} images")
        print()
        
        # Update each app's component constructor file
        updated_count = 0
        for app_dir, image_data in app_images.items():
            
            print(f"Updating {app_dir}:")
            for item in image_data:
                deployed = item['deployed_image']
                reason = item['reason']
                print(f"  + {item['image_resource']['name']} "
                      f"({deployed.oci_url}:{deployed.oci_version}) [{reason}]")
            
            if self._update_component_constructor_file(app_dir, image_data):
                updated_count += 1
            print()
        
        print(f"✅ Successfully updated {updated_count}/{len(app_images)} component constructor files")
        return updated_count > 0
    
    def print_analysis(self):
        """Print detailed analysis of image to helm mapping correlations."""
        correlations = self.find_correlations()
        
        print("Container Image to Helm Chart Mapping Analysis")
        print("=" * 80)
        print(f"Analyzing scan file: {self.scan_file_path}")
        print(f"Using mappings from: {self.csv_file_path}")
        print()
        
        matched_count = len([c for c in correlations if c[1] is not None])
        unmatched_count = len(correlations) - matched_count
        
        print(f"Total deployed images: {len(correlations)}")
        print(f"Successfully matched: {matched_count}")
        print(f"Unmatched: {unmatched_count}")
        print()
        
        # Print matched correlations
        if matched_count > 0:
            print("MATCHED CORRELATIONS:")
            print("-" * 80)
            
            for i, (deployed, mapping, reason) in enumerate([c for c in correlations if c[1] is not None], 1):
                print(f"{i:2d}. DEPLOYED IMAGE:")
                print(f"    Resource: {deployed.resource_name} ({deployed.resource_type})")
                print(f"    Container: {deployed.container_name}")
                print(f"    Helm Chart: {deployed.helm_chart}")
                print(f"    App Instance: {deployed.app_instance}")
                print(f"    Image: {deployed.oci_url}:{deployed.oci_version}")
                print(f"    → MATCHES HELM MAPPING:")
                print(f"      HelmRelease: {mapping.helm_release_id}")
                print(f"      OCIRepository: {mapping.oci_repository_id}")
                print(f"      Resource: {mapping.resource_id}")
                print(f"      Component: {mapping.resource_reference_path}")
                print(f"      Chart Resource: {mapping.resource_resource_name}")
                print(f"      Match Reason: {reason}")
                print()
        
        # Print unmatched images
        if unmatched_count > 0:
            print("UNMATCHED DEPLOYED IMAGES:")
            print("-" * 40)
            
            for deployed, _, reason in [c for c in correlations if c[1] is None]:
                print(f"  - Resource: {deployed.resource_name}")
                print(f"    Helm Chart: {deployed.helm_chart}")
                print(f"    App Instance: {deployed.app_instance}")
                print(f"    Image: {deployed.oci_url}:{deployed.oci_version}")
                print(f"    Reason: {reason}")
                print()
    
    def export_correlation_csv(self, output_file: str = None):
        """Export correlations to CSV format."""
        if output_file is None:
            script_dir = Path(__file__).parent
            output_file = script_dir / "image_helm_correlations.csv"
        
        correlations = self.find_correlations()
        
        try:
            import csv
            with open(output_file, 'w', newline='', encoding='utf-8') as csvfile:
                writer = csv.writer(csvfile)
                writer.writerow([
                    'Deployed_Resource_Name', 'Deployed_Resource_Type', 'Deployed_Container_Name',
                    'Deployed_Helm_Chart', 'Deployed_App_Instance', 'Deployed_OCI_URL', 'Deployed_OCI_Version',
                    'Matched_HelmRelease_ID', 'Matched_OCIRepository_ID', 'Matched_Resource_ID',
                    'Matched_Component_Path', 'Matched_Chart_Resource', 'Match_Reason'
                ])
                
                for deployed, mapping, reason in correlations:
                    if mapping:
                        writer.writerow([
                            deployed.resource_name, deployed.resource_type, deployed.container_name,
                            deployed.helm_chart, deployed.app_instance, deployed.oci_url, deployed.oci_version,
                            mapping.helm_release_id, mapping.oci_repository_id, mapping.resource_id,
                            mapping.resource_reference_path, mapping.resource_resource_name, reason
                        ])
                    else:
                        writer.writerow([
                            deployed.resource_name, deployed.resource_type, deployed.container_name,
                            deployed.helm_chart, deployed.app_instance, deployed.oci_url, deployed.oci_version,
                            '', '', '', '', '', reason
                        ])
            
            print(f"Correlations exported to {output_file}")
        
        except Exception as e:
            print(f"Error exporting to CSV: {e}")


def main():
    """Main function to run the component constructor update."""
    # Default paths relative to scripts directory
    script_dir = Path(__file__).parent
    default_scan_path = script_dir / "scans-extract-deployment-images" / "scan-opendeskk8s.blueprints.shoot.canary.k8s-hana.ondemand.com-06-11-2025.yaml"
    default_csv_path = script_dir / "helm_oci_resource_mappings.csv"
    
    # Check if file paths are provided as arguments
    if len(sys.argv) >= 3:
        scan_path = sys.argv[1]
        csv_path = sys.argv[2]
    else:
        scan_path = default_scan_path
        csv_path = default_csv_path
    
    # Check if files exist
    if not Path(scan_path).exists():
        print(f"Error: Scan file not found: {scan_path}")
        print("Usage: python analyze_image_helm_correlation.py [scan_file.yaml] [mappings.csv] [--dry-run]")
        print("  --dry-run: Show what would be updated without modifying files")
        sys.exit(1)
    
    if not Path(csv_path).exists():
        print(f"Error: CSV file not found: {csv_path}")
        print("Usage: python analyze_image_helm_correlation.py [scan_file.yaml] [mappings.csv] [--dry-run]")
        print("  --dry-run: Show what would be updated without modifying files")
        sys.exit(1)
    
    # Create analyzer and update component constructors
    analyzer = ImageMappingAnalyzer(scan_path, csv_path)
    
    # Check for --dry-run flag
    dry_run = '--dry-run' in sys.argv
    
    if dry_run:
        print("🔍 DRY RUN MODE - No files will be modified")
        print()
        analyzer.print_analysis()
    else:
        # Ask for confirmation before updating files
        try:
            confirm = input("This will modify component-constructor.yaml files. Continue? (y/n): ").lower().strip()
            if confirm not in ['y', 'yes']:
                print("Cancelled.")
                sys.exit(0)
        except KeyboardInterrupt:
            print("\nCancelled.")
            sys.exit(0)
        
        # Update the component constructor files
        success = analyzer.update_component_constructors()
        
        if success:
            print("\n💡 Next steps:")
            print("1. Review the updated component-constructor.yaml files")
            print("2. Test the OCM component building process")
            print("3. Commit the changes if everything looks correct")
        else:
            print("\n⚠️  Some updates failed. Please check the output above.")
            sys.exit(1)


if __name__ == "__main__":
    main()
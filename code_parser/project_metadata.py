"""Extract project-level metadata including languages, build tools, and package managers."""

import os
import json
import re
import subprocess
import xml.etree.ElementTree as ET
from typing import Dict, Any, List, Optional
from pathlib import Path
from datetime import datetime

from code_parser.framework_detector import detect_frameworks
from code_parser.multi_parser import detect_language
from utils.file_utils import collect_files


# Framework to package name mapping for version extraction
FRAMEWORK_PACKAGE_MAP = {
    "angular": "@angular/core",
    "react": "react",
    "vue": "vue",
    "nextjs": "next",
    "nestjs": "@nestjs/core",
    "express": "express",
    "fastify": "fastify",
    "koa": "koa",
    "fastapi": "fastapi",
    "flask": "flask",
    "django": "django",
}


def detect_languages(repo_path: str) -> List[str]:
    """
    Detect all languages used in the repository.
    
    Args:
        repo_path: Root path of the repository
        
    Returns:
        List of unique language names
    """
    languages = set()
    
    # Collect all files
    files = collect_files(repo_path)
    
    for file_path in files:
        lang = detect_language(file_path)
        if lang:
            languages.add(lang)
    
    return sorted(list(languages))


def detect_build_tools(repo_path: str) -> List[str]:
    """
    Detect build tools from configuration files.
    
    Args:
        repo_path: Root path of the repository
        
    Returns:
        List of build tool names
    """
    build_tools = []
    repo_path_obj = Path(repo_path)
    
    # npm/yarn/pnpm
    if (repo_path_obj / "package.json").exists():
        build_tools.append("npm")
        if (repo_path_obj / "yarn.lock").exists():
            build_tools.append("yarn")
        if (repo_path_obj / "pnpm-lock.yaml").exists():
            build_tools.append("pnpm")
    
    # Maven
    if (repo_path_obj / "pom.xml").exists():
        build_tools.append("maven")
    
    # Gradle
    if (repo_path_obj / "build.gradle").exists() or (repo_path_obj / "build.gradle.kts").exists():
        build_tools.append("gradle")
    
    # .NET
    if list(repo_path_obj.rglob("*.csproj")):
        build_tools.append("dotnet")
    
    # CMake
    if (repo_path_obj / "CMakeLists.txt").exists():
        build_tools.append("cmake")
    
    # Make
    if (repo_path_obj / "Makefile").exists():
        build_tools.append("make")
    
    return build_tools


def get_git_sha(repo_path: str) -> Optional[str]:
    """
    Get the current git commit SHA if the repository is a git repo.
    
    Args:
        repo_path: Root path of the repository
        
    Returns:
        Git commit SHA or None
    """
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=5
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    
    return None


def extract_framework_versions(pkg_data: Dict[str, Any], frameworks: List[str], repo_path: Optional[Path] = None) -> Dict[str, Dict[str, str]]:
    """
    Extract framework versions from package.json dependencies.
    Optionally uses package-lock.json for exact versions.
    
    Args:
        pkg_data: Parsed package.json data
        frameworks: List of detected framework names
        repo_path: Optional repository path for package-lock.json lookup
        
    Returns:
        Dictionary mapping framework names to version info: {framework: {package, version, versionSpec, exactVersion}}
    """
    framework_versions = {}
    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
    
    # Try to load package-lock.json for exact versions
    lock_versions = {}
    if repo_path:
        lock_file = repo_path / "package-lock.json"
        if lock_file.exists():
            try:
                with open(lock_file, 'r', encoding='utf-8') as f:
                    lock_data = json.load(f)
                    # Extract versions from packages field (npm v7+)
                    packages = lock_data.get("packages", {})
                    for pkg_path, pkg_info in packages.items():
                        if "version" in pkg_info:
                            # Normalize package path (remove node_modules prefix)
                            pkg_name = pkg_path.replace("node_modules/", "").split("/")[0]
                            if pkg_name.startswith("@") and "/" in pkg_path:
                                # Scoped package
                                parts = pkg_path.replace("node_modules/", "").split("/")
                                if len(parts) >= 2:
                                    pkg_name = f"{parts[0]}/{parts[1]}"
                            lock_versions[pkg_name] = pkg_info["version"]
                    
                    # Fallback to dependencies field (npm v6)
                    if not lock_versions:
                        deps_lock = lock_data.get("dependencies", {})
                        for pkg_name, pkg_info in deps_lock.items():
                            if isinstance(pkg_info, dict) and "version" in pkg_info:
                                lock_versions[pkg_name] = pkg_info["version"]
            except Exception:
                pass
    
    for framework in frameworks:
        package_name = FRAMEWORK_PACKAGE_MAP.get(framework)
        if package_name and package_name in deps:
            version_spec = deps[package_name]
            # Extract version number from version spec (e.g., "^17.2.1" -> "17.2.1")
            version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', version_spec)
            version = version_match.group(1) if version_match else version_spec
            
            # Get exact version from package-lock.json if available
            exact_version = lock_versions.get(package_name)
            
            framework_versions[framework] = {
                "package": package_name,
                "version": version,
                "versionSpec": version_spec
            }
            
            if exact_version:
                framework_versions[framework]["exactVersion"] = exact_version
    
    return framework_versions


def extract_node_version(repo_path: Path) -> Optional[str]:
    """Extract Node.js version from .nvmrc or package.json engines."""
    # Check .nvmrc
    nvmrc = repo_path / ".nvmrc"
    if nvmrc.exists():
        try:
            with open(nvmrc, 'r', encoding='utf-8') as f:
                version = f.read().strip()
                if version:
                    return version
        except Exception:
            pass
    
    # Check package.json engines
    package_json = repo_path / "package.json"
    if package_json.exists():
        try:
            with open(package_json, 'r', encoding='utf-8') as f:
                pkg_data = json.load(f)
                engines = pkg_data.get("engines", {})
                node_version = engines.get("node")
                if node_version:
                    return node_version
        except Exception:
            pass
    
    return None


def extract_typescript_version(pkg_data: Dict[str, Any]) -> Optional[str]:
    """Extract TypeScript version from package.json."""
    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
    ts_version = deps.get("typescript")
    if ts_version:
        version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', ts_version)
        return version_match.group(1) if version_match else ts_version
    return None


def extract_build_tool_versions(pkg_data: Dict[str, Any]) -> Dict[str, str]:
    """Extract build tool versions from package.json."""
    build_tool_versions = {}
    deps = {**pkg_data.get("dependencies", {}), **pkg_data.get("devDependencies", {})}
    
    # Angular CLI
    if "@angular/cli" in deps:
        version_spec = deps["@angular/cli"]
        version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', version_spec)
        build_tool_versions["angularCli"] = version_match.group(1) if version_match else version_spec
    
    # React Scripts
    if "react-scripts" in deps:
        version_spec = deps["react-scripts"]
        version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', version_spec)
        build_tool_versions["reactScripts"] = version_match.group(1) if version_match else version_spec
    
    # Vite
    if "vite" in deps:
        version_spec = deps["vite"]
        version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', version_spec)
        build_tool_versions["vite"] = version_match.group(1) if version_match else version_spec
    
    # Webpack
    if "webpack" in deps:
        version_spec = deps["webpack"]
        version_match = re.search(r'(\d+\.\d+\.\d+(?:-[a-zA-Z0-9]+)?)', version_spec)
        build_tool_versions["webpack"] = version_match.group(1) if version_match else version_spec
    
    return build_tool_versions


def parse_angular_json(repo_path: Path) -> Optional[Dict[str, Any]]:
    """Parse angular.json to extract Angular CLI version and project structure."""
    angular_json = repo_path / "angular.json"
    if not angular_json.exists():
        return None
    
    try:
        with open(angular_json, 'r', encoding='utf-8') as f:
            data = json.load(f)
            config = {
                "version": data.get("version"),
                "projects": list(data.get("projects", {}).keys()) if isinstance(data.get("projects"), dict) else []
            }
            
            # Extract build configurations
            default_project = data.get("defaultProject")
            if default_project and default_project in data.get("projects", {}):
                project_config = data["projects"][default_project]
                config["defaultProject"] = default_project
                config["architect"] = list(project_config.get("architect", {}).keys()) if isinstance(project_config.get("architect"), dict) else []
            
            return config
    except Exception:
        return None


def parse_tsconfig_json(repo_path: Path) -> Optional[Dict[str, Any]]:
    """Parse tsconfig.json to extract TypeScript compiler options."""
    tsconfig = repo_path / "tsconfig.json"
    if not tsconfig.exists():
        return None
    
    try:
        with open(tsconfig, 'r', encoding='utf-8') as f:
            data = json.load(f)
            compiler_options = data.get("compilerOptions", {})
            return {
                "target": compiler_options.get("target"),
                "module": compiler_options.get("module"),
                "lib": compiler_options.get("lib"),
                "strict": compiler_options.get("strict"),
                "esModuleInterop": compiler_options.get("esModuleInterop"),
                "skipLibCheck": compiler_options.get("skipLibCheck"),
                "forceConsistentCasingInFileNames": compiler_options.get("forceConsistentCasingInFileNames"),
            }
    except Exception:
        return None


def parse_requirements_txt(repo_path: Path) -> Optional[List[Dict[str, str]]]:
    """Parse requirements.txt to extract Python package versions."""
    requirements = repo_path / "requirements.txt"
    if not requirements.exists():
        return None
    
    try:
        packages = []
        with open(requirements, 'r', encoding='utf-8') as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith('#'):
                    continue
                
                # Parse package line (e.g., "fastapi==0.104.1" or "flask>=2.0.0")
                match = re.match(r'([a-zA-Z0-9_-]+(?:\[[^\]]+\])?)([<>=!]+)?([\d.]+)?', line)
                if match:
                    package_name = match.group(1).split('[')[0]  # Remove extras
                    constraint = match.group(2) or "=="
                    version = match.group(3) or ""
                    packages.append({
                        "package": package_name,
                        "version": version,
                        "constraint": constraint
                    })
        return packages if packages else None
    except Exception:
        return None


def parse_pom_xml(repo_path: Path) -> Optional[Dict[str, Any]]:
    """Parse pom.xml to extract Java version and Maven properties."""
    pom_xml = repo_path / "pom.xml"
    if not pom_xml.exists():
        return None
    
    try:
        tree = ET.parse(pom_xml)
        root = tree.getroot()
        
        # Handle namespaces
        ns = {'maven': 'http://maven.apache.org/POM/4.0.0'}
        if root.tag.startswith('{'):
            ns['maven'] = root.tag[1:root.tag.index('}')]
            root.tag = root.tag[root.tag.index('}')+1:]
        
        config = {}
        
        # Extract Java version from properties
        properties = root.find('.//maven:properties', ns)
        if properties is not None:
            java_version = properties.find('maven:maven.compiler.source', ns)
            if java_version is not None:
                config["javaVersion"] = java_version.text
            else:
                # Try alternative property names
                for prop in properties:
                    if 'java.version' in prop.tag or 'maven.compiler.source' in prop.tag:
                        config["javaVersion"] = prop.text
                        break
        
        # Extract project version
        version_elem = root.find('maven:version', ns)
        if version_elem is not None:
            config["projectVersion"] = version_elem.text
        
        return config if config else None
    except Exception:
        # Fallback to regex parsing if XML parsing fails
        try:
            with open(pom_xml, 'r', encoding='utf-8') as f:
                content = f.read()
                config = {}
                
                # Extract Java version
                java_match = re.search(r'<maven\.compiler\.source>([^<]+)</maven\.compiler\.source>', content)
                if java_match:
                    config["javaVersion"] = java_match.group(1)
                
                # Extract project version
                version_match = re.search(r'<version>([^<]+)</version>', content)
                if version_match:
                    config["projectVersion"] = version_match.group(1)
                
                return config if config else None
        except Exception:
            return None


def extract_python_version(repo_path: Path) -> Optional[str]:
    """Extract Python version from .python-version, runtime.txt, or setup.py."""
    # Check .python-version
    python_version_file = repo_path / ".python-version"
    if python_version_file.exists():
        try:
            with open(python_version_file, 'r', encoding='utf-8') as f:
                version = f.read().strip()
                if version:
                    return version
        except Exception:
            pass
    
    # Check runtime.txt (used by Heroku, etc.)
    runtime_txt = repo_path / "runtime.txt"
    if runtime_txt.exists():
        try:
            with open(runtime_txt, 'r', encoding='utf-8') as f:
                content = f.read().strip()
                if content.startswith('python-'):
                    return content.replace('python-', '')
        except Exception:
            pass
    
    # Check setup.py (basic extraction)
    setup_py = repo_path / "setup.py"
    if setup_py.exists():
        try:
            with open(setup_py, 'r', encoding='utf-8') as f:
                content = f.read()
                # Look for python_requires
                match = re.search(r'python_requires\s*=\s*["\']([^"\']+)["\']', content)
                if match:
                    return match.group(1)
        except Exception:
            pass
    
    return None


def extract_project_ui_patterns(modules: List[Dict[str, Any]], repo_path: str) -> Dict[str, Any]:
    """
    Extract project-level UI patterns by aggregating from all modules.
    
    Args:
        modules: List of module dictionaries with uiElements
        repo_path: Root path of the repository
        
    Returns:
        Dictionary with aggregated UI patterns
    """
    from collections import Counter
    from pathlib import Path
    
    ui_patterns: Dict[str, Any] = {
        "buttonComponent": None,
        "navigationPattern": None,
        "routingConfig": None,
        "commonImports": []
    }
    
    navigation_patterns: Dict[str, Any] = {
        "backButtonPatterns": []
    }
    
    button_imports = Counter()
    navigation_patterns_list = []
    all_imports = Counter()
    back_button_patterns = Counter()
    
    # Aggregate patterns from modules
    for module in modules:
        ui_elements = module.get("uiElements", {})
        
        # Collect button imports
        buttons = ui_elements.get("buttons", [])
        for button in buttons:
            button_import = button.get("import")
            if button_import:
                button_imports[button_import] += 1
        
        # Collect navigation patterns
        navigation = ui_elements.get("navigation", {})
        if navigation:
            nav_pattern = navigation.get("pattern")
            if nav_pattern:
                navigation_patterns_list.append(nav_pattern)
        
        # Collect imports from code patterns
        code_patterns = module.get("codePatterns", {})
        if code_patterns:
            # This would need to be extracted from actual imports in the module
            pass
    
    # Find most common button component
    if button_imports:
        ui_patterns["buttonComponent"] = button_imports.most_common(1)[0][0]
    
    # Find most common navigation pattern
    if navigation_patterns_list:
        nav_counter = Counter(navigation_patterns_list)
        ui_patterns["navigationPattern"] = nav_counter.most_common(1)[0][0]
    
    # Find routing config file
    repo_path_obj = Path(repo_path)
    routing_files = [
        "app-routing.module.ts",
        "routing.module.ts",
        "router.ts",
        "routes.ts",
        "AppRouter.tsx",
        "router.js"
    ]
    
    for routing_file in routing_files:
        # Search in common locations
        search_paths = [
            repo_path_obj / routing_file,
            repo_path_obj / "src" / routing_file,
            repo_path_obj / "src" / "app" / routing_file,
        ]
        for search_path in search_paths:
            if search_path.exists():
                rel_path = os.path.relpath(search_path, repo_path)
                ui_patterns["routingConfig"] = rel_path.replace(os.sep, '/')
                break
        if ui_patterns["routingConfig"]:
            break
    
    # Extract top 10 most common imports from modules
    # This would need actual import analysis - simplified here
    # In practice, this would analyze all imports from all modules
    
    # Find back button patterns
    # Search for common back button patterns in source files
    back_patterns = [
        r'router\.(back|go\(-1\))',
        r'history\.(back|go\(-1\))',
        r'navigate\(["\']\.\./',
        r'routerLink\s*=\s*["\']\.\./'
    ]
    
    source_dirs = ["src", "app", "components"]
    for source_dir in source_dirs:
        src_path = repo_path_obj / source_dir
        if not src_path.exists():
            continue
        
        for file_path in src_path.rglob("*.{ts,tsx,js,jsx,html}"):
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    content = f.read()
                    for pattern in back_patterns:
                        matches = re.findall(pattern, content, re.IGNORECASE)
                        if matches:
                            back_button_patterns[pattern] += len(matches)
            except Exception:
                continue
    
    # Convert to list with frequency
    for pattern, frequency in back_button_patterns.most_common(10):
        navigation_patterns["backButtonPatterns"].append({
            "pattern": pattern,
            "frequency": frequency
        })
    
    return {
        "uiPatterns": ui_patterns,
        "navigationPatterns": navigation_patterns
    }


def extract_code_style(repo_path: str, sample_size: int = 20) -> Dict[str, Any]:
    """
    Extract code style conventions from actual files.
    
    Analyzes naming conventions, quote style, indentation, semicolons, and import style.
    
    Args:
        repo_path: Root path of the repository
        sample_size: Number of files to sample for analysis
        
    Returns:
        Dictionary with code style information
    """
    from pathlib import Path
    from collections import Counter
    
    repo_path_obj = Path(repo_path)
    code_style: Dict[str, Any] = {
        "namingConvention": "camelCase",
        "importStyle": "mixed",
        "quoteStyle": "single",
        "indentation": 2,
        "semicolons": True
    }
    
    # Collect sample files
    sample_files = []
    source_dirs = ["src", "app", "lib", "components"]
    
    for source_dir in source_dirs:
        src_path = repo_path_obj / source_dir
        if src_path.exists():
            for ext in ["*.ts", "*.tsx", "*.js", "*.jsx", "*.py"]:
                for file_path in src_path.rglob(ext):
                    if len(sample_files) >= sample_size:
                        break
                    sample_files.append(file_path)
                if len(sample_files) >= sample_size:
                    break
        if len(sample_files) >= sample_size:
            break
    
    naming_patterns = Counter()
    quote_styles = Counter()
    indentations = Counter()
    semicolon_usage = Counter()
    import_styles = Counter()
    
    for file_path in sample_files:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                content = f.read()
                lines = content.split('\n')
                
                # Analyze naming conventions from variable/function names
                # Look for camelCase, PascalCase, snake_case
                camel_case_pattern = r'\b[a-z][a-zA-Z0-9]*\b'
                pascal_case_pattern = r'\b[A-Z][a-zA-Z0-9]*\b'
                snake_case_pattern = r'\b[a-z_][a-z0-9_]*\b'
                
                camel_matches = len(re.findall(camel_case_pattern, content))
                pascal_matches = len(re.findall(pascal_case_pattern, content))
                snake_matches = len(re.findall(snake_case_pattern, content))
                
                if camel_matches > pascal_matches and camel_matches > snake_matches:
                    naming_patterns["camelCase"] += 1
                elif pascal_matches > snake_matches:
                    naming_patterns["PascalCase"] += 1
                elif snake_matches > 0:
                    naming_patterns["snake_case"] += 1
                
                # Analyze quote style
                single_quotes = content.count("'")
                double_quotes = content.count('"')
                if single_quotes > double_quotes:
                    quote_styles["single"] += 1
                else:
                    quote_styles["double"] += 1
                
                # Analyze indentation
                for line in lines[:50]:  # Sample first 50 lines
                    if line.strip():
                        leading_spaces = len(line) - len(line.lstrip())
                        if leading_spaces > 0:
                            # Determine if tabs or spaces
                            if line[0] == '\t':
                                indentations["tab"] += 1
                            else:
                                indentations[leading_spaces] += 1
                
                # Analyze semicolons
                if ';' in content:
                    semicolon_usage[True] += 1
                else:
                    semicolon_usage[False] += 1
                
                # Analyze import style
                relative_imports = len(re.findall(r"from\s+['\"](\.\.?/)", content))
                absolute_imports = len(re.findall(r"from\s+['\"][^./]", content))
                
                if relative_imports > 0 and absolute_imports > 0:
                    import_styles["mixed"] += 1
                elif absolute_imports > 0:
                    import_styles["absolute"] += 1
                elif relative_imports > 0:
                    import_styles["relative"] += 1
                    
        except Exception:
            continue
    
    # Set most common values
    if naming_patterns:
        code_style["namingConvention"] = naming_patterns.most_common(1)[0][0]
    
    if quote_styles:
        code_style["quoteStyle"] = quote_styles.most_common(1)[0][0]
    
    if indentations:
        most_common_indent = indentations.most_common(1)[0]
        if most_common_indent[0] == "tab":
            code_style["indentation"] = 1  # Represent tabs as 1
        else:
            code_style["indentation"] = most_common_indent[0]
    
    if semicolon_usage:
        code_style["semicolons"] = semicolon_usage.most_common(1)[0][0]
    
    if import_styles:
        code_style["importStyle"] = import_styles.most_common(1)[0][0]
    
    return code_style


def extract_project_metadata(repo_path: str) -> Dict[str, Any]:
    """
    Extract comprehensive project metadata.
    
    Args:
        repo_path: Root path of the repository
        
    Returns:
        Dictionary with project metadata
    """
    repo_path_obj = Path(repo_path)
    repo_name = repo_path_obj.name
    
    # Detect languages
    languages = detect_languages(repo_path)
    
    # Detect frameworks
    frameworks = detect_frameworks(repo_path)
    
    # Detect build tools
    build_tools = detect_build_tools(repo_path)
    
    # Get git SHA
    git_sha = get_git_sha(repo_path)
    
    # Extract package manager metadata
    metadata = {}
    
    # Node.js metadata
    package_json = repo_path_obj / "package.json"
    if package_json.exists():
        try:
            with open(package_json, 'r', encoding='utf-8') as f:
                pkg_data = json.load(f)
                metadata["packageManager"] = "npm"
                if "name" in pkg_data:
                    metadata["packageName"] = pkg_data["name"]
                if "version" in pkg_data:
                    metadata["packageVersion"] = pkg_data["version"]
                
                # Extract framework versions
                framework_versions = extract_framework_versions(pkg_data, frameworks, repo_path_obj)
                if framework_versions:
                    metadata["frameworkVersions"] = framework_versions
                
                # Extract TypeScript version
                ts_version = extract_typescript_version(pkg_data)
                if ts_version:
                    metadata["typescriptVersion"] = ts_version
                
                # Extract build tool versions
                build_tool_versions = extract_build_tool_versions(pkg_data)
                if build_tool_versions:
                    metadata["buildToolVersions"] = build_tool_versions
        except Exception:
            pass
    
    # Extract Node.js version
    node_version = extract_node_version(repo_path_obj)
    if node_version:
        metadata["nodeVersion"] = node_version
    
    # Extract Python version
    python_version = extract_python_version(repo_path_obj)
    if python_version:
        metadata["pythonVersion"] = python_version
    
    # Parse configuration files
    configs = {}
    
    # Angular configuration
    angular_config = parse_angular_json(repo_path_obj)
    if angular_config:
        configs["angular"] = angular_config
    
    # TypeScript configuration
    tsconfig = parse_tsconfig_json(repo_path_obj)
    if tsconfig:
        configs["typescript"] = tsconfig
    
    # Python requirements
    requirements = parse_requirements_txt(repo_path_obj)
    if requirements:
        configs["pythonPackages"] = requirements
    
    # Maven configuration
    pom_config = parse_pom_xml(repo_path_obj)
    if pom_config:
        configs["maven"] = pom_config
        # Also add Java version to metadata if found
        if "javaVersion" in pom_config:
            metadata["javaVersion"] = pom_config["javaVersion"]
    
    if configs:
        metadata["configurations"] = configs
    
    # Java metadata
    pom_xml = repo_path_obj / "pom.xml"
    if pom_xml.exists():
        try:
            with open(pom_xml, 'r', encoding='utf-8') as f:
                content = f.read()
                # Simple extraction of groupId and artifactId
                group_match = re.search(r'<groupId>([^<]+)</groupId>', content)
                artifact_match = re.search(r'<artifactId>([^<]+)</artifactId>', content)
                if group_match and artifact_match:
                    metadata["mavenGroupId"] = group_match.group(1)
                    metadata["mavenArtifactId"] = artifact_match.group(1)
        except Exception:
            pass
    
    # .NET metadata
    csproj_files = list(repo_path_obj.rglob("*.csproj"))
    if csproj_files:
        try:
            with open(csproj_files[0], 'r', encoding='utf-8') as f:
                content = f.read()
                # Extract project name
                name_match = re.search(r'<PropertyGroup>.*?<AssemblyName>([^<]+)</AssemblyName>', content, re.DOTALL)
                if name_match:
                    metadata["dotnetAssemblyName"] = name_match.group(1)
        except Exception:
            pass
    
    return {
        "id": repo_name,
        "name": repo_name,
        "rootPath": repo_path,
        "languages": languages,
        "frameworks": frameworks,
        "buildTools": build_tools,
        "gitSha": git_sha,
        "metadata": metadata
    }


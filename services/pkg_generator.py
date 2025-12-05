"""Generate Project Knowledge Graph (PKG) JSON following project-schema.json."""

import os
import hashlib
import json
from datetime import datetime
from typing import Dict, Any, List, Optional
from pathlib import Path

from code_parser.project_metadata import extract_project_metadata
from code_parser.framework_detector import detect_frameworks
from code_parser.multi_parser import detect_language, parse_file
from code_parser.multi_normalizer import extract_definitions
from code_parser.endpoint_extractors import extract_endpoints
from code_parser.relationship_extractor import extract_relationships, calculate_fan_in_fan_out
from utils.file_utils import collect_files
import db.neo4j_db as neo4j_database  # Import to ensure connection is established

class PKGGenerator:
    """Generate Project Knowledge Graph JSON."""
    
    def __init__(self, repo_path: str, fan_threshold: int = 3, include_features: bool = True):
        """
        Initialize PKG generator.
        
        Args:
            repo_path: Root path of the repository
            fan_threshold: Fan-in threshold for filtering detailed symbol info
            include_features: Whether to include feature groupings
        """
        self.repo_path = os.path.abspath(repo_path)
        self.fan_threshold = fan_threshold
        self.include_features = include_features
        self.modules = []
        self.symbols = []
        self.endpoints = []
        self.edges = []
        self.features = []
        self.frameworks = []
        
    def _generate_module_id(self, file_path: str) -> str:
        """Generate stable module ID from file path."""
        rel_path = os.path.relpath(file_path, self.repo_path)
        # Normalize path separators
        rel_path = rel_path.replace(os.sep, '/')
        return f"mod:{rel_path}"
    
    def _generate_symbol_id(self, module_id: str, symbol_name: str) -> str:
        """Generate stable symbol ID."""
        return f"sym:{module_id}:{symbol_name}"
    
    def _generate_feature_id(self, folder_path: str) -> str:
        """Generate stable feature ID from folder path."""
        rel_path = os.path.relpath(folder_path, self.repo_path)
        rel_path = rel_path.replace(os.sep, '/')
        return f"feat:{rel_path}"
    
    def _calculate_file_hash(self, file_path: str) -> str:
        """Calculate SHA256 hash of file content."""
        try:
            with open(file_path, 'rb') as f:
                content = f.read()
                return hashlib.sha256(content).hexdigest()
        except Exception:
            return ""
    
    def _count_lines_of_code(self, file_path: str) -> int:
        """Count lines of code in a file."""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                return len([line for line in f if line.strip()])
        except Exception:
            return 0
    
    def _detect_module_kind(self, file_path: str, definitions: Dict[str, Any], frameworks: List[str]) -> List[str]:
        """Detect module kind/tags (controller, service, entity, etc.)."""
        kinds = []
        file_name = os.path.basename(file_path).lower()
        path_lower = file_path.lower()
        
        # Framework-specific detection
        if "nestjs" in frameworks:
            if "controller" in file_name or "@controller" in str(definitions).lower():
                kinds.append("controller")
            if "service" in file_name or "@injectable" in str(definitions).lower():
                kinds.append("service")
            if "module" in file_name:
                kinds.append("module")
        
        if "spring-boot" in frameworks:
            if "controller" in file_name or "@restcontroller" in str(definitions).lower():
                kinds.append("controller")
            if "service" in file_name or "@service" in str(definitions).lower():
                kinds.append("service")
            if "repository" in file_name or "@repository" in str(definitions).lower():
                kinds.append("repository")
        
        if any(f.startswith("aspnet") for f in frameworks):
            if "controller" in file_name or "[controller]" in str(definitions).lower():
                kinds.append("controller")
        
        # Generic patterns
        if "test" in file_name or "spec" in file_name:
            kinds.append("test")
        
        if "util" in file_name or "helper" in file_name:
            kinds.append("util")
        
        if "entity" in file_name or "model" in file_name:
            kinds.append("entity")
        
        if "component" in file_name:
            kinds.append("component")
        
        return kinds if kinds else []
    
    def _build_modules(self) -> List[Dict[str, Any]]:
        """Build modules array from parsed files."""
        modules = []
        files = collect_files(self.repo_path)
        self.frameworks = detect_frameworks(self.repo_path)
        
        for file_path in files:
            language = detect_language(file_path)
            if not language:
                continue
            
            module_id = self._generate_module_id(file_path)
            rel_path = os.path.relpath(file_path, self.repo_path).replace(os.sep, '/')
            
            # Parse file
            definitions = extract_definitions(file_path)
            if not definitions:
                continue
            
            # Calculate hash and LOC
            file_hash = self._calculate_file_hash(file_path)
            loc = self._count_lines_of_code(file_path)
            
            # Detect module kind
            kinds = self._detect_module_kind(file_path, definitions, self.frameworks)
            
            # Extract imports (store raw for now, will be resolved later)
            raw_imports = []
            if "imports" in definitions:
                raw_imports = definitions["imports"]
            
            # Build module object
            module = {
                "id": module_id,
                "path": rel_path,
                "kind": kinds,
                "loc": loc,
                "hash": file_hash,
                "exports": [],  # Will be populated with symbol IDs
                "imports": [],  # Will be resolved to module IDs in relationship extraction
                "definitions": definitions,  # Store for later processing
                "file_path": file_path,  # Store for endpoint extraction
                "raw_imports": raw_imports  # Store raw imports for resolution
            }
            
            modules.append(module)
        
        return modules
    
    def _build_symbols(self, modules: List[Dict[str, Any]], fan_stats: Dict[str, tuple]) -> List[Dict[str, Any]]:
        """Build symbols array from module definitions."""
        symbols = []
        
        for module in modules:
            module_id = module["id"]
            definitions = module.get("definitions", {})
            file_path = module.get("file_path", "")
            
            # Check fan-in threshold
            fan_in, _ = fan_stats.get(module_id, (0, 0))
            include_details = fan_in >= self.fan_threshold
            
            # Extract functions
            functions = definitions.get("functions", [])
            for func in functions:
                func_name = func.get("name")
                if not func_name:
                    continue
                
                symbol_id = self._generate_symbol_id(module_id, func_name)
                
                # Build signature
                params = func.get("parameters", "")
                signature = f"{func_name}({params})"
                
                symbol = {
                    "id": symbol_id,
                    "moduleId": module_id,
                    "name": func_name,
                    "kind": "function",
                    "isExported": True,  # Simplified - can be enhanced
                    "signature": signature,
                    "visibility": "public",
                }
                
                if include_details:
                    symbol["summary"] = func.get("docstring", "")
                
                symbols.append(symbol)
                # Add to module exports
                module["exports"].append(symbol_id)
            
            # Extract classes
            classes = definitions.get("classes", [])
            for cls in classes:
                cls_name = cls.get("name")
                if not cls_name:
                    continue
                
                symbol_id = self._generate_symbol_id(module_id, cls_name)
                
                symbol = {
                    "id": symbol_id,
                    "moduleId": module_id,
                    "name": cls_name,
                    "kind": "class",
                    "isExported": True,
                    "signature": cls_name,
                    "visibility": "public",
                }
                
                if include_details:
                    symbol["summary"] = cls.get("docstring", "")
                
                symbols.append(symbol)
                module["exports"].append(symbol_id)
                
                # Extract methods
                methods = cls.get("methods", [])
                for method in methods:
                    # Handle both string and dict formats
                    if isinstance(method, dict):
                        method_name = method.get("name")
                    else:
                        method_name = method
                    
                    if isinstance(method_name, str):
                        method_symbol_id = self._generate_symbol_id(module_id, f"{cls_name}.{method_name}")
                        
                        method_symbol = {
                            "id": method_symbol_id,
                            "moduleId": module_id,
                            "name": f"{cls_name}.{method_name}",
                            "kind": "method",
                            "isExported": False,
                            "signature": f"{method_name}()",
                            "visibility": "public",
                        }
                        
                        symbols.append(method_symbol)
            
            # Extract interfaces (Java, C#, TypeScript)
            interfaces = definitions.get("interfaces", [])
            for interface in interfaces:
                interface_name = interface.get("name")
                if not interface_name:
                    continue
                
                symbol_id = self._generate_symbol_id(module_id, interface_name)
                
                symbol = {
                    "id": symbol_id,
                    "moduleId": module_id,
                    "name": interface_name,
                    "kind": "interface",
                    "isExported": True,
                    "signature": interface_name,
                    "visibility": "public",
                }
                
                symbols.append(symbol)
                module["exports"].append(symbol_id)
        
        return symbols
    
    def _build_endpoints(self, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build endpoints array from modules."""
        endpoints = []
        
        for module in modules:
            module_id = module["id"]
            file_path = module.get("file_path")
            
            if not file_path:
                continue
            
            try:
                with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                    source = f.read()
                
                module_endpoints = extract_endpoints(file_path, source, module_id, self.frameworks)
                endpoints.extend(module_endpoints)
            except Exception:
                continue
        
        return endpoints
    
    def _build_features(self, modules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Build features array from folder hierarchy."""
        if not self.include_features:
            return []
        
        features = []
        feature_map = {}
        
        for module in modules:
            path = module.get("path", "")
            path_parts = path.split('/')[:-1]  # Exclude filename
            
            # Build feature hierarchy
            current_path = ""
            for part in path_parts:
                if not part:
                    continue
                
                current_path = os.path.join(current_path, part) if current_path else part
                feature_id = self._generate_feature_id(
                    os.path.join(self.repo_path, current_path)
                )
                
                if feature_id not in feature_map:
                    feature = {
                        "id": feature_id,
                        "name": part,
                        "path": current_path.replace(os.sep, '/'),
                        "moduleIds": []
                    }
                    feature_map[feature_id] = feature
                    features.append(feature)
                
                feature_map[feature_id]["moduleIds"].append(module["id"])
        
        return features
    
    def generate_pkg(self, output_path: Optional[str] = None) -> Dict[str, Any]:
        """
        Generate complete PKG JSON.
        
        Args:
            output_path: Optional path to save JSON file
            
        Returns:
            Complete PKG dictionary
        """
        import logging
        logger = logging.getLogger(__name__)
        
        logger.info(f"🏗️  STARTING PKG GENERATION | Repo: {self.repo_path}")
        
        # Extract project metadata
        logger.info(f"📋 EXTRACTING PROJECT METADATA | Repo: {self.repo_path}")
        project_meta = extract_project_metadata(self.repo_path)
        project_id = project_meta.get("id", "unknown")
        logger.info(f"✅ PROJECT METADATA EXTRACTED | Project ID: {project_id} | Name: {project_meta.get('name', 'N/A')} | Languages: {project_meta.get('languages', [])}")
        
        # Build modules
        logger.info(f"📦 BUILDING MODULES | Repo: {self.repo_path}")
        self.modules = self._build_modules()
        logger.info(f"✅ MODULES BUILT | Count: {len(self.modules)}")
        
        # Build symbols (need fan stats, so do a first pass)
        # For now, build symbols without fan filtering, then recalculate
        logger.info(f"🔤 BUILDING SYMBOLS (first pass) | Repo: {self.repo_path}")
        temp_symbols = self._build_symbols(self.modules, {})
        self.symbols = temp_symbols
        logger.info(f"✅ SYMBOLS BUILT (first pass) | Count: {len(self.symbols)}")
        
        # Build endpoints
        logger.info(f"🌐 BUILDING ENDPOINTS | Repo: {self.repo_path}")
        self.endpoints = self._build_endpoints(self.modules)
        logger.info(f"✅ ENDPOINTS BUILT | Count: {len(self.endpoints)}")
        
        # Extract relationships
        logger.info(f"🔗 EXTRACTING RELATIONSHIPS | Repo: {self.repo_path}")
        self.edges, fan_stats = extract_relationships(
            self.modules, self.symbols, self.endpoints, self.repo_path
        )
        logger.info(f"✅ RELATIONSHIPS EXTRACTED | Edges: {len(self.edges)}")
        
        # Populate module imports from edges
        logger.debug(f"📥 POPULATING MODULE IMPORTS | Repo: {self.repo_path}")
        for edge in self.edges:
            if edge.get("type") == "imports":
                from_id = edge.get("from")
                to_id = edge.get("to")
                for module in self.modules:
                    if module["id"] == from_id:
                        if to_id not in module["imports"]:
                            module["imports"].append(to_id)
        
        # Rebuild symbols with fan filtering
        logger.info(f"🔤 REBUILDING SYMBOLS (with fan filtering) | Repo: {self.repo_path} | Fan threshold: {self.fan_threshold}")
        self.symbols = self._build_symbols(self.modules, fan_stats)
        logger.info(f"✅ SYMBOLS REBUILT | Count: {len(self.symbols)}")
        
        # Build features
        if self.include_features:
            logger.info(f"📁 BUILDING FEATURES | Repo: {self.repo_path}")
            self.features = self._build_features(self.modules)
            logger.info(f"✅ FEATURES BUILT | Count: {len(self.features)}")
        else:
            self.features = []
            logger.info(f"⏭️  SKIPPING FEATURES | Repo: {self.repo_path} | include_features=False")
        
        # Clean up module definitions (remove file_path, keep only needed fields)
        logger.debug(f"🧹 CLEANING UP MODULE DATA | Repo: {self.repo_path}")
        for module in self.modules:
            module.pop("definitions", None)
            module.pop("file_path", None)
            # Add moduleSummary if available
            if "moduleSummary" not in module:
                module["moduleSummary"] = None
        
        # Build final PKG
        logger.info(f"📦 BUILDING FINAL PKG STRUCTURE | Repo: {self.repo_path}")
        pkg = {
            "version": "1.0.0",
            "generatedAt": datetime.utcnow().isoformat() + "Z",
            "gitSha": project_meta.get("gitSha"),
            "project": {
                "id": project_meta.get("id", ""),
                "name": project_meta.get("name", ""),
                "rootPath": project_meta.get("rootPath", ""),
                "languages": project_meta.get("languages", []),
                "metadata": project_meta.get("metadata", {})
            },
            "modules": self.modules,
            "symbols": self.symbols,
            "endpoints": self.endpoints,
            "edges": self.edges,
        }
        
        if self.features:
            pkg["features"] = self.features
        
        # Save if output path provided
        if output_path:
            logger.info(f"💾 SAVING PKG TO FILE | Path: {output_path}")
            os.makedirs(os.path.dirname(output_path) if os.path.dirname(output_path) else '.', exist_ok=True)
            with open(output_path, 'w', encoding='utf-8') as f:
                json.dump(pkg, f, indent=2)
            logger.info(f"✅ PKG SAVED TO FILE | Path: {output_path}")
        
        logger.info(f"💾 STORING PKG TO NEO4J | Project ID: {project_id}")
        neo4j_database.store_pkg(pkg)
        logger.info(f"✅ PKG STORED TO NEO4J | Project ID: {project_id}")

        logger.info(f"✅ PKG GENERATION COMPLETE | Repo: {self.repo_path} | Project ID: {project_id} | Modules: {len(self.modules)} | Symbols: {len(self.symbols)} | Edges: {len(self.edges)} | Endpoints: {len(self.endpoints)}")
        return pkg        


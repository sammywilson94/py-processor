"""PKG Query Engine - Queries the Project Knowledge Graph."""

import logging
import os
import re
from typing import Dict, Any, List, Set, Optional

logger = logging.getLogger(__name__)


class PKGQueryEngine:
    """Query engine for Project Knowledge Graph (PKG) data."""
    
    def __init__(self, pkg_data: Dict[str, Any], neo4j_engine=None):
        """
        Initialize query engine with PKG data.
        
        Args:
            pkg_data: Complete PKG dictionary
            neo4j_engine: Optional Neo4jQueryEngine instance for complex queries
        """
        self.pkg_data = pkg_data
        self.modules = pkg_data.get('modules', [])
        self.symbols = pkg_data.get('symbols', [])
        self.endpoints = pkg_data.get('endpoints', [])
        self.edges = pkg_data.get('edges', [])
        self.neo4j_engine = neo4j_engine
        self.project_id = pkg_data.get('project', {}).get('id', '')
        
        # Build lookup indices for performance
        self._module_by_id: Dict[str, Dict[str, Any]] = {}
        self._symbol_by_id: Dict[str, Dict[str, Any]] = {}
        self._endpoint_by_id: Dict[str, Dict[str, Any]] = {}
        
        for module in self.modules:
            self._module_by_id[module['id']] = module
        
        for symbol in self.symbols:
            self._symbol_by_id[symbol['id']] = symbol
        
        for endpoint in self.endpoints:
            self._endpoint_by_id[endpoint['id']] = endpoint
    
    def get_modules_by_tag(self, tag: str) -> List[Dict[str, Any]]:
        """
        Find modules with matching tag.
        
        Args:
            tag: Tag to search for (e.g., "auth", "controller", "service")
            
        Returns:
            List of matching modules
        """
        logger.debug(f"🔍 QUERY: get_modules_by_tag | Tag: {tag} | Project: {self.project_id}")
        tag_lower = tag.lower()
        matching_modules = []
        
        for module in self.modules:
            # Check kind array (tags)
            kinds = module.get('kind', [])
            if isinstance(kinds, list):
                for kind in kinds:
                    if tag_lower in kind.lower():
                        matching_modules.append(module)
                        break
        
        logger.info(f"✅ QUERY RESULT: get_modules_by_tag | Tag: {tag} | Found: {len(matching_modules)} modules")
        return matching_modules
    
    def get_modules_by_path_pattern(self, pattern: str) -> List[Dict[str, Any]]:
        """
        Find modules matching path pattern.
        
        Args:
            pattern: Path pattern (supports wildcards like "auth/*")
            
        Returns:
            List of matching modules
        """
        # Convert pattern to regex
        regex_pattern = pattern.replace('*', '.*')
        regex = re.compile(regex_pattern, re.IGNORECASE)
        
        matching_modules = []
        for module in self.modules:
            path = module.get('path', '')
            if regex.search(path):
                matching_modules.append(module)
        
        return matching_modules
    
    def get_endpoints_by_path(self, path_pattern: str) -> List[Dict[str, Any]]:
        """
        Find endpoints matching path pattern.
        
        Args:
            path_pattern: Endpoint path pattern (e.g., "/login", "/auth/*")
            
        Returns:
            List of matching endpoints
        """
        # Convert pattern to regex
        regex_pattern = path_pattern.replace('*', '.*')
        regex = re.compile(regex_pattern, re.IGNORECASE)
        
        matching_endpoints = []
        for endpoint in self.endpoints:
            path = endpoint.get('path', '')
            if regex.search(path):
                matching_endpoints.append(endpoint)
        
        return matching_endpoints
    
    def get_impacted_modules(
        self,
        module_ids: List[str],
        depth: int = 2
    ) -> Dict[str, Any]:
        """
        Build transitive closure of dependencies for given modules.
        
        Uses Neo4j if available for better performance on complex queries.
        
        Args:
            module_ids: List of starting module IDs
            depth: Maximum depth to traverse (default: 2)
            
        Returns:
            Dictionary with impacted_modules, impacted_files, and dependency graph
        """
        logger.info(f"🔍 QUERY: get_impacted_modules | Project: {self.project_id} | Module IDs: {len(module_ids)} | Depth: {depth}")
        # Use Neo4j if available for complex transitive queries
        if self.neo4j_engine and self.project_id:
            try:
                logger.debug(f"🌐 USING NEO4J ENGINE | Project: {self.project_id}")
                result = self.neo4j_engine.get_impacted_modules(module_ids, depth)
                # Convert Neo4j node objects to dictionaries if needed
                if result.get("impacted_modules"):
                    impacted_modules = []
                    for mod in result["impacted_modules"]:
                        if hasattr(mod, 'items'):
                            impacted_modules.append(dict(mod))
                        else:
                            impacted_modules.append(mod)
                    result["impacted_modules"] = impacted_modules
                logger.info(f"✅ QUERY RESULT: get_impacted_modules | Found: {len(result.get('impacted_modules', []))} impacted modules")
                return result
            except Exception as e:
                logger.warning(f"⚠️  NEO4J QUERY FAILED | Project: {self.project_id} | Error: {e} | Falling back to in-memory")
        
        # Fallback to in-memory implementation
        impacted_module_ids: Set[str] = set(module_ids)
        visited: Set[str] = set()
        
        # Build dependency graph from edges
        # Map: module_id -> set of dependent module_ids
        dependents: Dict[str, Set[str]] = {}  # Who depends on this module
        dependencies: Dict[str, Set[str]] = {}  # What this module depends on
        
        for edge in self.edges:
            edge_from = edge.get('from')
            edge_to = edge.get('to')
            edge_type = edge.get('type', '')
            
            if not edge_from or not edge_to:
                continue
            
            # Extract module ID from symbol/module ID
            from_module = self._extract_module_id(edge_from)
            to_module = self._extract_module_id(edge_to)
            
            if from_module and to_module:
                # from_module depends on to_module
                if to_module not in dependencies:
                    dependencies[to_module] = set()
                dependencies[to_module].add(from_module)
                
                # from_module is a dependent of to_module
                if from_module not in dependents:
                    dependents[from_module] = set()
                dependents[from_module].add(to_module)
        
        # BFS traversal to find all impacted modules
        queue = [(mid, 0) for mid in module_ids]  # (module_id, depth)
        
        while queue:
            current_id, current_depth = queue.pop(0)
            
            if current_id in visited or current_depth > depth:
                continue
            
            visited.add(current_id)
            impacted_module_ids.add(current_id)
            
            # Add dependents (modules that depend on this one)
            for dependent_id in dependents.get(current_id, []):
                if dependent_id not in visited:
                    queue.append((dependent_id, current_depth + 1))
            
            # Add dependencies (modules this one depends on)
            for dep_id in dependencies.get(current_id, []):
                if dep_id not in visited:
                    queue.append((dep_id, current_depth + 1))
        
        # Get module objects
        impacted_modules = [
            self._module_by_id[mid] for mid in impacted_module_ids
            if mid in self._module_by_id
        ]
        
        # Get file paths
        impacted_files = [
            module.get('path') for module in impacted_modules
            if module.get('path')
        ]
        
        return {
            "impacted_modules": impacted_modules,
            "impacted_module_ids": list(impacted_module_ids),
            "impacted_files": impacted_files,
            "depth_reached": depth
        }
    
    def get_dependencies(self, module_id: str) -> Dict[str, Any]:
        """
        Get callers (fan-in) and callees (fan-out) for a module.
        
        Uses Neo4j if available for better performance.
        
        Args:
            module_id: Module ID to analyze
            
        Returns:
            Dictionary with callers, callees, fan_in_count, fan_out_count
        """
        # Use Neo4j if available
        if self.neo4j_engine:
            try:
                result = self.neo4j_engine.get_dependencies(module_id)
                # Convert Neo4j node objects to dictionaries if needed
                if result.get("callers"):
                    result["callers"] = [dict(c) if hasattr(c, 'items') else c for c in result["callers"]]
                if result.get("callees"):
                    result["callees"] = [dict(c) if hasattr(c, 'items') else c for c in result["callees"]]
                return result
            except Exception as e:
                logger.warning(f"Neo4j query failed, falling back to in-memory: {e}")
        
        # Fallback to in-memory implementation
        callers: Set[str] = set()  # Modules that call/import this module
        callees: Set[str] = set()   # Modules this module calls/imports
        
        for edge in self.edges:
            edge_from = edge.get('from')
            edge_to = edge.get('to')
            edge_type = edge.get('type', '')
            
            if not edge_from or not edge_to:
                continue
            
            from_module = self._extract_module_id(edge_from)
            to_module = self._extract_module_id(edge_to)
            
            if from_module == module_id and to_module:
                callees.add(to_module)
            elif to_module == module_id and from_module:
                callers.add(from_module)
        
        # Get module objects
        caller_modules = [
            self._module_by_id[mid] for mid in callers
            if mid in self._module_by_id
        ]
        
        callee_modules = [
            self._module_by_id[mid] for mid in callees
            if mid in self._module_by_id
        ]
        
        return {
            "callers": caller_modules,
            "callees": callee_modules,
            "fan_in_count": len(callers),
            "fan_out_count": len(callees)
        }
    
    def get_symbols_by_name(self, name_pattern: str) -> List[Dict[str, Any]]:
        """
        Find symbols matching name pattern.
        
        Args:
            name_pattern: Symbol name pattern (supports wildcards)
            
        Returns:
            List of matching symbols
        """
        # Convert pattern to regex
        regex_pattern = name_pattern.replace('*', '.*')
        regex = re.compile(regex_pattern, re.IGNORECASE)
        
        matching_symbols = []
        for symbol in self.symbols:
            name = symbol.get('name', '')
            if regex.search(name):
                matching_symbols.append(symbol)
        
        return matching_symbols
    
    def get_module_by_id(self, module_id: str) -> Optional[Dict[str, Any]]:
        """
        Get module by ID.
        
        Args:
            module_id: Module ID
            
        Returns:
            Module dictionary or None
        """
        return self._module_by_id.get(module_id)
    
    def get_symbol_by_id(self, symbol_id: str) -> Optional[Dict[str, Any]]:
        """
        Get symbol by ID.
        
        Args:
            symbol_id: Symbol ID
            
        Returns:
            Symbol dictionary or None
        """
        return self._symbol_by_id.get(symbol_id)
    
    def get_endpoint_by_id(self, endpoint_id: str) -> Optional[Dict[str, Any]]:
        """
        Get endpoint by ID.
        
        Args:
            endpoint_id: Endpoint ID
            
        Returns:
            Endpoint dictionary or None
        """
        return self._endpoint_by_id.get(endpoint_id)
    
    def _extract_module_id(self, id_string: str) -> Optional[str]:
        """
        Extract module ID from a symbol/module ID string.
        
        Args:
            id_string: ID string (e.g., "mod:path/to/file.py" or "sym:mod:path/to/file.py:function")
            
        Returns:
            Module ID or None
        """
        if not id_string:
            return None
        
        # If it's already a module ID (starts with "mod:")
        if id_string.startswith("mod:"):
            return id_string
        
        # If it's a symbol ID (starts with "sym:")
        if id_string.startswith("sym:"):
            # Extract module ID from symbol ID
            # Format: "sym:mod:path/to/file.py:symbol_name"
            parts = id_string.split(":", 3)
            if len(parts) >= 3:
                # Reconstruct module ID
                return f"mod:{parts[1]}"
        
        return None
    
    def get_modules_by_kind(self, kind: str) -> List[Dict[str, Any]]:
        """
        Find modules by kind (e.g., "controller", "service", "entity").
        
        Args:
            kind: Module kind to search for
            
        Returns:
            List of matching modules
        """
        kind_lower = kind.lower()
        matching_modules = []
        
        for module in self.modules:
            kinds = module.get('kind', [])
            if isinstance(kinds, list):
                for k in kinds:
                    if kind_lower == k.lower():
                        matching_modules.append(module)
                        break
        
        return matching_modules
    
    def get_endpoints_by_module(self, module_id: str) -> List[Dict[str, Any]]:
        """
        Get all endpoints for a module.
        
        Args:
            module_id: Module ID
            
        Returns:
            List of endpoints
        """
        matching_endpoints = []
        for endpoint in self.endpoints:
            handler_module_id = endpoint.get('handlerModuleId')
            if handler_module_id == module_id:
                matching_endpoints.append(endpoint)
        
        return matching_endpoints
    
    def get_modules_by_filename(self, filename: str) -> List[Dict[str, Any]]:
        """
        Find modules by exact filename or partial match.
        
        Args:
            filename: Filename to search for (e.g., "main.ts", "app.component.ts")
            
        Returns:
            List of matching modules
        """
        matches = []
        filename_lower = filename.lower()
        
        for module in self.modules:
            path = module.get('path', '')
            basename = os.path.basename(path).lower()
            # Exact match or partial match (e.g., "app.component.ts" matches "app.component.ts")
            if filename_lower == basename or filename_lower in basename:
                matches.append(module)
        
        return matches
    
    def get_entry_point_modules(self) -> List[Dict[str, Any]]:
        """
        Find common entry point files (main.ts, index.ts, app.py, main.py, etc.).
        
        Returns:
            List of entry point modules
        """
        entry_patterns = [
            'main.ts', 'main.js', 'main.tsx', 'main.jsx',
            'index.ts', 'index.js', 'index.tsx', 'index.jsx',
            'app.py', 'main.py', '__main__.py',
            'main.java', 'Application.java',
            'Program.cs', 'Main.cs',
            'main.cpp', 'main.c'
        ]
        
        entry_modules = []
        for module in self.modules:
            path = module.get('path', '').lower()
            basename = os.path.basename(path) if path else ''
            if basename in entry_patterns:
                entry_modules.append(module)
        
        return entry_modules
    
    def get_app_component_modules(self) -> List[Dict[str, Any]]:
        """
        Find app component files (app.component.ts, App.tsx, App.jsx, etc.).
        
        Returns:
            List of app component modules
        """
        component_patterns = [
            'app.component.ts', 'app.component.js',
            'app.tsx', 'app.jsx', 'app.ts', 'app.js',
            'app.component.tsx', 'app.component.jsx',
            'appcomponent.tsx', 'appcomponent.jsx',
            'main.component.ts', 'root.component.ts'
        ]
        
        component_modules = []
        for module in self.modules:
            path = module.get('path', '')
            basename = os.path.basename(path).lower() if path else ''
            if basename in component_patterns:
                component_modules.append(module)
            # Also check if path contains "app" and "component"
            elif 'app' in path.lower() and 'component' in path.lower():
                component_modules.append(module)
        
        return component_modules

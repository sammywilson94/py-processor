"""Diagram Generator - Creates dependency diagrams from PKG data."""

import logging
import os
import base64
import json
import re
from typing import Dict, Any, List, Optional, Set, Tuple
from collections import defaultdict

from services.pkg_query_engine import PKGQueryEngine
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class DiagramGenerator:
    """Generates dependency diagrams and visualizations from PKG data."""
    
    def __init__(self, pkg_data: Dict[str, Any], pkg_query_engine: Optional[PKGQueryEngine] = None):
        """
        Initialize diagram generator.
        
        Args:
            pkg_data: Complete PKG dictionary
            pkg_query_engine: Optional PKGQueryEngine instance (will create if not provided)
        """
        self.pkg_data = pkg_data
        self.project_id = pkg_data.get('project', {}).get('id', '')
        
        # Initialize Neo4j engine if available
        self.neo4j_engine = self._init_neo4j_engine()
        
        # Initialize PKGQueryEngine with Neo4j engine if available
        if pkg_query_engine:
            self.query_engine = pkg_query_engine
            # Update neo4j_engine if it was just initialized
            if self.neo4j_engine and not hasattr(self.query_engine, 'neo4j_engine'):
                self.query_engine.neo4j_engine = self.neo4j_engine
        else:
            self.query_engine = PKGQueryEngine(pkg_data, neo4j_engine=self.neo4j_engine)
        
        # Initialize LLM for architecture diagram generation
        self.llm = None
        self._init_llm()
    
    def generate_diagram(self, intent: Dict[str, Any], user_message: str) -> Dict[str, Any]:
        """
        Generate a diagram based on the request.
        
        Args:
            intent: Extracted intent dictionary
            user_message: User's message
            
        Returns:
            Dictionary with diagram content, format, and metadata
        """
        message_lower = user_message.lower()
        
        # Early query parsing for natural language module discovery
        query_obj = None
        target_modules = []
        try:
            query_obj = self._parse_query_for_module(user_message)
            target_modules = self._find_modules_from_query(query_obj)
        except Exception as e:
            logger.debug(f"Query parsing failed, using fallback: {e}")
        
        # Determine diagram type and scope
        # Architecture diagrams are triggered by explicit architecture/project requests
        # or when intent_category is diagram_request AND user mentions architecture/project
        is_diagram_request = intent.get('intent_category') == 'diagram_request'
        has_architecture_keywords = 'architecture' in message_lower or 'project' in message_lower or 'structure' in message_lower
        
        if has_architecture_keywords or (is_diagram_request and ('architecture' in message_lower or 'project' in message_lower)):
            diagram_type = "architecture"
            module_ids = None  # All modules
        elif target_modules:
            # Found modules from natural language query - use focused dependency diagram
            diagram_type = "focused_dependency"
            module_ids = None  # Will use target_modules instead
        elif 'module' in message_lower:
            # Try to extract specific module (fallback to old method)
            module_id = self._extract_module_from_query(user_message)
            if module_id:
                diagram_type = "module"
                module_ids = [module_id]
            else:
                diagram_type = "dependency"
                module_ids = None
        else:
            diagram_type = "dependency"
            module_ids = None
        
        # Determine format preference
        if 'mermaid' in message_lower:
            format_type = "mermaid"
        elif 'dot' in message_lower or 'graphviz' in message_lower:
            format_type = "dot"
        else:
            format_type = "mermaid"  # Default to mermaid for architecture diagrams
        
        # Determine depth
        depth = 2
        if 'depth' in message_lower or 'level' in message_lower:
            depth_match = re.search(r'(?:depth|level)\s*[:\s]*(\d+)', message_lower)
            if depth_match:
                depth = int(depth_match.group(1))
        
        # Handle architecture diagram generation
        if diagram_type == "architecture":
            try:
                # Check if LLM is available
                if not self.llm:
                    logger.warning("LLM not available for architecture diagram, falling back to standard diagram")
                    diagram_type = "dependency"
                else:
                    mermaid_code = self._generate_architecture_diagram(user_message)
                    # Render to high-resolution image (use resolution=2 for 3840px+ width)
                    content, rendered_info = self._render_mermaid_to_image(mermaid_code, resolution=2)
                    metadata = {
                        "generated_by": "llm"
                    }
                    if rendered_info:
                        metadata.update(rendered_info)
                    return {
                        "diagram_type": diagram_type,
                        "format": "mermaid",
                        "content": content,
                        "mermaid_code": mermaid_code,  # Also include raw code for fallback
                        "modules_included": [],
                        "metadata": metadata
                    }
            except Exception as e:
                logger.warning(f"Architecture diagram generation failed: {e}, falling back to standard diagram", exc_info=True)
                # Fallback to standard dependency diagram
                diagram_type = "dependency"
        
        # Build dependency graph for non-architecture diagrams
        if diagram_type == "focused_dependency" and target_modules:
            # Use focused dependency graph
            direction = query_obj.get("direction", "both") if query_obj else "both"
            graph_data = self._build_focused_dependency_graph(target_modules, depth, direction)
        else:
            # Use standard dependency graph
            graph_data = self._build_dependency_graph(module_ids, depth)
        
        # Generate diagram in requested format
        mermaid_code = None  # Initialize for all formats
        rendered_info = None  # Track rendering status
        if format_type == "text":
            content = self._generate_text_diagram(graph_data)
        elif format_type == "dot":
            content = self._generate_dot_format(graph_data)
        elif format_type == "mermaid":
            # Capture raw Mermaid code first
            mermaid_code = self._generate_mermaid_format(graph_data)
            # Render to high-resolution image
            content, rendered_info = self._render_mermaid_to_image(mermaid_code)
        else:
            content = self._generate_text_diagram(graph_data)
        
        # Build metadata
        metadata = {
            "depth": depth,
            "edge_count": len(graph_data.get('edges', [])),
            "module_count": len(graph_data.get('module_ids', []))
        }
        
        # Add rendering metadata if available
        if rendered_info:
            metadata.update(rendered_info)
        
        # Add focused diagram metadata if applicable
        if diagram_type == "focused_dependency":
            metadata["target_modules"] = graph_data.get('target_modules', [])
            metadata["direction"] = graph_data.get('direction', 'both')
            metadata["is_focused"] = True
            if target_modules:
                metadata["target_module_paths"] = [m.get('path', '') for m in target_modules[:5]]
        
        return {
            "diagram_type": diagram_type,
            "format": format_type,
            "content": content,
            "mermaid_code": mermaid_code,  # Raw code without markdown wrapper for frontend fallback
            "modules_included": graph_data.get('module_ids', []),
            "metadata": metadata
        }
    
    def _build_dependency_graph(self, module_ids: Optional[List[str]], depth: int) -> Dict[str, Any]:
        """
        Build dependency graph from PKG data.
        
        Args:
            module_ids: List of starting module IDs (None for all modules)
            depth: Maximum depth to traverse
            
        Returns:
            Dictionary with module_ids, edges, and module_info
        """
        if module_ids is None:
            # Include all modules
            all_modules = self.pkg_data.get('modules', [])
            module_ids = [m.get('id') for m in all_modules if m.get('id')]
        else:
            # Expand to include dependencies up to depth
            impacted = self.query_engine.get_impacted_modules(module_ids, depth)
            module_ids = impacted.get('impacted_module_ids', module_ids)
        
        # Build edge list for included modules
        edges = []
        all_edges = self.pkg_data.get('edges', [])
        module_id_set = set(module_ids)
        
        for edge in all_edges:
            edge_from = edge.get('from', '')
            edge_to = edge.get('to', '')
            edge_type = edge.get('type', '')
            
            # Extract module IDs
            from_module = self.query_engine._extract_module_id(edge_from)
            to_module = self.query_engine._extract_module_id(edge_to)
            
            # Only include edges between modules in our set
            if from_module and to_module and from_module in module_id_set and to_module in module_id_set:
                # Only include import and call relationships for dependency diagrams
                if edge_type in ['imports', 'calls']:
                    edges.append({
                        'from': from_module,
                        'to': to_module,
                        'type': edge_type
                    })
        
        # Get module info
        module_info = {}
        for mod_id in module_ids:
            module = self.query_engine.get_module_by_id(mod_id)
            if module:
                module_info[mod_id] = {
                    'path': module.get('path', mod_id),
                    'kind': module.get('kind', [])
                }
        
        return {
            'module_ids': module_ids,
            'edges': edges,
            'module_info': module_info
        }
    
    def _build_focused_dependency_graph(
        self, 
        target_modules: List[Dict[str, Any]], 
        depth: int, 
        direction: str = "both"
    ) -> Dict[str, Any]:
        """
        Build focused dependency graph starting from target modules.
        
        Args:
            target_modules: List of target module dictionaries
            depth: Maximum depth to traverse
            direction: "both" (default), "incoming" (callers), "outgoing" (callees)
            
        Returns:
            Dictionary with module_ids, edges, module_info, target_modules, direction
        """
        if not target_modules:
            return {
                'module_ids': [],
                'edges': [],
                'module_info': {},
                'target_modules': [],
                'direction': direction
            }
        
        target_module_ids = [m.get('id') for m in target_modules if m.get('id')]
        
        if not target_module_ids:
            return {
                'module_ids': [],
                'edges': [],
                'module_info': {},
                'target_modules': [],
                'direction': direction
            }
        
        # Get dependencies for each target module
        all_deps = set(target_module_ids)
        edges = []
        edge_set = set()  # Track edges to avoid duplicates
        
        for mod_id in target_module_ids:
            try:
                deps = self.query_engine.get_dependencies(mod_id)
                
                if direction in ["both", "incoming"]:
                    # Add callers (fan-in) - modules that depend on this module
                    for caller in deps.get("callers", []):
                        caller_id = caller.get('id') if isinstance(caller, dict) else caller
                        if caller_id and caller_id != mod_id:
                            all_deps.add(caller_id)
                            edge_key = (caller_id, mod_id)
                            if edge_key not in edge_set:
                                edges.append({
                                    'from': caller_id,
                                    'to': mod_id,
                                    'type': 'calls'
                                })
                                edge_set.add(edge_key)
                
                if direction in ["both", "outgoing"]:
                    # Add callees (fan-out) - modules this module depends on
                    for callee in deps.get("callees", []):
                        callee_id = callee.get('id') if isinstance(callee, dict) else callee
                        if callee_id and callee_id != mod_id:
                            all_deps.add(callee_id)
                            edge_key = (mod_id, callee_id)
                            if edge_key not in edge_set:
                                edges.append({
                                    'from': mod_id,
                                    'to': callee_id,
                                    'type': 'imports'
                                })
                                edge_set.add(edge_key)
            except Exception as e:
                logger.warning(f"Error getting dependencies for {mod_id}: {e}")
        
        # Expand to depth using get_impacted_modules if depth > 1
        if depth > 1 and all_deps:
            try:
                impacted = self.query_engine.get_impacted_modules(list(all_deps), depth - 1)
                impacted_ids = impacted.get('impacted_module_ids', [])
                all_deps.update(impacted_ids)
                
                # Add edges from impacted modules
                all_edges = self.pkg_data.get('edges', [])
                module_id_set = all_deps
                
                for edge in all_edges:
                    edge_from = edge.get('from', '')
                    edge_to = edge.get('to', '')
                    edge_type = edge.get('type', '')
                    
                    # Extract module IDs
                    from_module = self.query_engine._extract_module_id(edge_from)
                    to_module = self.query_engine._extract_module_id(edge_to)
                    
                    if from_module and to_module and from_module in module_id_set and to_module in module_id_set:
                        # Only include import and call relationships
                        if edge_type in ['imports', 'calls']:
                            edge_key = (from_module, to_module)
                            if edge_key not in edge_set:
                                edges.append({
                                    'from': from_module,
                                    'to': to_module,
                                    'type': edge_type
                                })
                                edge_set.add(edge_key)
            except Exception as e:
                logger.warning(f"Error expanding impacted modules: {e}")
        
        # Build module_info with metadata
        module_info = {}
        for mod_id in all_deps:
            try:
                module = self.query_engine.get_module_by_id(mod_id)
                if module:
                    deps = self.query_engine.get_dependencies(mod_id)
                    module_info[mod_id] = {
                        'path': module.get('path', mod_id),
                        'kind': module.get('kind', []),
                        'fan_in': deps.get('fan_in_count', 0),
                        'fan_out': deps.get('fan_out_count', 0),
                        'is_target': mod_id in target_module_ids
                    }
            except Exception as e:
                logger.debug(f"Error getting module info for {mod_id}: {e}")
                # Fallback info
                module_info[mod_id] = {
                    'path': mod_id,
                    'kind': [],
                    'fan_in': 0,
                    'fan_out': 0,
                    'is_target': mod_id in target_module_ids
                }
        
        return {
            'module_ids': list(all_deps),
            'edges': edges,
            'module_info': module_info,
            'target_modules': target_module_ids,
            'direction': direction
        }
    
    def _generate_text_diagram(self, graph_data: Dict[str, Any]) -> str:
        """Generate a text/ASCII diagram."""
        module_ids = graph_data.get('module_ids', [])
        edges = graph_data.get('edges', [])
        module_info = graph_data.get('module_info', {})
        
        if not module_ids:
            return "No modules found to diagram."
        
        # Build adjacency list
        adj_list = defaultdict(list)
        for edge in edges:
            from_mod = edge.get('from')
            to_mod = edge.get('to')
            if from_mod and to_mod:
                adj_list[from_mod].append(to_mod)
        
        # Generate tree-like representation
        diagram = "Dependency Diagram\n"
        diagram += "=" * 50 + "\n\n"
        
        # Group by root modules (modules with no incoming edges)
        incoming = set()
        for edge in edges:
            incoming.add(edge.get('to'))
        
        root_modules = [m for m in module_ids if m not in incoming]
        
        if not root_modules:
            # If no clear roots, just show all modules
            root_modules = module_ids[:10]  # Limit to 10
        
        def format_module_name(mod_id: str) -> str:
            """Format module name for display."""
            info = module_info.get(mod_id, {})
            path = info.get('path', mod_id)
            # Shorten path if too long
            if len(path) > 40:
                parts = path.split('/')
                if len(parts) > 2:
                    return f".../{'/'.join(parts[-2:])}"
            return path
        
        def print_tree(node: str, prefix: str = "", is_last: bool = True, visited: Set[str] = None, depth: int = 0):
            """Recursively print tree structure."""
            if visited is None:
                visited = set()
            if depth > 3 or node in visited:  # Limit depth and avoid cycles
                return ""
            
            visited.add(node)
            result = prefix + ("└── " if is_last else "├── ") + format_module_name(node) + "\n"
            
            children = adj_list.get(node, [])
            if children:
                for i, child in enumerate(children[:5]):  # Limit children
                    is_last_child = (i == len(children) - 1) or i >= 4
                    child_prefix = prefix + ("    " if is_last else "│   ")
                    result += print_tree(child, child_prefix, is_last_child, visited.copy(), depth + 1)
            
            return result
        
        for i, root in enumerate(root_modules[:5]):  # Limit roots
            is_last = (i == len(root_modules) - 1) or i >= 4
            diagram += print_tree(root, "", is_last, set(), 0)
            if i < len(root_modules) - 1:
                diagram += "\n"
        
        if len(module_ids) > len(root_modules):
            remaining = len(module_ids) - len(root_modules)
            diagram += f"\n... and {remaining} more modules\n"
        
        return diagram
    
    def _generate_dot_format(self, graph_data: Dict[str, Any]) -> str:
        """Generate Graphviz DOT format diagram."""
        module_ids = graph_data.get('module_ids', [])
        edges = graph_data.get('edges', [])
        module_info = graph_data.get('module_info', {})
        
        dot = "digraph Dependencies {\n"
        dot += "  rankdir=LR;\n"
        dot += "  node [shape=box, style=rounded];\n\n"
        
        # Add nodes
        for mod_id in module_ids:
            info = module_info.get(mod_id, {})
            path = info.get('path', mod_id)
            # Escape special characters and shorten
            label = path.replace('"', '\\"')
            if len(label) > 30:
                parts = label.split('/')
                if len(parts) > 1:
                    label = f".../{parts[-1]}"
            
            # Create safe node ID
            node_id = mod_id.replace(':', '_').replace('/', '_').replace('.', '_')
            dot += f'  "{node_id}" [label="{label}"];\n'
        
        dot += "\n"
        
        # Add edges
        for edge in edges:
            from_mod = edge.get('from')
            to_mod = edge.get('to')
            if from_mod and to_mod:
                from_id = from_mod.replace(':', '_').replace('/', '_').replace('.', '_')
                to_id = to_mod.replace(':', '_').replace('/', '_').replace('.', '_')
                dot += f'  "{from_id}" -> "{to_id}";\n'
        
        dot += "}\n"
        
        return dot
    
    def _generate_mermaid_format(self, graph_data: Dict[str, Any]) -> str:
        """Generate Mermaid format diagram with support for focused diagrams."""
        module_ids = graph_data.get('module_ids', [])
        edges = graph_data.get('edges', [])
        module_info = graph_data.get('module_info', {})
        
        # Check if this is a focused diagram
        is_focused = 'target_modules' in graph_data
        target_modules = graph_data.get('target_modules', [])
        direction = graph_data.get('direction', 'both')
        
        mermaid = "graph TD\n"
        
        # Define styles for focused diagrams
        if is_focused:
            mermaid += "  classDef targetModule fill:#ff6b6b,stroke:#c92a2a,stroke-width:3px,color:#fff\n"
            mermaid += "  classDef serviceModule fill:#4ecdc4,stroke:#26a69a,stroke-width:2px\n"
            mermaid += "  classDef controllerModule fill:#95e1d3,stroke:#6ab5b8,stroke-width:2px\n"
            mermaid += "  classDef entityModule fill:#ffeaa7,stroke:#fdcb6e,stroke-width:2px\n"
            mermaid += "  classDef repositoryModule fill:#a29bfe,stroke:#6c5ce7,stroke-width:2px\n"
            mermaid += "  classDef defaultModule fill:#dfe6e9,stroke:#b2bec3,stroke-width:1px\n"
            mermaid += "\n"
        
        # Group modules by kind for focused diagrams
        modules_by_kind = defaultdict(list)
        if is_focused:
            for mod_id in module_ids:
                info = module_info.get(mod_id, {})
                kinds = info.get('kind', [])
                if isinstance(kinds, list) and kinds:
                    # Use first kind for grouping
                    primary_kind = kinds[0].lower()
                    modules_by_kind[primary_kind].append(mod_id)
                else:
                    modules_by_kind['other'].append(mod_id)
        
        # Create node mapping
        node_map = {}
        node_classes = {}  # Track which class to apply to each node
        
        # If focused and has kind groups, use subgraphs
        if is_focused and modules_by_kind:
            kind_order = ['controller', 'service', 'entity', 'repository', 'component', 'module', 'other']
            for kind in kind_order:
                if kind in modules_by_kind and modules_by_kind[kind]:
                    # Create subgraph for this kind
                    kind_label = kind.capitalize() + 's'
                    mermaid += f"  subgraph {kind_label}\n"
                    
                    for mod_id in modules_by_kind[kind]:
                        info = module_info.get(mod_id, {})
                        path = info.get('path', mod_id)
                        display_name = self._format_module_name(path)
                        
                        node_id = f"M{len(node_map)}"
                        node_map[mod_id] = node_id
                        mermaid += f'    {node_id}["{display_name}"]\n'
                        
                        # Determine node class
                        if mod_id in target_modules:
                            node_classes[node_id] = 'targetModule'
                        elif kind == 'service':
                            node_classes[node_id] = 'serviceModule'
                        elif kind == 'controller':
                            node_classes[node_id] = 'controllerModule'
                        elif kind == 'entity':
                            node_classes[node_id] = 'entityModule'
                        elif kind == 'repository':
                            node_classes[node_id] = 'repositoryModule'
                        else:
                            node_classes[node_id] = 'defaultModule'
                    
                    mermaid += "  end\n\n"
            
            # Add any remaining modules not in kind groups
            for mod_id in module_ids:
                if mod_id not in node_map:
                    info = module_info.get(mod_id, {})
                    path = info.get('path', mod_id)
                    display_name = self._format_module_name(path)
                    
                    node_id = f"M{len(node_map)}"
                    node_map[mod_id] = node_id
                    mermaid += f'  {node_id}["{display_name}"]\n'
                    
                    if mod_id in target_modules:
                        node_classes[node_id] = 'targetModule'
                    else:
                        node_classes[node_id] = 'defaultModule'
        else:
            # Standard diagram without subgraphs
            for i, mod_id in enumerate(module_ids):
                info = module_info.get(mod_id, {})
                path = info.get('path', mod_id)
                display_name = self._format_module_name(path)
                
                node_id = f"M{i}"
                node_map[mod_id] = node_id
                mermaid += f'  {node_id}["{display_name}"]\n'
                
                if is_focused and mod_id in target_modules:
                    node_classes[node_id] = 'targetModule'
        
        mermaid += "\n"
        
        # Add edges with labels for focused diagrams
        edge_type_counts = defaultdict(int)
        for edge in edges:
            from_mod = edge.get('from')
            to_mod = edge.get('to')
            edge_type = edge.get('type', 'imports')
            
            if from_mod and to_mod and from_mod in node_map and to_mod in node_map:
                edge_type_counts[edge_type] += 1
                
                if is_focused and edge_type in ['imports', 'calls', 'extends']:
                    # Add edge label for relationship type
                    edge_label = edge_type.capitalize()
                    mermaid += f'  {node_map[from_mod]} -->|"{edge_label}"| {node_map[to_mod]}\n'
                else:
                    mermaid += f'  {node_map[from_mod]} --> {node_map[to_mod]}\n'
        
        # Apply classes to nodes for focused diagrams
        if is_focused and node_classes:
            for node_id, class_name in node_classes.items():
                mermaid += f'  class {node_id} {class_name}\n'
        
        # Add legend for focused diagrams
        if is_focused:
            mermaid += "\n"
            mermaid += "  subgraph Legend[\"Legend\"]\n"
            mermaid += "    direction LR\n"
            mermaid += "    L1[\"Target Module\"]:::targetModule\n"
            mermaid += "    L2[\"Service\"]:::serviceModule\n"
            mermaid += "    L3[\"Controller\"]:::controllerModule\n"
            mermaid += "    L4[\"Entity\"]:::entityModule\n"
            mermaid += "    L5[\"Repository\"]:::repositoryModule\n"
            mermaid += "  end\n"
            
            # Add direction info if not both
            if direction != 'both':
                direction_text = "Incoming dependencies (callers)" if direction == 'incoming' else "Outgoing dependencies (callees)"
                mermaid += f'\n  note1["{direction_text}"]\n'
        
        return mermaid
    
    def _format_module_name(self, path: str, max_length: int = 30) -> str:
        """Format module path for display in diagram."""
        # Shorten path
        if len(path) > max_length:
            parts = path.split('/')
            if len(parts) > 1:
                display_name = f".../{parts[-1]}"
            else:
                display_name = path[:max_length] + "..."
        else:
            display_name = path
        
        # Escape special characters for Mermaid
        display_name = display_name.replace('"', '&quot;').replace("'", "&#39;")
        return display_name
    
    def _extract_module_from_query(self, query: str) -> Optional[str]:
        """Try to extract module ID or path from query."""
        # Look for "mod:path" pattern
        mod_match = re.search(r'mod:([^\s]+)', query)
        if mod_match:
            return mod_match.group(0)
        
        # Look for file paths
        path_match = re.search(r'([a-zA-Z0-9_/\\]+\.(py|ts|js|tsx|jsx))', query)
        if path_match:
            path = path_match.group(1)
            # Try to find module with this path
            for module in self.pkg_data.get('modules', []):
                if path in module.get('path', '') or module.get('path', '').endswith(path):
                    return module.get('id')
        
        # Fallback to new parsing method
        try:
            query_obj = self._parse_query_for_module(query)
            found_modules = self._find_modules_from_query(query_obj)
            if found_modules:
                return found_modules[0].get('id')
        except Exception:
            pass
        
        return None
    
    def _parse_query_for_module(self, query: str) -> Dict[str, Any]:
        """
        Parse natural language query to extract structured module search information.
        
        Args:
            query: Natural language query string
            
        Returns:
            Dictionary with search_terms, file_pattern, module_kinds, feature_names, direction
        """
        query_lower = query.lower()
        
        # Initialize result structure
        result = {
            "search_terms": [],
            "file_pattern": None,
            "module_kinds": [],
            "feature_names": [],
            "direction": "both",
            "target_modules": []
        }
        
        # Extract file pattern (e.g., "user.py", "auth.service.ts")
        file_pattern_match = re.search(r'([a-zA-Z0-9_\-]+\.(py|ts|js|tsx|jsx|java|cs|cpp|c))', query, re.IGNORECASE)
        if file_pattern_match:
            result["file_pattern"] = file_pattern_match.group(1)
        
        # Detect dependency direction
        if re.search(r'(what|which|show).*(files?|modules?|components?).*(depend|depends|call|calls|use|uses).*on', query_lower):
            # "what files depend on X" -> incoming (fan-in)
            result["direction"] = "incoming"
        elif re.search(r'(what|which|show).*(does|do).*(depend|depends|call|calls|use|uses).*on', query_lower):
            # "what does X depend on" -> outgoing (fan-out)
            result["direction"] = "outgoing"
        elif 'depend on' in query_lower or 'depends on' in query_lower:
            # Default to outgoing if "depend on" is mentioned
            if 'what' in query_lower or 'which' in query_lower:
                result["direction"] = "outgoing"
        
        # Common module type keywords
        module_kind_keywords = {
            'service': ['service', 'services'],
            'controller': ['controller', 'controllers', 'ctrl'],
            'component': ['component', 'components'],
            'entity': ['entity', 'entities', 'model', 'models'],
            'repository': ['repository', 'repositories', 'repo', 'repos'],
            'module': ['module', 'modules'],
            'util': ['util', 'utils', 'utility', 'utilities'],
            'helper': ['helper', 'helpers'],
            'middleware': ['middleware'],
            'guard': ['guard', 'guards'],
            'interceptor': ['interceptor', 'interceptors'],
            'decorator': ['decorator', 'decorators'],
            'pipe': ['pipe', 'pipes'],
            'directive': ['directive', 'directives']
        }
        
        # Extract module kinds
        for kind, keywords in module_kind_keywords.items():
            if any(kw in query_lower for kw in keywords):
                if kind not in result["module_kinds"]:
                    result["module_kinds"].append(kind)
        
        # Extract feature names (common features)
        feature_keywords = ['login', 'auth', 'authentication', 'user', 'payment', 'order', 
                          'product', 'cart', 'checkout', 'admin', 'dashboard', 'profile']
        for feature in feature_keywords:
            if feature in query_lower:
                if feature not in result["feature_names"]:
                    result["feature_names"].append(feature)
        
        # Extract search terms (meaningful words, excluding stop words)
        stop_words = {'the', 'a', 'an', 'is', 'are', 'was', 'were', 'be', 'been', 'being',
                     'have', 'has', 'had', 'do', 'does', 'did', 'will', 'would', 'should',
                     'could', 'may', 'might', 'must', 'can', 'what', 'which', 'where',
                     'when', 'why', 'how', 'show', 'create', 'generate', 'make', 'get',
                     'file', 'files', 'module', 'modules', 'component', 'components',
                     'depend', 'depends', 'dependency', 'dependencies', 'diagram', 'map',
                     'of', 'on', 'in', 'at', 'to', 'for', 'with', 'from', 'by'}
        
        # Tokenize query and extract meaningful terms
        words = re.findall(r'\b[a-zA-Z][a-zA-Z0-9_]*\b', query_lower)
        for word in words:
            if word not in stop_words and len(word) > 2:
                # Skip if it's already in module_kinds or feature_names
                if word not in result["module_kinds"] and word not in result["feature_names"]:
                    if word not in result["search_terms"]:
                        result["search_terms"].append(word)
        
        # If we have a file pattern, extract the base name as a search term
        if result["file_pattern"]:
            base_name = os.path.splitext(result["file_pattern"])[0]
            if base_name not in result["search_terms"]:
                result["search_terms"].append(base_name)
        
        return result
    
    def _find_modules_from_query(self, query_obj: Dict[str, Any]) -> List[Dict[str, Any]]:
        """
        Intelligently find modules from parsed query using multiple search strategies.
        
        Args:
            query_obj: Parsed query object from _parse_query_for_module
            
        Returns:
            List of matching modules with confidence scores, sorted by relevance
        """
        found_modules = []
        seen_ids = set()
        
        # Strategy 1: Exact filename match (highest confidence)
        if query_obj.get("file_pattern"):
            try:
                modules = self.query_engine.get_modules_by_filename(query_obj["file_pattern"])
                for mod in modules:
                    mod_id = mod.get('id')
                    if mod_id and mod_id not in seen_ids:
                        mod['_confidence'] = 100
                        found_modules.append(mod)
                        seen_ids.add(mod_id)
            except Exception as e:
                logger.debug(f"Filename search failed: {e}")
        
        # Strategy 2: Kind-based search with search term filtering
        for kind in query_obj.get("module_kinds", []):
            try:
                # Try PKG first
                modules = self.query_engine.get_modules_by_kind(kind)
                
                # Try Neo4j if available
                if self.neo4j_engine and self.project_id:
                    try:
                        neo4j_modules = self.neo4j_engine.get_modules_by_tag(self.project_id, kind)
                        # Convert Neo4j nodes to dicts if needed
                        for nm in neo4j_modules:
                            if isinstance(nm, dict):
                                modules.append(nm)
                            else:
                                modules.append(dict(nm) if hasattr(nm, 'items') else nm)
                    except Exception as e:
                        logger.debug(f"Neo4j kind search failed: {e}")
                
                # Filter by search terms if provided
                if query_obj.get("search_terms"):
                    filtered_modules = []
                    for mod in modules:
                        mod_path = mod.get('path', '').lower()
                        mod_id = mod.get('id', '')
                        # Check if any search term matches path or name
                        matches = any(term.lower() in mod_path or term.lower() in mod_id.lower() 
                                    for term in query_obj["search_terms"])
                        if matches:
                            filtered_modules.append(mod)
                    modules = filtered_modules
                
                # Add modules with confidence score
                for mod in modules:
                    mod_id = mod.get('id')
                    if mod_id and mod_id not in seen_ids:
                        mod['_confidence'] = 80  # Exact kind match
                        found_modules.append(mod)
                        seen_ids.add(mod_id)
            except Exception as e:
                logger.debug(f"Kind search failed: {e}")
        
        # Strategy 3: Tag-based search for search terms
        for term in query_obj.get("search_terms", []):
            if term not in query_obj.get("module_kinds", []):  # Skip if already searched as kind
                try:
                    modules = self.query_engine.get_modules_by_tag(term)
                    
                    # Try Neo4j if available
                    if self.neo4j_engine and self.project_id:
                        try:
                            neo4j_modules = self.neo4j_engine.get_modules_by_tag(self.project_id, term)
                            for nm in neo4j_modules:
                                if isinstance(nm, dict):
                                    modules.append(nm)
                                else:
                                    modules.append(dict(nm) if hasattr(nm, 'items') else nm)
                        except Exception:
                            pass
                    
                    for mod in modules:
                        mod_id = mod.get('id')
                        if mod_id and mod_id not in seen_ids:
                            # Lower confidence for tag match
                            mod['_confidence'] = 40
                            found_modules.append(mod)
                            seen_ids.add(mod_id)
                except Exception as e:
                    logger.debug(f"Tag search failed: {e}")
        
        # Strategy 4: Path pattern search
        if query_obj.get("search_terms"):
            for term in query_obj["search_terms"]:
                try:
                    # Try wildcard pattern
                    pattern = f"*{term}*"
                    modules = self.query_engine.get_modules_by_path_pattern(pattern)
                    
                    for mod in modules:
                        mod_id = mod.get('id')
                        if mod_id and mod_id not in seen_ids:
                            mod['_confidence'] = 60  # Partial path match
                            found_modules.append(mod)
                            seen_ids.add(mod_id)
                except Exception as e:
                    logger.debug(f"Path pattern search failed: {e}")
        
        # Strategy 5: Symbol search (find symbols, then get their modules)
        if query_obj.get("search_terms"):
            for term in query_obj["search_terms"]:
                try:
                    symbols = self.query_engine.get_symbols_by_name(f"*{term}*")
                    for symbol in symbols:
                        symbol_id = symbol.get('id', '')
                        # Extract module ID from symbol ID (format: sym:mod:path:symbol_name)
                        if symbol_id.startswith('sym:'):
                            parts = symbol_id.split(':')
                            if len(parts) >= 3:
                                module_id = f"mod:{parts[2]}"
                                module = self.query_engine.get_module_by_id(module_id)
                                if module:
                                    mod_id = module.get('id')
                                    if mod_id and mod_id not in seen_ids:
                                        mod = dict(module)
                                        mod['_confidence'] = 30  # Symbol match
                                        found_modules.append(mod)
                                        seen_ids.add(mod_id)
                except Exception as e:
                    logger.debug(f"Symbol search failed: {e}")
        
        # Strategy 6: Feature-based search
        for feature in query_obj.get("feature_names", []):
            try:
                # Search modules in feature paths
                pattern = f"*{feature}*"
                modules = self.query_engine.get_modules_by_path_pattern(pattern)
                
                for mod in modules:
                    mod_id = mod.get('id')
                    if mod_id and mod_id not in seen_ids:
                        mod['_confidence'] = 50  # Feature match
                        found_modules.append(mod)
                        seen_ids.add(mod_id)
            except Exception as e:
                logger.debug(f"Feature search failed: {e}")
        
        # Sort by confidence (highest first) and return
        found_modules.sort(key=lambda x: x.get('_confidence', 0), reverse=True)
        
        # Update query_obj with found modules
        query_obj["target_modules"] = found_modules
        
        return found_modules
    
    def _init_llm(self) -> None:
        """Initialize LLM for architecture diagram generation."""
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, architecture diagram generation will be limited")
                return
            
            model = os.getenv("LLM_MODEL", "gpt-4")
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "4000"))
            
            self.llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                openai_api_key=api_key
            )
            logger.debug("LLM initialized for architecture diagram generation")
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
            self.llm = None
    
    def _init_neo4j_engine(self):
        """Initialize Neo4jQueryEngine if Neo4j is available."""
        try:
            import db.neo4j_db as neo4j_db
            from db.neo4j_query_engine import Neo4jQueryEngine
            
            if neo4j_db.verify_connection():
                logger.debug(f"Initializing Neo4jQueryEngine for project: {self.project_id}")
                return Neo4jQueryEngine()
            else:
                logger.debug("Neo4j connection not available, using in-memory PKG queries only")
                return None
        except Exception as e:
            logger.warning(f"Failed to initialize Neo4j engine: {e}", exc_info=True)
            return None
    
    def _collect_architecture_data(self) -> Dict[str, Any]:
        """
        Collect architecture information from PKG/Neo4j.
        
        Returns:
            Dictionary with architecture summary including modules by kind, dependencies, entry points, etc.
        """
        architecture_data = {
            "modules_by_kind": {},
            "total_modules": 0,
            "entry_points": [],
            "critical_modules": [],
            "dependency_patterns": {},
            "features": []
        }
        
        try:
            # Get all modules
            all_modules = self.pkg_data.get('modules', [])
            architecture_data["total_modules"] = len(all_modules)
            
            # Group modules by kind
            modules_by_kind = defaultdict(list)
            for module in all_modules:
                kinds = module.get('kind', [])
                if isinstance(kinds, list):
                    for kind in kinds:
                        modules_by_kind[kind].append({
                            'id': module.get('id'),
                            'path': module.get('path', ''),
                            'name': os.path.basename(module.get('path', ''))
                        })
                elif kinds:
                    modules_by_kind[kinds].append({
                        'id': module.get('id'),
                        'path': module.get('path', ''),
                        'name': os.path.basename(module.get('path', ''))
                    })
            
            architecture_data["modules_by_kind"] = dict(modules_by_kind)
            
            # Get entry points
            entry_points = self.query_engine.get_entry_point_modules()
            architecture_data["entry_points"] = [
                {
                    'id': ep.get('id'),
                    'path': ep.get('path', ''),
                    'kind': ep.get('kind', [])
                }
                for ep in entry_points
            ]
            
            # Get critical modules (high fan-in) using Neo4j if available
            if self.neo4j_engine and self.project_id:
                try:
                    critical = self.neo4j_engine.get_critical_modules(self.project_id, limit=10)
                    architecture_data["critical_modules"] = [
                        {
                            'id': item.get('module', {}).get('id', ''),
                            'path': item.get('module', {}).get('path', ''),
                            'fan_in': item.get('fan_in', 0)
                        }
                        for item in critical
                    ]
                except Exception as e:
                    logger.warning(f"Failed to get critical modules from Neo4j: {e}")
            
            # Analyze dependency patterns
            edges = self.pkg_data.get('edges', [])
            dependency_types = defaultdict(int)
            for edge in edges:
                edge_type = edge.get('type', 'unknown')
                dependency_types[edge_type] += 1
            
            architecture_data["dependency_patterns"] = dict(dependency_types)
            
            # Get features if available
            features = self.pkg_data.get('features', [])
            architecture_data["features"] = [
                {
                    'id': feat.get('id', ''),
                    'name': feat.get('name', ''),
                    'path': feat.get('path', '')
                }
                for feat in features[:10]  # Limit to 10 features
            ]
            
        except Exception as e:
            logger.error(f"Error collecting architecture data: {e}", exc_info=True)
        
        return architecture_data
    
    def _generate_architecture_diagram(self, user_message: str) -> str:
        """
        Generate architecture diagram using LLM analysis.
        
        Args:
            user_message: User's message/request
            
        Returns:
            Mermaid code for architecture diagram
        """
        if not self.llm:
            raise Exception("LLM not initialized, cannot generate architecture diagram")
        
        # Collect architecture data
        arch_data = self._collect_architecture_data()
        
        # Build LLM prompt
        prompt = f"""You are an expert software architect. Analyze the codebase structure and generate a comprehensive Mermaid architecture diagram.

Codebase Summary:
- Total Modules: {arch_data['total_modules']}
- Modules by Kind:
{json.dumps(arch_data['modules_by_kind'], indent=2)}

- Entry Points: {len(arch_data['entry_points'])}
{json.dumps([ep['path'] for ep in arch_data['entry_points']], indent=2)}

- Critical Modules (High Fan-in): {len(arch_data['critical_modules'])}
{json.dumps([{'path': cm['path'], 'fan_in': cm['fan_in']} for cm in arch_data['critical_modules']], indent=2)}

- Dependency Patterns:
{json.dumps(arch_data['dependency_patterns'], indent=2)}

- Features: {len(arch_data['features'])}
{json.dumps([f['name'] for f in arch_data['features']], indent=2)}

User Request: {user_message}

Generate a Mermaid architecture diagram (graph TD format) that shows:
1. High-level architectural layers (e.g., Controllers, Services, Data Access, Entities, etc.)
2. Key modules/components in each layer (limit to most important ones)
3. Relationships and data flow between layers
4. Entry points and critical modules
5. Clear, readable structure with proper grouping

Requirements:
- Use Mermaid graph TD syntax
- Group related modules into subgraphs or layers
- Use descriptive labels (shorten long paths)
- Show data flow direction with arrows
- Keep the diagram readable (limit to ~20-30 key modules)
- Use appropriate node shapes and styling

Return ONLY the Mermaid code, no explanations or markdown formatting."""
        
        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Extract Mermaid code from response (handle markdown code blocks)
            mermaid_code = content.strip()
            
            # Remove markdown code blocks if present
            if mermaid_code.startswith('```'):
                # Extract content between ```mermaid and ```
                match = re.search(r'```(?:mermaid)?\s*\n(.*?)\n```', mermaid_code, re.DOTALL)
                if match:
                    mermaid_code = match.group(1).strip()
                else:
                    # Try to remove just the opening/closing ```
                    mermaid_code = re.sub(r'^```[a-z]*\s*\n', '', mermaid_code)
                    mermaid_code = re.sub(r'\n```\s*$', '', mermaid_code)
            
            # Validate that it starts with a valid Mermaid graph type
            if not re.match(r'^\s*(graph|flowchart|classDiagram|erDiagram|sequenceDiagram|stateDiagram|gantt|pie|gitgraph|journey|requirement)', mermaid_code, re.IGNORECASE):
                # If no graph type, assume graph TD
                if not mermaid_code.strip().startswith('graph'):
                    mermaid_code = 'graph TD\n' + mermaid_code
            
            logger.debug(f"Generated Mermaid architecture diagram ({len(mermaid_code)} chars)")
            return mermaid_code.strip()
            
        except Exception as e:
            logger.error(f"Error generating architecture diagram with LLM: {e}", exc_info=True)
            raise
    
    def _render_mermaid_to_image(self, mermaid_code: str, resolution: int = 2) -> Tuple[str, Dict[str, Any]]:
        """
        Render Mermaid code to high-resolution image and return as Markdown.
        
        Uses Playwright for high-resolution rendering with fallback chain:
        1. Playwright (high-res, minimum 2024px width, 2024x1140 * resolution)
        2. mermaid-cli (if available, with --scale parameter)
        3. Mermaid.ink API (low-res fallback)
        4. Code block (final fallback)
        
        Args:
            mermaid_code: Mermaid diagram code
            resolution: Resolution multiplier (default: 2 for 2x scale, gives 4048px width)
            
        Returns:
            Tuple of (markdown string with embedded image, metadata dict)
            Metadata includes: rendered (bool), resolution (int), method (str), width, height
        """
        # Try Playwright first (high-resolution rendering)
        try:
            return self._render_with_playwright(mermaid_code, resolution)
        except Exception as e:
            logger.warning(f"Playwright rendering failed: {e}, trying fallback methods")
        
        # Fallback 1: Try mermaid-cli
        try:
            return self._render_with_mermaid_cli(mermaid_code, resolution)
        except Exception as e:
            logger.warning(f"mermaid-cli rendering failed: {e}, trying Mermaid.ink")
        
        # Fallback 2: Try Mermaid.ink API (low-res)
        try:
            return self._render_with_mermaid_ink(mermaid_code)
        except Exception as e:
            logger.warning(f"Mermaid.ink API failed: {e}, falling back to code block")
        
        # Fallback 3: Return code block
        logger.warning("All rendering methods failed, returning Mermaid code block")
        return (
            f"```mermaid\n{mermaid_code}\n```",
            {"rendered": False, "resolution": 0, "method": "code_block"}
        )
    
    def _render_with_playwright(self, mermaid_code: str, resolution: int = 2) -> Tuple[str, Dict[str, Any]]:
        """
        Render Mermaid diagram using Playwright in headless browser.
        
        Generates high-resolution images with minimum 2024px width.
        For resolution=2: 4048x2280px with 2x device scale factor for crisp text.
        
        Args:
            mermaid_code: Mermaid diagram code
            resolution: Resolution multiplier (2 = 4048px width, 3 = 6072px width)
            
        Returns:
            Tuple of (markdown string, metadata dict)
        """
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise Exception("Playwright not installed. Install with: pip install playwright && playwright install chromium")
        
        # Calculate dimensions - ensure minimum 2024px width
        # Base dimensions: 2024x1140 (maintains 16:9 aspect ratio, meets 2024px minimum)
        base_width = 2024
        base_height = 1140
        width = base_width * resolution
        height = base_height * resolution
        
        # Create HTML page with Mermaid.js
        html_content = f"""<!DOCTYPE html>
<html>
<head>
    <meta charset="UTF-8">
    <script src="https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js"></script>
    <style>
        body {{
            margin: 0;
            padding: 20px;
            background: white;
            font-family: Arial, sans-serif;
        }}
        .mermaid {{
            display: flex;
            justify-content: center;
            align-items: center;
        }}
    </style>
</head>
<body>
    <div class="mermaid">
{mermaid_code}
    </div>
    <script>
        mermaid.initialize({{
            startOnLoad: true,
            theme: 'default',
            themeVariables: {{
                fontSize: '16px'
            }}
        }});
    </script>
</body>
</html>"""
        
        try:
            with sync_playwright() as p:
                # Try to launch browser (handle if not installed)
                try:
                    browser = p.chromium.launch(headless=True)
                except Exception as e:
                    # Browser might not be installed
                    logger.warning(f"Could not launch Chromium browser: {e}. Run 'playwright install chromium' to install.")
                    raise Exception("Chromium browser not installed")
                
                try:
                    # Create page with high DPI
                    page = browser.new_page(
                        viewport={"width": width, "height": height},
                        device_scale_factor=resolution
                    )
                    
                    # Set content and wait for Mermaid to render
                    page.set_content(html_content)
                    
                    # Wait for Mermaid to render (check for SVG elements)
                    page.wait_for_selector("svg", timeout=10000)
                    
                    # Wait a bit more for any animations/transitions
                    page.wait_for_timeout(500)
                    
                    # Take screenshot of the mermaid element with high DPI
                    # Using page.screenshot() with clip ensures device_scale_factor is properly applied
                    mermaid_element = page.query_selector(".mermaid")
                    if mermaid_element:
                        # Get element bounding box (in CSS pixels)
                        box = mermaid_element.bounding_box()
                        if box:
                            # Use page screenshot with clip - output will be scaled by device_scale_factor
                            screenshot_bytes = page.screenshot(
                                type="png",
                                clip={
                                    "x": max(0, box["x"] - 10),  # Add small padding
                                    "y": max(0, box["y"] - 10),
                                    "width": box["width"] + 20,
                                    "height": box["height"] + 20
                                }
                            )
                            # Screenshot dimensions are automatically scaled by device_scale_factor
                            # So actual pixel dimensions = CSS dimensions * resolution
                            actual_width = int((box["width"] + 20) * resolution)
                            actual_height = int((box["height"] + 20) * resolution)
                        else:
                            # Fallback to element screenshot (also respects device_scale_factor)
                            screenshot_bytes = mermaid_element.screenshot(type="png")
                            # Element screenshot dimensions are scaled by device_scale_factor
                            actual_width = width
                            actual_height = height
                    else:
                        # Fallback to viewport screenshot
                        screenshot_bytes = page.screenshot(
                            type="png",
                            full_page=False
                        )
                        # Viewport screenshot respects device_scale_factor
                        actual_width = width
                        actual_height = height
                    
                    # Convert to base64 data URI
                    image_base64 = base64.b64encode(screenshot_bytes).decode('utf-8')
                    data_uri = f"data:image/png;base64,{image_base64}"
                    
                    # Return markdown with image
                    markdown = f"![Diagram]({data_uri})"
                    
                    logger.debug(f"Successfully rendered Mermaid diagram with Playwright at {actual_width}x{actual_height}")
                    
                    return (
                        markdown,
                        {"rendered": True, "resolution": resolution, "method": "playwright", "width": actual_width, "height": actual_height}
                    )
                    
                finally:
                    browser.close()
                    
        except Exception as e:
            raise Exception(f"Playwright rendering error: {e}")
    
    def _render_with_mermaid_cli(self, mermaid_code: str, resolution: int = 2) -> Tuple[str, Dict[str, Any]]:
        """
        Render Mermaid diagram using mermaid-cli (mmdc) command-line tool.
        
        Args:
            mermaid_code: Mermaid diagram code
            resolution: Resolution multiplier
            
        Returns:
            Tuple of (markdown string, metadata dict)
        """
        import subprocess
        import tempfile
        import shutil
        
        # Check if mmdc is available
        if not shutil.which("mmdc"):
            raise Exception("mermaid-cli (mmdc) not found in PATH")
        
        # Calculate dimensions - ensure minimum 2024px width
        # Base dimensions: 2024x1140 (maintains 16:9 aspect ratio, meets 2024px minimum)
        base_width = 2024
        base_height = 1140
        width = base_width * resolution
        height = base_height * resolution
        
        # Create temporary files
        with tempfile.NamedTemporaryFile(mode='w', suffix='.mmd', delete=False) as input_file:
            input_file.write(mermaid_code)
            input_file_path = input_file.name
        
        try:
            with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as output_file:
                output_file_path = output_file.name
            
            # Run mmdc command with high resolution
            # Width and height already account for resolution scaling (2024 * resolution)
            cmd_base = [
                "mmdc",
                "-i", input_file_path,
                "-o", output_file_path,
                "-w", str(width),  # Already scaled: 2024 * resolution
                "-H", str(height),  # Already scaled: 1140 * resolution
                "-b", "white"
            ]
            
            # Try with scale parameter if resolution > 1 (may not be supported by all versions)
            result = None
            if resolution > 1:
                # Some versions of mmdc support -s for scale, but it's optional
                # Try with scale first, fall back if it fails
                cmd_with_scale = cmd_base + ["-s", str(resolution)]
                result = subprocess.run(
                    cmd_with_scale,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
                if result.returncode != 0:
                    # Scale parameter not supported, use width/height only
                    logger.debug("mmdc -s parameter not supported, using width/height only")
                    result = None  # Reset to try without scale
            
            # Run without scale if previous attempt failed or wasn't tried
            if result is None or result.returncode != 0:
                result = subprocess.run(
                    cmd_base,
                    capture_output=True,
                    text=True,
                    timeout=30
                )
            
            if result.returncode != 0:
                raise Exception(f"mmdc failed: {result.stderr}")
            
            # Read the generated PNG
            with open(output_file_path, 'rb') as f:
                image_data = f.read()
            
            # Convert to base64 data URI
            image_base64 = base64.b64encode(image_data).decode('utf-8')
            data_uri = f"data:image/png;base64,{image_base64}"
            
            # Return markdown with image
            markdown = f"![Diagram]({data_uri})"
            
            logger.debug(f"Successfully rendered Mermaid diagram with mermaid-cli at {width}x{height}")
            
            return (
                markdown,
                {"rendered": True, "resolution": resolution, "method": "mermaid_cli", "width": width, "height": height}
            )
            
        finally:
            # Clean up temporary files
            try:
                os.unlink(input_file_path)
            except:
                pass
            try:
                os.unlink(output_file_path)
            except:
                pass
    
    def _render_with_mermaid_ink(self, mermaid_code: str) -> Tuple[str, Dict[str, Any]]:
        """
        Render Mermaid diagram using Mermaid.ink API (low-resolution fallback).
        
        Args:
            mermaid_code: Mermaid diagram code
            
        Returns:
            Tuple of (markdown string, metadata dict)
        """
        import urllib.parse
        import urllib.request
        
        # Use base64 encoding for better reliability with complex diagrams
        mermaid_bytes = mermaid_code.encode('utf-8')
        mermaid_b64 = base64.urlsafe_b64encode(mermaid_bytes).decode('utf-8')
        url = f"https://mermaid.ink/img/{mermaid_b64}"
        
        # Fetch the image
        with urllib.request.urlopen(url, timeout=15) as response:
            if response.status == 200:
                image_data = response.read()
                
                # Determine content type
                content_type = response.headers.get('Content-Type', 'image/svg+xml')
                if 'svg' in content_type.lower():
                    # Convert SVG to base64 data URI
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    data_uri = f"data:image/svg+xml;base64,{image_base64}"
                else:
                    # PNG or other format
                    image_base64 = base64.b64encode(image_data).decode('utf-8')
                    data_uri = f"data:{content_type};base64,{image_base64}"
                
                # Return Markdown with image
                markdown = f"![Diagram]({data_uri})"
                logger.debug("Successfully rendered Mermaid diagram with Mermaid.ink (low-res)")
                
                return (
                    markdown,
                    {"rendered": True, "resolution": 1, "method": "mermaid_ink", "note": "low_resolution"}
                )
            else:
                raise Exception(f"Mermaid.ink API returned status {response.status}")

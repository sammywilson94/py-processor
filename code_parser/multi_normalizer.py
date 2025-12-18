"""Multi-language normalizer to extract definitions from various programming languages."""

import re
from typing import Any, Dict, Optional, List
from tree_sitter import Node

from code_parser.normalizer import get_text, extract_docstring
from code_parser.multi_parser import parse_source, detect_language


def extract_python_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract Python definitions (reuse existing implementation)."""
    from code_parser.normalizer import extract_python_definitions as py_extract
    return py_extract(root, source)


def extract_ts_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract TypeScript definitions (reuse existing implementation)."""
    from code_parser.normalizer import extract_ts_definitions as ts_extract
    return ts_extract(root, source)


def extract_js_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract JavaScript definitions (similar to TypeScript)."""
    results: Dict[str, Any] = {
        "functions": [],
        "classes": [],
        "imports": [],
        "variables": [],
        "calls": []
    }
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    for node in walk(root):
        if node.type == "import_statement":
            results["imports"].append(get_text(node, source))
        
        elif node.type == "function_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            params = get_text(node.child_by_field_name("parameters"), source)
            results["functions"].append({"name": name, "parameters": params})
        
        elif node.type == "arrow_function":
            # Handle arrow functions assigned to variables
            parent = node.parent
            if parent and parent.type == "variable_declarator":
                name_node = parent.child_by_field_name("name")
                name = get_text(name_node, source) if name_node else None
                params = get_text(node.child_by_field_name("parameters"), source)
                if name:
                    results["functions"].append({"name": name, "parameters": params})
        
        elif node.type == "class_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "method_definition":
                        method_name = get_text(child.child_by_field_name("name"), source)
                        methods.append({"name": method_name})
            results["classes"].append({"name": name, "methods": methods})
        
        elif node.type == "variable_declaration":
            results["variables"].append(get_text(node, source))
        
        elif node.type == "call_expression":
            func = get_text(node.child_by_field_name("function"), source)
            args_node = node.child_by_field_name("arguments")
            args = [get_text(arg, source) for arg in args_node.children if arg.type not in (",", "(", ")")]
            results["calls"].append({"function": func, "arguments": args})
    
    return results


def extract_java_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract Java definitions including classes, methods, interfaces, and annotations."""
    results: Dict[str, Any] = {
        "classes": [],
        "interfaces": [],
        "methods": [],
        "imports": [],
        "annotations": [],
        "fields": []
    }
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    for node in walk(root):
        if node.type == "import_declaration":
            results["imports"].append(get_text(node, source))
        
        elif node.type == "class_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            methods = []
            fields = []
            annotations = []
            
            # Extract annotations
            for child in node.children:
                if child.type == "modifiers":
                    for mod in child.children:
                        if mod.type == "annotation":
                            annotations.append(get_text(mod, source))
            
            # Extract methods and fields
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        method_name = get_text(child.child_by_field_name("name"), source)
                        params = get_text(child.child_by_field_name("parameters"), source)
                        return_type = None
                        for c in child.children:
                            if c.type == "type_identifier" or c.type == "void_type":
                                return_type = get_text(c, source)
                                break
                        methods.append({
                            "name": method_name,
                            "parameters": params,
                            "return_type": return_type
                        })
                    elif child.type == "field_declaration":
                        field_text = get_text(child, source)
                        fields.append(field_text)
            
            results["classes"].append({
                "name": name,
                "methods": methods,
                "fields": fields,
                "annotations": annotations
            })
        
        elif node.type == "interface_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        method_name = get_text(child.child_by_field_name("name"), source)
                        params = get_text(child.child_by_field_name("parameters"), source)
                        methods.append({"name": method_name, "parameters": params})
            results["interfaces"].append({"name": name, "methods": methods})
    
    return results


def extract_c_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract C definitions including functions, structs, and includes."""
    results: Dict[str, Any] = {
        "functions": [],
        "structs": [],
        "includes": [],
        "typedefs": []
    }
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    for node in walk(root):
        if node.type == "preproc_include":
            results["includes"].append(get_text(node, source))
        
        elif node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            if declarator:
                name_node = declarator.child_by_field_name("declarator")
                if name_node:
                    name = get_text(name_node, source)
                    params = get_text(declarator.child_by_field_name("parameters"), source)
                    results["functions"].append({"name": name, "parameters": params})
        
        elif node.type == "struct_specifier":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = get_text(name_node, source)
                results["structs"].append({"name": name})
        
        elif node.type == "type_definition":
            name = get_text(node.child_by_field_name("name"), source)
            results["typedefs"].append({"name": name})
    
    return results


def extract_cpp_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract C++ definitions including classes, functions, and includes."""
    results: Dict[str, Any] = {
        "classes": [],
        "functions": [],
        "includes": [],
        "namespaces": []
    }
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    for node in walk(root):
        if node.type == "preproc_include":
            results["includes"].append(get_text(node, source))
        
        elif node.type == "function_definition":
            declarator = node.child_by_field_name("declarator")
            if declarator:
                name_node = declarator.child_by_field_name("declarator")
                if name_node:
                    name = get_text(name_node, source)
                    params = get_text(declarator.child_by_field_name("parameters"), source)
                    results["functions"].append({"name": name, "parameters": params})
        
        elif node.type == "class_specifier":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = get_text(name_node, source)
                methods = []
                body = node.child_by_field_name("body")
                if body:
                    for child in body.children:
                        if child.type == "function_definition":
                            declarator = child.child_by_field_name("declarator")
                            if declarator:
                                method_name_node = declarator.child_by_field_name("declarator")
                                if method_name_node:
                                    method_name = get_text(method_name_node, source)
                                    params = get_text(declarator.child_by_field_name("parameters"), source)
                                    methods.append({"name": method_name, "parameters": params})
                results["classes"].append({"name": name, "methods": methods})
        
        elif node.type == "namespace_definition":
            name_node = node.child_by_field_name("name")
            if name_node:
                name = get_text(name_node, source)
                results["namespaces"].append({"name": name})
    
    return results


def extract_csharp_definitions(root: Node, source: str) -> Dict[str, Any]:
    """Extract C# definitions including classes, methods, interfaces, and attributes."""
    results: Dict[str, Any] = {
        "classes": [],
        "interfaces": [],
        "methods": [],
        "imports": [],
        "attributes": [],
        "properties": []
    }
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    for node in walk(root):
        if node.type == "using_directive":
            results["imports"].append(get_text(node, source))
        
        elif node.type == "class_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            methods = []
            properties = []
            attributes = []
            
            # Extract attributes
            for child in node.children:
                if child.type == "attribute_list":
                    attributes.append(get_text(child, source))
            
            # Extract methods and properties
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        method_name = get_text(child.child_by_field_name("name"), source)
                        params = get_text(child.child_by_field_name("parameter_list"), source)
                        return_type = None
                        for c in child.children:
                            if c.type == "predefined_type" or c.type == "identifier":
                                return_type = get_text(c, source)
                                break
                        methods.append({
                            "name": method_name,
                            "parameters": params,
                            "return_type": return_type
                        })
                    elif child.type == "property_declaration":
                        prop_name = get_text(child.child_by_field_name("name"), source)
                        properties.append({"name": prop_name})
            
            results["classes"].append({
                "name": name,
                "methods": methods,
                "properties": properties,
                "attributes": attributes
            })
        
        elif node.type == "interface_declaration":
            name = get_text(node.child_by_field_name("name"), source)
            methods = []
            body = node.child_by_field_name("body")
            if body:
                for child in body.children:
                    if child.type == "method_declaration":
                        method_name = get_text(child.child_by_field_name("name"), source)
                        params = get_text(child.child_by_field_name("parameter_list"), source)
                        methods.append({"name": method_name, "parameters": params})
            results["interfaces"].append({"name": name, "methods": methods})
    
    return results


def extract_asp_definitions(source: str) -> Dict[str, Any]:
    """Extract Classic ASP definitions using regex (no tree-sitter support)."""
    results: Dict[str, Any] = {
        "functions": [],
        "subroutines": [],
        "includes": []
    }
    
    # Extract function definitions
    function_pattern = r'Function\s+(\w+)\s*\([^)]*\)'
    for match in re.finditer(function_pattern, source, re.IGNORECASE):
        results["functions"].append({"name": match.group(1)})
    
    # Extract subroutine definitions
    sub_pattern = r'Sub\s+(\w+)\s*\([^)]*\)'
    for match in re.finditer(sub_pattern, source, re.IGNORECASE):
        results["subroutines"].append({"name": match.group(1)})
    
    # Extract includes
    include_pattern = r'<!--\s*#include\s+(?:file|virtual)=["\']([^"\']+)["\']\s*-->'
    for match in re.finditer(include_pattern, source, re.IGNORECASE):
        results["includes"].append(match.group(1))
    
    return results


def extract_code_patterns(root: Node, source: str, language: str) -> Dict[str, Any]:
    """
    Extract code patterns from source code including import style, export style,
    decorators, component type, lifecycle hooks, and state management.
    
    Args:
        root: Root AST node
        source: Source code string
        language: Programming language
        
    Returns:
        Dictionary with code patterns
    """
    patterns: Dict[str, Any] = {
        "importStyle": "mixed",
        "exportStyle": "mixed",
        "decorators": [],
        "componentType": None,
        "lifecycleHooks": [],
        "stateManagement": "none"
    }
    
    if not root:
        return patterns
    
    def walk(node: Node):
        yield node
        for child in node.children:
            yield from walk(child)
    
    imports = []
    exports = []
    decorators = []
    component_types = []
    lifecycle_hooks = []
    state_imports = []
    
    # Angular lifecycle hooks
    angular_hooks = ['ngoninit', 'ngondestroy', 'ngafterviewinit', 'ngafterviewchecked',
                     'ngaftercontentinit', 'ngaftercontentchecked', 'ngonchanges', 'ngdocheck']
    # React hooks
    react_hooks = ['usestate', 'useeffect', 'usecallback', 'usememo', 'useref', 'usecontext']
    # Vue hooks
    vue_hooks = ['onmounted', 'onunmounted', 'onupdated', 'onbeforemount', 'onbeforeunmount']
    
    source_lower = source.lower()
    
    for node in walk(root):
        # Extract imports
        if node.type in ("import_statement", "import_from_statement", "import_declaration", "using_directive"):
            import_text = get_text(node, source)
            if import_text:
                imports.append(import_text)
                # Check for state management imports
                import_lower = import_text.lower()
                if 'rxjs' in import_lower or 'observable' in import_lower:
                    state_imports.append('rxjs')
                elif 'redux' in import_lower or 'react-redux' in import_lower:
                    state_imports.append('redux')
                elif 'mobx' in import_lower:
                    state_imports.append('mobx')
        
        # Extract exports
        if node.type == "export_statement" or (node.type in ("class_declaration", "function_declaration") and 
                                                any(child.type == "export" for child in node.children)):
            export_text = get_text(node, source)
            if export_text:
                exports.append(export_text)
        
        # Extract decorators
        if node.type == "decorator":
            decorator_text = get_text(node, source)
            if decorator_text:
                # Extract decorator name (e.g., "@Component" -> "Component")
                decorator_clean = decorator_text.strip()
                if decorator_clean.startswith('@'):
                    decorator_name = decorator_clean[1:].split('(')[0].strip()
                    if decorator_name and decorator_name not in decorators:
                        decorators.append(decorator_name)
        
        # Extract component type
        if node.type == "class_declaration":
            class_text = get_text(node, source)
            if class_text:
                # Check if it extends React.Component
                if 'extends' in class_text.lower() and 'component' in class_text.lower():
                    component_types.append('class')
                elif 'class' in class_text.lower():
                    component_types.append('class')
        
        elif node.type == "function_declaration":
            func_text = get_text(node, source)
            if func_text and ('component' in func_text.lower() or 'react' in func_text.lower()):
                component_types.append('function')
        
        elif node.type == "arrow_function":
            # Check if arrow function is assigned to a component-like variable
            parent = node.parent
            if parent and parent.type == "variable_declarator":
                var_name = get_text(parent.child_by_field_name("name"), source)
                if var_name and (var_name[0].isupper() or 'component' in var_name.lower()):
                    component_types.append('arrow')
        
        # Extract lifecycle hooks
        if node.type in ("method_definition", "function_declaration", "call_expression"):
            node_text = get_text(node, source)
            if node_text:
                node_lower = node_text.lower()
                # Check for Angular hooks
                for hook in angular_hooks:
                    if hook in node_lower:
                        lifecycle_hooks.append(hook)
                # Check for React hooks
                for hook in react_hooks:
                    if hook in node_lower:
                        lifecycle_hooks.append(hook)
                # Check for Vue hooks
                for hook in vue_hooks:
                    if hook in node_lower:
                        lifecycle_hooks.append(hook)
    
    # Analyze import style
    absolute_count = 0
    relative_count = 0
    
    for imp in imports:
        imp_lower = imp.lower()
        # Check for relative imports (./ or ../)
        if re.search(r"from\s+['\"](\.\.?/|\.\.?\\\\)", imp) or re.search(r"import\s+['\"](\.\.?/|\.\.?\\\\)", imp):
            relative_count += 1
        # Check for absolute imports (no ./ or ../)
        elif re.search(r"from\s+['\"][^./]", imp) or re.search(r"import\s+['\"][^./]", imp):
            absolute_count += 1
    
    if absolute_count > 0 and relative_count > 0:
        patterns["importStyle"] = "mixed"
    elif absolute_count > 0:
        patterns["importStyle"] = "absolute"
    elif relative_count > 0:
        patterns["importStyle"] = "relative"
    
    # Analyze export style
    named_count = 0
    default_count = 0
    
    for exp in exports:
        exp_lower = exp.lower()
        if 'export default' in exp_lower:
            default_count += 1
        elif 'export' in exp_lower:
            named_count += 1
    
    if named_count > 0 and default_count > 0:
        patterns["exportStyle"] = "mixed"
    elif default_count > 0:
        patterns["exportStyle"] = "default"
    elif named_count > 0:
        patterns["exportStyle"] = "named"
    
    # Set decorators
    patterns["decorators"] = list(set(decorators))
    
    # Set component type (prefer first found, or most common)
    if component_types:
        # Count occurrences
        from collections import Counter
        type_counts = Counter(component_types)
        patterns["componentType"] = type_counts.most_common(1)[0][0]
    
    # Set lifecycle hooks (unique)
    patterns["lifecycleHooks"] = list(set(lifecycle_hooks))
    
    # Set state management
    if state_imports:
        from collections import Counter
        state_counts = Counter(state_imports)
        patterns["stateManagement"] = state_counts.most_common(1)[0][0]
    
    return patterns


def extract_definitions(file_path: str, source: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """
    Extract definitions from a file based on its language.
    
    Args:
        file_path: Path to the file
        source: Optional source code string (if None, will read from file)
        
    Returns:
        Dictionary with extracted definitions or None if not supported
    """
    language = detect_language(file_path)
    
    if not language:
        return None
    
    if source is None:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except FileNotFoundError:
            from code_parser.exceptions import ParseError
            raise ParseError(f"File not found: {file_path}", file_path=file_path)
        except (IOError, OSError) as e:
            from code_parser.exceptions import ParseError
            raise ParseError(f"Failed to read file: {e}", file_path=file_path)
    
    # Handle languages without tree-sitter support
    if language in ('asp', 'aspx'):
        return extract_asp_definitions(source)
    
    # Parse using tree-sitter
    root = parse_source(source, language)
    if not root:
        return None
    
    # Extract based on language
    definitions = None
    if language == 'python':
        definitions = extract_python_definitions(root, source)
    elif language == 'typescript':
        definitions = extract_ts_definitions(root, source)
    elif language == 'javascript':
        definitions = extract_js_definitions(root, source)
    elif language == 'java':
        definitions = extract_java_definitions(root, source)
    elif language == 'c':
        definitions = extract_c_definitions(root, source)
    elif language == 'cpp':
        definitions = extract_cpp_definitions(root, source)
    elif language == 'csharp':
        definitions = extract_csharp_definitions(root, source)
    
    if definitions is None:
        return None
    
    # Extract code patterns and add to definitions
    code_patterns = extract_code_patterns(root, source, language)
    definitions["codePatterns"] = code_patterns
    
    return definitions


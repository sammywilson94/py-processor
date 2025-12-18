"""Multi-language parser using tree-sitter for various programming languages."""

import os
import re
from typing import Optional, Tuple, Dict, Any
from tree_sitter import Language, Parser, Node
from code_parser.exceptions import ParseError
from code_parser.normalizer import get_text

try:
    import tree_sitter_python as tspython
    PY_LANGUAGE = Language(tspython.language())
    parser_py = Parser(PY_LANGUAGE)
except ImportError:
    PY_LANGUAGE = None
    parser_py = None

try:
    import tree_sitter_typescript as tstypescript
    TS_LANGUAGE = Language(tstypescript.language_typescript())
    parser_ts = Parser(TS_LANGUAGE)
except ImportError:
    TS_LANGUAGE = None
    parser_ts = None

try:
    import tree_sitter_javascript as tsjavascript
    JS_LANGUAGE = Language(tsjavascript.language())
    parser_js = Parser(JS_LANGUAGE)
except ImportError:
    JS_LANGUAGE = None
    parser_js = None

try:
    import tree_sitter_java as tsjava
    JAVA_LANGUAGE = Language(tsjava.language())
    parser_java = Parser(JAVA_LANGUAGE)
except ImportError:
    JAVA_LANGUAGE = None
    parser_java = None

try:
    import tree_sitter_c as tsc
    C_LANGUAGE = Language(tsc.language())
    parser_c = Parser(C_LANGUAGE)
except ImportError:
    C_LANGUAGE = None
    parser_c = None

try:
    import tree_sitter_cpp as tscpp
    CPP_LANGUAGE = Language(tscpp.language())
    parser_cpp = Parser(CPP_LANGUAGE)
except ImportError:
    CPP_LANGUAGE = None
    parser_cpp = None

try:
    import tree_sitter_c_sharp as tscsharp
    CSHARP_LANGUAGE = Language(tscsharp.language())
    parser_csharp = Parser(CSHARP_LANGUAGE)
except ImportError:
    CSHARP_LANGUAGE = None
    parser_csharp = None


def detect_language(file_path: str) -> Optional[str]:
    """
    Detect programming language from file extension.
    
    Args:
        file_path: Path to the file
        
    Returns:
        Language name or None if not supported
    """
    ext = os.path.splitext(file_path)[1].lower()
    
    language_map = {
        '.py': 'python',
        '.js': 'javascript',
        '.jsx': 'javascript',
        '.ts': 'typescript',
        '.tsx': 'typescript',
        '.java': 'java',
        '.c': 'c',
        '.cpp': 'cpp',
        '.cc': 'cpp',
        '.cxx': 'cpp',
        '.h': 'c',
        '.hpp': 'cpp',
        '.hxx': 'cpp',
        '.cs': 'csharp',
        '.asp': 'asp',
        '.aspx': 'aspx',
    }
    
    return language_map.get(ext)


def parse_file(file_path: str) -> Optional[Node]:
    """
    Parse a file using the appropriate tree-sitter parser.
    
    Args:
        file_path: Path to the file to parse
        
    Returns:
        Root node of the AST or None if parsing fails or language not supported
    """
    language = detect_language(file_path)
    
    if not language:
        return None
    
    try:
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            source = f.read()
    except FileNotFoundError:
        raise ParseError(f"File not found: {file_path}", file_path=file_path)
    except (IOError, OSError) as e:
        raise ParseError(f"Failed to read file: {e}", file_path=file_path)
    
    # Select parser based on language
    parser = None
    
    if language == 'python' and parser_py:
        parser = parser_py
    elif language == 'typescript' and parser_ts:
        parser = parser_ts
    elif language == 'javascript' and parser_js:
        parser = parser_js
    elif language == 'java' and parser_java:
        parser = parser_java
    elif language == 'c' and parser_c:
        parser = parser_c
    elif language in ('cpp', 'cxx', 'cc') and parser_cpp:
        parser = parser_cpp
    elif language == 'csharp' and parser_csharp:
        parser = parser_csharp
    elif language in ('asp', 'aspx'):
        # Classic ASP/ASPX - not supported by tree-sitter, return None
        # Will be handled by regex-based parser in normalizer
        return None
    
    if parser:
        try:
            tree = parser.parse(bytes(source, 'utf8'))
            return tree.root_node
        except Exception:
            return None
    
    return None


def parse_source(source: str, language: str) -> Optional[Node]:
    """
    Parse source code string directly.
    
    Args:
        source: Source code string
        language: Language name ('python', 'typescript', 'javascript', 'java', 'c', 'cpp', 'csharp')
        
    Returns:
        Root node of the AST or None if parsing fails
    """
    parser = None
    
    if language == 'python' and parser_py:
        parser = parser_py
    elif language == 'typescript' and parser_ts:
        parser = parser_ts
    elif language == 'javascript' and parser_js:
        parser = parser_js
    elif language == 'java' and parser_java:
        parser = parser_java
    elif language == 'c' and parser_c:
        parser = parser_c
    elif language == 'cpp' and parser_cpp:
        parser = parser_cpp
    elif language == 'csharp' and parser_csharp:
        parser = parser_csharp
    
    if parser:
        try:
            tree = parser.parse(bytes(source, 'utf8'))
            return tree.root_node
        except Exception:
            return None
    
    return None


def detect_module_framework(file_path: str, source: Optional[str] = None) -> Tuple[Optional[str], float]:
    """
    Detect framework for a specific module/file with confidence scoring.
    
    Analyzes file content (imports, decorators, syntax patterns) to determine
    the framework used in this specific file. Returns framework name and confidence
    score (0.0-1.0).
    
    Args:
        file_path: Path to the file
        source: Optional source code string (if None, will read from file)
        
    Returns:
        Tuple of (framework_name, confidence_score) where:
        - framework_name: Framework name (e.g., 'angular', 'react', 'vue', 'nestjs') or None
        - confidence_score: Confidence score between 0.0 and 1.0
    """
    if source is None:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except (FileNotFoundError, IOError, OSError):
            return None, 0.0
    
    if not source:
        return None, 0.0
    
    ext = os.path.splitext(file_path)[1].lower()
    source_lower = source.lower()
    framework_scores = {}
    
    # Parse AST for decorators/annotations
    root = None
    language = detect_language(file_path)
    if language:
        root = parse_source(source, language)
    
    # Helper function to walk AST
    def walk_ast(node):
        yield node
        for child in node.children:
            yield from walk_ast(child)
    
    # Angular detection
    angular_indicators = 0
    if '@component' in source_lower or '@ngmodule' in source_lower:
        angular_indicators += 2  # Strong indicator
    if '@injectable' in source_lower:
        angular_indicators += 1
    if '@input' in source_lower or '@output' in source_lower:
        angular_indicators += 1
    if re.search(r"import.*@angular/", source, re.IGNORECASE):
        angular_indicators += 2  # Strong indicator
    if re.search(r"from ['\"]@angular/", source, re.IGNORECASE):
        angular_indicators += 2
    if ext == '.ts' and 'component' in file_path.lower() and angular_indicators > 0:
        angular_indicators += 1
    
    # Check for Angular decorators in AST
    if root:
        for node in walk_ast(root):
            if node.type == "decorator":
                decorator_text = get_text(node, source)
                if decorator_text:
                    decorator_lower = decorator_text.lower()
                    if '@component' in decorator_lower or '@ngmodule' in decorator_lower:
                        angular_indicators += 2
                    elif '@injectable' in decorator_lower:
                        angular_indicators += 1
    
    if angular_indicators > 0:
        # Confidence: 0.5 base + 0.1 per indicator, capped at 0.98
        confidence = min(0.5 + (angular_indicators * 0.1), 0.98)
        framework_scores['angular'] = confidence
    
    # React detection
    react_indicators = 0
    if re.search(r"import.*from ['\"]react['\"]", source, re.IGNORECASE):
        react_indicators += 2  # Strong indicator
    if 'usestate' in source_lower or 'useeffect' in source_lower:
        react_indicators += 2
    if 'usecallback' in source_lower or 'usememo' in source_lower:
        react_indicators += 1
    if ext == '.tsx' or ext == '.jsx':
        react_indicators += 2  # Strong indicator
    if re.search(r"react\.(createelement|component)", source, re.IGNORECASE):
        react_indicators += 1
    if 'react.fc' in source_lower or 'react.functioncomponent' in source_lower:
        react_indicators += 1
    
    if react_indicators > 0:
        confidence = min(0.4 + (react_indicators * 0.12), 0.95)
        framework_scores['react'] = confidence
    
    # Vue detection
    vue_indicators = 0
    if ext == '.vue':
        vue_indicators += 3  # Very strong indicator
    if 'definecomponent' in source_lower:
        vue_indicators += 2
    if re.search(r"from ['\"]vue['\"]", source, re.IGNORECASE):
        vue_indicators += 2
    if '<template>' in source_lower and '<script' in source_lower:
        vue_indicators += 1
    if 'onmounted' in source_lower or 'onunmounted' in source_lower:
        vue_indicators += 1
    
    if vue_indicators > 0:
        confidence = min(0.6 + (vue_indicators * 0.1), 0.98)
        framework_scores['vue'] = confidence
    
    # NestJS detection
    nestjs_indicators = 0
    if '@controller' in source_lower:
        nestjs_indicators += 2
    if '@injectable' in source_lower and '@controller' not in source_lower:
        nestjs_indicators += 1
    if '@module' in source_lower:
        nestjs_indicators += 2
    if re.search(r"@nestjs/", source, re.IGNORECASE):
        nestjs_indicators += 2
    if re.search(r"import.*@nestjs/", source, re.IGNORECASE):
        nestjs_indicators += 2
    
    # Check for NestJS decorators in AST
    if root:
        for node in walk_ast(root):
            if node.type == "decorator":
                decorator_text = get_text(node, source)
                if decorator_text:
                    decorator_lower = decorator_text.lower()
                    if '@controller' in decorator_lower:
                        nestjs_indicators += 2
                    elif '@module' in decorator_lower:
                        nestjs_indicators += 2
                    elif '@injectable' in decorator_lower:
                        nestjs_indicators += 1
    
    if nestjs_indicators > 0:
        confidence = min(0.5 + (nestjs_indicators * 0.1), 0.98)
        framework_scores['nestjs'] = confidence
    
    # Next.js detection (subset of React)
    nextjs_indicators = 0
    if 'next/router' in source_lower or 'next/link' in source_lower:
        nextjs_indicators += 2
    if 'next/navigation' in source_lower:
        nextjs_indicators += 2
    if 'userouter' in source_lower and 'next' in source_lower:
        nextjs_indicators += 1
    
    if nextjs_indicators > 0:
        confidence = min(0.5 + (nextjs_indicators * 0.15), 0.95)
        framework_scores['nextjs'] = confidence
    
    # Flask detection
    flask_indicators = 0
    if re.search(r"from flask import", source, re.IGNORECASE):
        flask_indicators += 2
    if re.search(r"@app\.route\(", source, re.IGNORECASE):
        flask_indicators += 2
    if 'flask(' in source_lower or 'flask import' in source_lower:
        flask_indicators += 1
    
    if flask_indicators > 0:
        confidence = min(0.5 + (flask_indicators * 0.15), 0.95)
        framework_scores['flask'] = confidence
    
    # FastAPI detection
    fastapi_indicators = 0
    if re.search(r"from fastapi import", source, re.IGNORECASE):
        fastapi_indicators += 2
    if re.search(r"@app\.(get|post|put|delete)\(", source, re.IGNORECASE):
        fastapi_indicators += 2
    if re.search(r"@router\.(get|post|put|delete)\(", source, re.IGNORECASE):
        fastapi_indicators += 2
    
    if fastapi_indicators > 0:
        confidence = min(0.5 + (fastapi_indicators * 0.15), 0.95)
        framework_scores['fastapi'] = confidence
    
    # Spring Boot detection
    spring_indicators = 0
    if '@restcontroller' in source_lower or '@controller' in source_lower:
        spring_indicators += 2
    if '@service' in source_lower:
        spring_indicators += 1
    if '@repository' in source_lower:
        spring_indicators += 1
    if re.search(r"import org\.springframework", source, re.IGNORECASE):
        spring_indicators += 2
    
    if spring_indicators > 0:
        confidence = min(0.5 + (spring_indicators * 0.12), 0.95)
        framework_scores['spring-boot'] = confidence
    
    # Return framework with highest confidence if above threshold
    if framework_scores:
        best_framework = max(framework_scores.items(), key=lambda x: x[1])
        if best_framework[1] >= 0.3:  # Minimum confidence threshold
            return best_framework[0], best_framework[1]
    
    return None, 0.0


def extract_ui_patterns(file_path: str, source: Optional[str] = None) -> Dict[str, Any]:
    """
    Extract UI patterns from template files (JSX/TSX/HTML).
    
    Extracts button patterns, navigation patterns, and form patterns
    from template files to enable accurate code editing.
    
    Args:
        file_path: Path to the template file
        source: Optional source code string (if None, will read from file)
        
    Returns:
        Dictionary with UI elements patterns
    """
    if source is None:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except (FileNotFoundError, IOError, OSError):
            return {"buttons": [], "navigation": {}, "forms": []}
    
    if not source:
        return {"buttons": [], "navigation": {}, "forms": []}
    
    ext = os.path.splitext(file_path)[1].lower()
    ui_elements: Dict[str, Any] = {
        "buttons": [],
        "navigation": {},
        "forms": []
    }
    
    source_lower = source.lower()
    
    # Extract button patterns
    # Angular Material buttons
    mat_button_pattern = r'<button[^>]*mat-button[^>]*>'
    for match in re.finditer(mat_button_pattern, source, re.IGNORECASE):
        button_text = match.group(0)
        ui_elements["buttons"].append({
            "type": "mat-button",
            "pattern": button_text[:100],  # Limit pattern length
            "import": "@angular/material/button"
        })
    
    # Angular Material raised buttons
    mat_raised_pattern = r'<button[^>]*mat-raised-button[^>]*>'
    for match in re.finditer(mat_raised_pattern, source, re.IGNORECASE):
        button_text = match.group(0)
        ui_elements["buttons"].append({
            "type": "mat-raised-button",
            "pattern": button_text[:100],
            "import": "@angular/material/button"
        })
    
    # React Button components
    react_button_pattern = r'<Button[^>]*>'
    for match in re.finditer(react_button_pattern, source, re.IGNORECASE):
        button_text = match.group(0)
        # Try to detect which library (Material-UI, Ant Design, etc.)
        import_lib = "@mui/material"  # Default
        if 'antd' in source_lower or 'ant-design' in source_lower:
            import_lib = "antd"
        elif 'chakra' in source_lower:
            import_lib = "@chakra-ui/react"
        ui_elements["buttons"].append({
            "type": "Button",
            "pattern": button_text[:100],
            "import": import_lib
        })
    
    # Generic button with onClick (React)
    if ext in ('.tsx', '.jsx'):
        onClick_button_pattern = r'<button[^>]*onClick\s*=\s*\{[^}]*\}[^>]*>'
        for match in re.finditer(onClick_button_pattern, source, re.IGNORECASE):
            button_text = match.group(0)
            ui_elements["buttons"].append({
                "type": "button",
                "pattern": button_text[:100],
                "import": None  # Native HTML button
            })
    
    # Extract navigation patterns
    # Angular router.navigate
    router_navigate_pattern = r'this\.router\.navigate\s*\(\s*\[[^\]]+\]\s*\)'
    for match in re.finditer(router_navigate_pattern, source, re.IGNORECASE):
        nav_text = match.group(0)
        ui_elements["navigation"] = {
            "pattern": nav_text[:150],
            "import": "@angular/router"
        }
        break  # Take first match
    
    # Angular routerLink
    router_link_pattern = r'routerLink\s*=\s*["\'][^"\']+["\']'
    for match in re.finditer(router_link_pattern, source, re.IGNORECASE):
        nav_text = match.group(0)
        if not ui_elements["navigation"]:
            ui_elements["navigation"] = {
                "pattern": nav_text[:150],
                "import": "@angular/router"
            }
        break
    
    # React useNavigate
    if 'usenavigate' in source_lower:
        navigate_match = re.search(r'const\s+\w+\s*=\s*useNavigate\s*\(\)', source, re.IGNORECASE)
        if navigate_match:
            ui_elements["navigation"] = {
                "pattern": "useNavigate()",
                "import": "react-router-dom"
            }
    
    # React Link component
    react_link_pattern = r'<Link[^>]*to\s*=\s*["\'][^"\']+["\']'
    for match in re.finditer(react_link_pattern, source, re.IGNORECASE):
        nav_text = match.group(0)
        if not ui_elements["navigation"]:
            ui_elements["navigation"] = {
                "pattern": nav_text[:150],
                "import": "react-router-dom"
            }
        break
    
    # Next.js router
    if 'next/router' in source_lower or 'next/navigation' in source_lower:
        next_router_match = re.search(r'router\.(push|replace)\s*\(', source, re.IGNORECASE)
        if next_router_match:
            ui_elements["navigation"] = {
                "pattern": f"router.{next_router_match.group(1)}()",
                "import": "next/router" if 'next/router' in source_lower else "next/navigation"
            }
    
    # Extract form patterns
    # Angular reactive forms
    form_group_pattern = r'\[formGroup\]\s*=\s*["\'][^"\']+["\']'
    for match in re.finditer(form_group_pattern, source, re.IGNORECASE):
        form_text = match.group(0)
        ui_elements["forms"].append({
            "type": "reactive",
            "pattern": form_text[:100],
            "import": "@angular/forms"
        })
        break
    
    # Angular template-driven forms
    ng_model_pattern = r'\[\(ngModel\)\]\s*=\s*["\'][^"\']+["\']'
    for match in re.finditer(ng_model_pattern, source, re.IGNORECASE):
        form_text = match.group(0)
        ui_elements["forms"].append({
            "type": "template-driven",
            "pattern": form_text[:100],
            "import": "@angular/forms"
        })
        break
    
    # React forms
    if ext in ('.tsx', '.jsx'):
        react_form_pattern = r'<form[^>]*onSubmit\s*=\s*\{[^}]*\}[^>]*>'
        for match in re.finditer(react_form_pattern, source, re.IGNORECASE):
            form_text = match.group(0)
            ui_elements["forms"].append({
                "type": "react",
                "pattern": form_text[:100],
                "import": None  # Native form
            })
            break
    
    # Remove duplicates from buttons
    seen_buttons = set()
    unique_buttons = []
    for button in ui_elements["buttons"]:
        button_key = (button.get("type"), button.get("pattern"))
        if button_key not in seen_buttons:
            seen_buttons.add(button_key)
            unique_buttons.append(button)
    ui_elements["buttons"] = unique_buttons
    
    return ui_elements


def analyze_file_structure(file_path: str, source: Optional[str] = None) -> Dict[str, Any]:
    """
    Analyze file structure to detect separate template and style files.
    
    Checks for:
    - Separate template file (.html for Angular)
    - Separate styles file (.css, .scss, .less)
    - Angular standalone components
    
    Args:
        file_path: Path to the component file
        source: Optional source code string (if None, will read from file)
        
    Returns:
        Dictionary with file structure information
    """
    file_structure: Dict[str, Any] = {
        "hasTemplate": False,
        "templatePath": None,
        "hasStyles": False,
        "stylesPath": None,
        "isStandalone": False
    }
    
    if source is None:
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                source = f.read()
        except (FileNotFoundError, IOError, OSError):
            return file_structure
    
    if not source:
        return file_structure
    
    import os
    from pathlib import Path
    
    file_dir = os.path.dirname(file_path)
    file_base = os.path.splitext(os.path.basename(file_path))[0]
    
    # Check for Angular standalone component
    if '@component' in source.lower():
        # Check for standalone: true in decorator
        standalone_pattern = r'standalone\s*:\s*true'
        if re.search(standalone_pattern, source, re.IGNORECASE):
            file_structure["isStandalone"] = True
    
    # Check for separate template file (Angular)
    # Common patterns: component.html, component.template.html
    template_extensions = ['.html', '.template.html']
    for ext in template_extensions:
        template_path = os.path.join(file_dir, f"{file_base}{ext}")
        if os.path.exists(template_path):
            rel_path = os.path.relpath(template_path, os.path.dirname(file_path))
            file_structure["hasTemplate"] = True
            file_structure["templatePath"] = rel_path.replace(os.sep, '/')
            break
    
    # Also check for templateUrl in decorator
    templateUrl_pattern = r'templateUrl\s*:\s*["\']([^"\']+)["\']'
    match = re.search(templateUrl_pattern, source, re.IGNORECASE)
    if match:
        template_url = match.group(1)
        # Resolve relative path
        if template_url.startswith('./') or template_url.startswith('../'):
            template_path = os.path.normpath(os.path.join(file_dir, template_url))
            if os.path.exists(template_path):
                rel_path = os.path.relpath(template_path, os.path.dirname(file_path))
                file_structure["hasTemplate"] = True
                file_structure["templatePath"] = rel_path.replace(os.sep, '/')
    
    # Check for separate styles file
    style_extensions = ['.css', '.scss', '.less', '.sass']
    for ext in style_extensions:
        style_path = os.path.join(file_dir, f"{file_base}{ext}")
        if os.path.exists(style_path):
            rel_path = os.path.relpath(style_path, os.path.dirname(file_path))
            file_structure["hasStyles"] = True
            file_structure["stylesPath"] = rel_path.replace(os.sep, '/')
            break
    
    # Also check for styleUrls in decorator
    styleUrls_pattern = r'styleUrls\s*:\s*\[([^\]]+)\]'
    match = re.search(styleUrls_pattern, source, re.IGNORECASE)
    if match:
        styles_array = match.group(1)
        # Extract first style URL
        style_url_match = re.search(r'["\']([^"\']+)["\']', styles_array)
        if style_url_match:
            style_url = style_url_match.group(1)
            if style_url.startswith('./') or style_url.startswith('../'):
                style_path = os.path.normpath(os.path.join(file_dir, style_url))
                if os.path.exists(style_path):
                    rel_path = os.path.relpath(style_path, os.path.dirname(file_path))
                    file_structure["hasStyles"] = True
                    file_structure["stylesPath"] = rel_path.replace(os.sep, '/')
    
    return file_structure


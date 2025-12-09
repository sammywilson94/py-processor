"""Planner - Generates step-by-step code change plans using LLM."""

import logging
import os
import uuid
from typing import Dict, Any, List, Optional
from langchain_openai import ChatOpenAI

logger = logging.getLogger(__name__)


class Planner:
    """Generates structured code change plans using LLM."""
    
    def __init__(self):
        """Initialize the planner."""
        self.llm = None
        self._init_llm()
    
    def _init_llm(self) -> None:
        """Initialize LLM for planning."""
        try:
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, planning will be limited")
                return
            
            model = os.getenv("LLM_MODEL", "gpt-4")
            temperature = float(os.getenv("LLM_TEMPERATURE", "0.3"))
            max_tokens = int(os.getenv("LLM_MAX_TOKENS", "2000"))
            
            self.llm = ChatOpenAI(
                model=model,
                temperature=temperature,
                max_tokens=max_tokens,
                openai_api_key=api_key
            )
        except Exception as e:
            logger.error(f"Failed to initialize LLM: {e}", exc_info=True)
            self.llm = None
    
    def generate_plan(
        self,
        intent: Dict[str, Any],
        impact_result: Dict[str, Any],
        constraints: List[str],
        pkg_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Generate a step-by-step code change plan.
        
        Args:
            intent: Intent dictionary
            impact_result: Impact analysis result
            constraints: List of constraints
            pkg_data: Optional PKG data dictionary for context-aware planning
            
        Returns:
            Plan dictionary with tasks
        """
        if not self.llm:
            return self._fallback_plan(intent, impact_result, constraints)
        
        try:
            return self._call_llm(intent, impact_result, constraints, pkg_data)
        except Exception as e:
            logger.error(f"LLM planning failed: {e}", exc_info=True)
            return self._fallback_plan(intent, impact_result, constraints)
    
    def _call_llm(
        self,
        intent: Dict[str, Any],
        impact_result: Dict[str, Any],
        constraints: List[str],
        pkg_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Call LLM to generate plan.
        
        Args:
            intent: Intent dictionary
            impact_result: Impact analysis result
            constraints: List of constraints
            pkg_data: Optional PKG data dictionary for context-aware planning
            
        Returns:
            Plan dictionary
        """
        # Prepare module summaries for context
        impacted_modules = impact_result.get('impacted_modules', [])
        module_summaries = []
        
        for module in impacted_modules[:10]:  # Limit to first 10 for context
            module_info = {
                "id": module.get('id'),
                "path": module.get('path'),
                "summary": module.get('moduleSummary', ''),
                "kind": module.get('kind', [])
            }
            module_summaries.append(module_info)
        
        # Extract PKG context if available
        pkg_context = ""
        if pkg_data:
            try:
                from services.pkg_query_engine import PKGQueryEngine
                from agents.code_context_analyzer import CodeContextAnalyzer
                
                query_engine = PKGQueryEngine(pkg_data)
                context_analyzer = CodeContextAnalyzer(pkg_data, query_engine)
                
                # Extract framework patterns from project
                project = pkg_data.get('project', {})
                framework_type = project.get('framework', 'unknown')
                languages = project.get('languages', [])
                
                # Get framework patterns from impacted modules
                framework_patterns = []
                import_patterns = []
                code_conventions = []
                
                for module in impacted_modules[:5]:  # Limit to first 5 for context
                    module_id = module.get('id')
                    if module_id:
                        try:
                            patterns = context_analyzer.extract_code_patterns(module_id)
                            if patterns.get('framework_type'):
                                framework_type = patterns.get('framework_type')
                            if patterns.get('patterns'):
                                framework_patterns.extend(patterns.get('patterns', [])[:3])
                            if patterns.get('style', {}).get('import_style'):
                                import_patterns.append(patterns['style']['import_style'])
                            if patterns.get('style', {}).get('naming_convention'):
                                code_conventions.append(patterns['style']['naming_convention'])
                        except Exception as e:
                            logger.debug(f"Failed to extract patterns for module {module_id}: {e}")
                
                # Build PKG context string
                pkg_context_parts = []
                if framework_type and framework_type != 'unknown':
                    pkg_context_parts.append(f"Framework: {framework_type}")
                if languages:
                    pkg_context_parts.append(f"Languages: {', '.join(languages)}")
                if framework_patterns:
                    unique_patterns = list(set(framework_patterns))[:5]
                    pkg_context_parts.append(f"Code Patterns: {', '.join(unique_patterns)}")
                if import_patterns:
                    unique_imports = list(set(import_patterns))[:3]
                    pkg_context_parts.append(f"Import Style: {', '.join(unique_imports)}")
                if code_conventions:
                    unique_conventions = list(set(code_conventions))[:3]
                    pkg_context_parts.append(f"Naming Conventions: {', '.join(unique_conventions)}")
                
                if pkg_context_parts:
                    pkg_context = "\n\nProject Context (from knowledge graph):\n" + "\n".join(f"- {part}" for part in pkg_context_parts) + "\n"
                    pkg_context += "\nIMPORTANT: Follow the project's framework patterns, import styles, and naming conventions shown above when planning changes.\n"
                
            except Exception as e:
                logger.warning(f"Failed to extract PKG context for planning: {e}", exc_info=True)
                # Continue without PKG context if extraction fails
        
        prompt = f"""You are a code-change planner. Given the following information, produce a detailed, step-by-step plan for implementing the requested changes.

Intent: {intent.get('description', '')}
Intent Type: {intent.get('intent', 'unknown')}
Risk Level: {impact_result.get('risk_score', 'medium')}

Impacted Modules ({len(impacted_modules)} total):
{self._format_modules_for_prompt(module_summaries)}

Impacted Files: {len(impact_result.get('impacted_files', []))} files
Affected Tests: {len(impact_result.get('affected_tests', []))} test files

Constraints:
{chr(10).join(f"- {c}" for c in constraints) if constraints else "- None specified"}
{pkg_context}

Produce a numbered plan of code edits with:
1. Files to modify (relative path from repo root)
2. Specific changes (add field, update method signature, call new function, etc.)
3. Tests to add/change (file path + test name/description)
4. Migration steps if database changes are required
5. CI changes if needed

For each task, provide:
- task: Clear description of what to do
- files: Array of file paths to modify
- changes: Array of specific change descriptions
- tests: Array of test files and test descriptions
- notes: Any important notes (migrations, breaking changes, etc.)
- estimated_time: Rough time estimate (e.g., "15min", "1h")

Return a JSON object with this structure:
{{
  "tasks": [
    {{
      "task": "Description of task",
      "files": ["path/to/file1.py", "path/to/file2.ts"],
      "changes": ["Add field X to class Y", "Update method Z to handle new case"],
      "tests": ["tests/test_file1.py - test_new_functionality"],
      "notes": "Migration required: add column to database",
      "estimated_time": "30min"
    }}
  ],
  "total_estimated_time": "2h",
  "migration_required": false
}}

Be specific, actionable, and consider the constraints. Order tasks logically (dependencies first)."""

        try:
            response = self.llm.invoke(prompt)
            content = response.content if hasattr(response, 'content') else str(response)
            
            # Parse JSON from response
            import json
            import re
            
            # Extract JSON from response
            json_match = re.search(r'\{.*\}', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(0)
                plan_dict = json.loads(json_str)
            else:
                # Fallback parsing
                plan_dict = self._parse_plan_from_text(content)
            
            # Normalize plan
            plan_dict = self._normalize_plan(plan_dict, intent, impact_result)
            
            return plan_dict
        
        except Exception as e:
            logger.error(f"Error parsing LLM response: {e}", exc_info=True)
            return self._fallback_plan(intent, impact_result, constraints)
    
    def _format_modules_for_prompt(self, modules: List[Dict[str, Any]]) -> str:
        """Format modules for prompt."""
        lines = []
        for i, module in enumerate(modules, 1):
            path = module.get('path', 'unknown')
            summary = module.get('summary', 'No summary')
            kind = ', '.join(module.get('kind', []))
            lines.append(f"{i}. {path} ({kind})")
            if summary:
                lines.append(f"   Summary: {summary[:100]}")
        return '\n'.join(lines) if lines else "No modules found"
    
    def _parse_plan_from_text(self, text: str) -> Dict[str, Any]:
        """Fallback parser for plan text."""
        tasks = []
        lines = text.split('\n')
        current_task = None
        
        for line in lines:
            line = line.strip()
            if not line:
                continue
            
            # Detect task start
            if line.startswith(('1.', '2.', '3.', '4.', '5.', '6.', '7.', '8.', '9.')):
                if current_task:
                    tasks.append(current_task)
                current_task = {
                    "task": line[2:].strip(),
                    "files": [],
                    "changes": [],
                    "tests": [],
                    "notes": "",
                    "estimated_time": "30min"
                }
            elif current_task:
                if 'file' in line.lower() or '.py' in line or '.ts' in line:
                    # Extract file path
                    import re
                    file_match = re.search(r'[\w/]+\.(py|ts|js|java|cs)', line)
                    if file_match:
                        current_task["files"].append(file_match.group(0))
                elif 'change' in line.lower() or 'add' in line.lower() or 'update' in line.lower():
                    current_task["changes"].append(line)
                elif 'test' in line.lower():
                    current_task["tests"].append(line)
        
        if current_task:
            tasks.append(current_task)
        
        return {
            "tasks": tasks,
            "total_estimated_time": f"{len(tasks) * 30}min",
            "migration_required": False
        }
    
    def _normalize_plan(
        self,
        plan_dict: Dict[str, Any],
        intent: Dict[str, Any],
        impact_result: Dict[str, Any]
    ) -> Dict[str, Any]:
        """Normalize plan dictionary."""
        # Ensure tasks is a list
        tasks = plan_dict.get('tasks', [])
        if not isinstance(tasks, list):
            tasks = []
        
        # Normalize each task
        normalized_tasks = []
        for i, task in enumerate(tasks, 1):
            if not isinstance(task, dict):
                continue
            
            normalized_task = {
                "task_id": i,
                "task": task.get('task', f'Task {i}'),
                "files": task.get('files', []) if isinstance(task.get('files'), list) else [],
                "changes": task.get('changes', []) if isinstance(task.get('changes'), list) else [],
                "tests": task.get('tests', []) if isinstance(task.get('tests'), list) else [],
                "notes": task.get('notes', ''),
                "estimated_time": task.get('estimated_time', '30min')
            }
            normalized_tasks.append(normalized_task)
        
        # Check for migration requirement
        migration_required = plan_dict.get('migration_required', False)
        if not migration_required:
            # Check tasks for migration hints
            for task in normalized_tasks:
                notes = task.get('notes', '').lower()
                if 'migration' in notes or 'database' in notes or 'schema' in notes:
                    migration_required = True
                    break
        
        return {
            "plan_id": str(uuid.uuid4()),
            "tasks": normalized_tasks,
            "total_estimated_time": plan_dict.get('total_estimated_time', f"{len(normalized_tasks) * 30}min"),
            "migration_required": migration_required,
            "intent": intent,
            "impact_summary": {
                "file_count": impact_result.get('file_count', 0),
                "module_count": impact_result.get('module_count', 0),
                "risk_score": impact_result.get('risk_score', 'medium')
            }
        }
    
    def _fallback_plan(
        self,
        intent: Dict[str, Any],
        impact_result: Dict[str, Any],
        constraints: List[str]
    ) -> Dict[str, Any]:
        """Generate a basic fallback plan."""
        impacted_files = impact_result.get('impacted_files', [])[:5]  # Limit to 5 files
        
        tasks = []
        for i, file_path in enumerate(impacted_files, 1):
            tasks.append({
                "task_id": i,
                "task": f"Modify {file_path.split('/')[-1]}",
                "files": [file_path],
                "changes": [f"Apply changes as per intent: {intent.get('description', '')}"],
                "tests": [],
                "notes": "",
                "estimated_time": "30min"
            })
        
        return {
            "plan_id": str(uuid.uuid4()),
            "tasks": tasks,
            "total_estimated_time": f"{len(tasks) * 30}min",
            "migration_required": False,
            "intent": intent,
            "impact_summary": {
                "file_count": len(impacted_files),
                "module_count": len(impact_result.get('impacted_modules', [])),
                "risk_score": impact_result.get('risk_score', 'medium')
            }
        }

"""Code Edit Executor - Applies code changes to repository."""

import logging
import os
import subprocess
from typing import Dict, Any, List, Optional
from git import Repo, InvalidGitRepositoryError
from git.exc import GitCommandError

logger = logging.getLogger(__name__)


class CodeEditExecutor:
    """Executes code edits on a repository."""
    
    def __init__(self, repo_path: str):
        """
        Initialize code editor.
        
        Args:
            repo_path: Path to repository
        """
        self.repo_path = os.path.abspath(repo_path)
        self.repo = None
        self.current_branch = None
        
        try:
            self.repo = Repo(self.repo_path)
        except InvalidGitRepositoryError:
            logger.warning(f"Not a git repository: {repo_path}")
            self.repo = None
    
    def create_branch(self, branch_name: str) -> str:
        """
        Create a new git branch.
        
        Args:
            branch_name: Name of branch to create
            
        Returns:
            Branch name
        """
        if not self.repo:
            logger.warning("Not a git repository, skipping branch creation")
            return branch_name
        
        try:
            # Check if branch already exists
            if branch_name in [ref.name.split('/')[-1] for ref in self.repo.heads]:
                logger.info(f"Branch {branch_name} already exists, checking it out")
                self.repo.git.checkout(branch_name)
            else:
                # Create and checkout new branch
                self.repo.git.checkout('-b', branch_name)
                logger.info(f"Created and checked out branch: {branch_name}")
            
            self.current_branch = branch_name
            return branch_name
        
        except GitCommandError as e:
            logger.error(f"Error creating branch: {e}", exc_info=True)
            raise
    
    def apply_edits(self, plan: Dict[str, Any], pkg_data: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """
        Apply code edits from plan.
        
        Args:
            plan: Plan dictionary with tasks
            pkg_data: Optional PKG data dictionary for context-aware editing
            
        Returns:
            Dictionary with edit results
        """
        tasks = plan.get('tasks', [])
        changes = []
        errors = []
        validation_results = []
        
        for task in tasks:
            task_id = task.get('task_id', 0)
            files = task.get('files', [])
            change_descriptions = task.get('changes', [])
            
            for file_path in files:
                try:
                    # Resolve full file path
                    full_path = os.path.join(self.repo_path, file_path)
                    
                    if not os.path.exists(full_path):
                        logger.warning(f"File not found: {full_path}")
                        errors.append({
                            "file": file_path,
                            "error": "File not found",
                            "task_id": task_id
                        })
                        continue
                    
                    # Apply edits with PKG context
                    edit_result = self._edit_file(full_path, change_descriptions, task, pkg_data)
                    
                    if edit_result['success']:
                        changes.append({
                            "file": file_path,
                            "status": "modified",
                            "diff": edit_result.get('diff', ''),
                            "task_id": task_id
                        })
                        
                        # Collect validation result
                        if edit_result.get('validation'):
                            validation_results.append({
                                "file": file_path,
                                "validation": edit_result['validation'],
                                "task_id": task_id
                            })
                    else:
                        errors.append({
                            "file": file_path,
                            "error": edit_result.get('error', 'Unknown error'),
                            "task_id": task_id,
                            "validation": edit_result.get('validation')
                        })
                
                except Exception as e:
                    logger.error(f"Error editing file {file_path}: {e}", exc_info=True)
                    errors.append({
                        "file": file_path,
                        "error": str(e),
                        "task_id": task_id
                    })
        
        return {
            "changes": changes,
            "errors": errors,
            "validation_results": validation_results,
            "total_files": len(changes),
            "success": len(errors) == 0
        }
    
    def _edit_file(
        self,
        file_path: str,
        change_descriptions: List[str],
        task: Dict[str, Any],
        pkg_data: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """
        Edit a file based on change descriptions.
        
        Args:
            file_path: Full path to file
            change_descriptions: List of change descriptions
            task: Task dictionary
            pkg_data: Optional PKG data dictionary for context-aware editing
            
        Returns:
            Dictionary with success status and diff
        """
        try:
            # Read original file
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                original_content = f.read()
            
            # Use LLM-based editing with PKG context
            modified_content = self._apply_llm_edit(
                file_path,
                original_content,
                change_descriptions,
                task,
                pkg_data
            )
            
            if modified_content == original_content:
                # No changes made
                return {
                    "success": False,
                    "error": "No changes applied",
                    "diff": ""
                }
            
            # Validate code before writing
            validation_result = None
            try:
                from agents.code_validator import CodeValidator
                validator = CodeValidator(self.repo_path)
                validation_result = validator.validate_all(file_path, modified_content, pkg_data)
                
                if not validation_result['valid']:
                    return {
                        "success": False,
                        "error": f"Validation failed: {'; '.join(validation_result['errors'])}",
                        "diff": "",
                        "validation": validation_result
                    }
                
                # Log warnings if any
                if validation_result.get('warnings'):
                    logger.warning(f"Code validation warnings for {file_path}: {validation_result['warnings']}")
            except Exception as e:
                logger.warning(f"Code validation error: {e}", exc_info=True)
                # Continue even if validation fails (non-blocking)
                # Create a default validation result for error case
                validation_result = {
                    "valid": True,  # Don't block on validation errors
                    "errors": [],
                    "warnings": [f"Validation check failed: {str(e)}"]
                }
            
            # Write modified content
            with open(file_path, 'w', encoding='utf-8') as f:
                f.write(modified_content)
            
            # Generate diff
            diff = self._generate_file_diff(original_content, modified_content, file_path)
            
            return {
                "success": True,
                "diff": diff,
                "modified": True,
                "validation": validation_result or {
                    "valid": True,
                    "errors": [],
                    "warnings": []
                }
            }
        
        except Exception as e:
            logger.error(f"Error editing file: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "diff": ""
            }
    
    def _apply_llm_edit(
        self,
        file_path: str,
        original_content: str,
        change_descriptions: List[str],
        task: Dict[str, Any],
        pkg_data: Optional[Dict[str, Any]] = None
    ) -> str:
        """
        Apply edits using LLM with rich PKG context.
        
        Args:
            file_path: File path
            original_content: Original file content
            change_descriptions: List of change descriptions
            task: Task dictionary
            pkg_data: Optional PKG data dictionary for context-aware editing
            
        Returns:
            Modified file content
        """
        try:
            from langchain_openai import ChatOpenAI
            import os
            
            api_key = os.getenv("OPENAI_API_KEY")
            if not api_key:
                logger.warning("OPENAI_API_KEY not set, skipping LLM edit")
                return original_content
            
            llm = ChatOpenAI(
                model=os.getenv("LLM_MODEL", "gpt-4"),
                temperature=0.1,
                openai_api_key=api_key
            )
            
            # Build rich context from PKG if available
            context_info = ""
            if pkg_data:
                try:
                    from agents.code_context_analyzer import CodeContextAnalyzer
                    from services.pkg_query_engine import PKGQueryEngine
                    
                    query_engine = PKGQueryEngine(pkg_data)
                    context_analyzer = CodeContextAnalyzer(pkg_data, query_engine)
                    
                    # Find module in PKG by file path
                    # Convert file_path to relative path from repo root
                    rel_path = os.path.relpath(file_path, self.repo_path) if os.path.isabs(file_path) else file_path
                    # Normalize path separators (handle both Windows and Unix)
                    rel_path_normalized = rel_path.replace('\\', '/')
                    
                    # Try to find module by path with multiple matching strategies
                    module = None
                    module_id = None
                    
                    # Strategy 1: Exact match with normalized path
                    for mod in pkg_data.get('modules', []):
                        mod_path = mod.get('path', '')
                        mod_path_normalized = mod_path.replace('\\', '/')
                        if mod_path_normalized == rel_path_normalized or mod_path == rel_path:
                            module = mod
                            break
                    
                    # Strategy 2: Match by filename if exact path not found
                    if not module:
                        filename = os.path.basename(rel_path)
                        for mod in pkg_data.get('modules', []):
                            mod_path = mod.get('path', '')
                            if os.path.basename(mod_path) == filename:
                                module = mod
                                logger.debug(f"Found module by filename match: {mod_path} for {rel_path}")
                                break
                    
                    if module:
                        module_id = module.get('id')
                        if not module_id:
                            logger.warning(f"Module found but missing ID for path: {rel_path}")
                            context = {}
                        else:
                            intent = task.get('intent', {})
                            try:
                                context = context_analyzer.build_code_generation_context(module_id, intent)
                            except Exception as e:
                                logger.warning(f"Failed to build code generation context for module {module_id}: {e}", exc_info=True)
                                context = {}
                        
                        # Build context string for prompt
                        context_parts = []
                        
                        if context.get('framework'):
                            context_parts.append(f"- Framework: {context['framework']}")
                        
                        if context.get('patterns', {}).get('patterns'):
                            patterns_str = ', '.join(context['patterns']['patterns'][:5])
                            context_parts.append(f"- Code patterns: {patterns_str}")
                        
                        if context.get('related_modules'):
                            related_paths = [m.get('path', '') for m in context['related_modules'][:3]]
                            if related_paths:
                                context_parts.append(f"- Related modules: {', '.join(related_paths)}")
                        
                        if context.get('import_patterns', {}).get('direct_imports'):
                            imports_str = ', '.join(context['import_patterns']['direct_imports'][:5])
                            context_parts.append(f"- Import patterns: {imports_str}")
                        
                        if context.get('code_style', {}).get('naming_convention'):
                            context_parts.append(f"- Naming convention: {context['code_style']['naming_convention']}")
                        
                        if context.get('type_information'):
                            type_info_str = ', '.join([
                                f"{name}: {info.get('signature', '')}" 
                                for name, info in list(context['type_information'].items())[:3]
                            ])
                            if type_info_str:
                                context_parts.append(f"- Type information: {type_info_str}")
                        
                        if context_parts:
                            context_info = "\n".join(context_parts) + "\n"
                    else:
                        logger.debug(f"Module not found in PKG for file: {rel_path} (tried normalized: {rel_path_normalized})")
                        
                except Exception as e:
                    logger.warning(f"Failed to build PKG context: {e}", exc_info=True)
                    # Continue without context if there's an error
            
            changes_text = '\n'.join(f"- {desc}" for desc in change_descriptions)
            
            prompt = f"""You are a code-edit assistant. Given:
- File path: {file_path}
- Current file content:
<<<
{original_content}
>>>
- Edit instructions:
{changes_text}
{context_info}
Apply the edits precisely. Return ONLY the modified file content (no prose, no explanations).
Preserve code style and formatting. Make minimal, targeted changes.
{f"Follow the framework patterns and conventions shown in related modules." if context_info else ""}"""

            response = llm.invoke(prompt)
            modified_content = response.content if hasattr(response, 'content') else str(response)
            
            # Clean up response (remove markdown code blocks if present)
            if modified_content.startswith('```'):
                # Remove code block markers
                lines = modified_content.split('\n')
                if lines[0].startswith('```'):
                    lines = lines[1:]
                if lines[-1].strip() == '```':
                    lines = lines[:-1]
                modified_content = '\n'.join(lines)
            
            return modified_content
        
        except Exception as e:
            logger.error(f"LLM edit failed: {e}", exc_info=True)
            return original_content
    
    def _generate_file_diff(
        self,
        original: str,
        modified: str,
        file_path: str
    ) -> str:
        """
        Generate unified diff for file changes.
        
        Args:
            original: Original content
            modified: Modified content
            file_path: File path
            
        Returns:
            Unified diff string
        """
        try:
            import difflib
            
            original_lines = original.splitlines(keepends=True)
            modified_lines = modified.splitlines(keepends=True)
            
            diff = difflib.unified_diff(
                original_lines,
                modified_lines,
                fromfile=file_path,
                tofile=file_path,
                lineterm=''
            )
            
            return ''.join(diff)
        
        except Exception as e:
            logger.error(f"Error generating diff: {e}", exc_info=True)
            return ""
    
    def generate_diff(self) -> str:
        """
        Generate unified diff for all changes.
        
        Returns:
            Unified diff string
        """
        if not self.repo:
            return ""
        
        try:
            # Get diff of working directory
            diff = self.repo.git.diff()
            return diff
        except Exception as e:
            logger.error(f"Error generating diff: {e}", exc_info=True)
            return ""
    
    def commit_changes(self, message: str) -> str:
        """
        Commit changes with message.
        
        Args:
            message: Commit message
            
        Returns:
            Commit SHA
        """
        if not self.repo:
            logger.warning("Not a git repository, skipping commit")
            return ""
        
        try:
            # Configure git user if not set
            git_user_name = os.getenv('GIT_USER_NAME', 'Agent')
            git_user_email = os.getenv('GIT_USER_EMAIL', 'agent@example.com')
            
            self.repo.config_writer().set_value("user", "name", git_user_name).release()
            self.repo.config_writer().set_value("user", "email", git_user_email).release()
            
            # Stage all changes
            self.repo.git.add(A=True)
            
            # Commit
            commit = self.repo.index.commit(message)
            logger.info(f"Committed changes: {commit.hexsha}")
            
            return commit.hexsha
        
        except GitCommandError as e:
            logger.error(f"Error committing changes: {e}", exc_info=True)
            raise

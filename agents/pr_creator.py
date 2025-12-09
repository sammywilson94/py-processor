"""PR Creator - Creates pull requests via GitHub API."""

import logging
import os
from typing import Dict, Any, Optional
from git import Repo
from git.exc import GitCommandError
from github import Github
from github.GithubException import GithubException

logger = logging.getLogger(__name__)


class PRCreator:
    """Creates pull requests for code changes."""
    
    def __init__(self, repo_path: str):
        """
        Initialize PR creator.
        
        Args:
            repo_path: Path to repository
        """
        self.repo_path = os.path.abspath(repo_path)
        self.repo = None
        self.github = None
        self._init_github()
        
        try:
            self.repo = Repo(self.repo_path)
        except Exception:
            logger.warning(f"Not a git repository: {repo_path}")
            self.repo = None
    
    def _init_github(self) -> None:
        """Initialize GitHub API client."""
        try:
            github_token = os.getenv('GITHUB_TOKEN')
            if not github_token or github_token == 'your_github_token_here':
                logger.warning("GITHUB_TOKEN not set, PR creation will be limited")
                return
            
            self.github = Github(github_token)
        except Exception as e:
            logger.error(f"Failed to initialize GitHub client: {e}", exc_info=True)
            self.github = None
    
    def fork_repository(self, owner: str, repo_name: str) -> Dict[str, Any]:
        """
        Fork a repository if not already forked by the authenticated user.
        
        Args:
            owner: Repository owner username
            repo_name: Repository name
            
        Returns:
            Dictionary with success status, fork_url, fork_owner, html_url, original_url
        """
        if not self.github:
            logger.warning("GitHub client not initialized, cannot fork repository")
            return {
                "success": False,
                "error": "GitHub client not initialized",
                "message": "GITHUB_TOKEN not configured"
            }
        
        try:
            # Get authenticated user
            user = self.github.get_user()
            authenticated_username = user.login
            logger.info(f"Authenticated GitHub user: {authenticated_username}")
            
            # Get original repository
            original_repo = self.github.get_repo(f"{owner}/{repo_name}")
            original_url = original_repo.clone_url
            original_html_url = original_repo.html_url
            
            logger.info(f"Checking fork status for {owner}/{repo_name}")
            
            # Check if repository is already owned by authenticated user
            if owner.lower() == authenticated_username.lower():
                logger.info(f"Repository {owner}/{repo_name} is owned by authenticated user, no fork needed")
                return {
                    "success": True,
                    "fork_url": original_url,
                    "fork_owner": authenticated_username,
                    "html_url": original_html_url,
                    "original_url": original_url,
                    "already_owned": True
                }
            
            # Check if fork already exists
            # Try to get the fork directly
            fork_repo = None
            try:
                # Check if user has a fork of this repository
                fork_repo = user.get_repo(repo_name)
                # Verify it's actually a fork of the original
                if fork_repo.fork and fork_repo.parent and fork_repo.parent.full_name == f"{owner}/{repo_name}":
                    logger.info(f"Found existing fork: {authenticated_username}/{repo_name}")
                    fork_url = fork_repo.clone_url
                    fork_html_url = fork_repo.html_url
                else:
                    # Not a fork, or not a fork of this repo
                    fork_repo = None
            except GithubException:
                # Repository not found, need to create fork
                fork_repo = None
            
            # If no existing fork found, create one
            if not fork_repo:
                logger.info(f"Creating fork of {owner}/{repo_name} for {authenticated_username}")
                try:
                    fork_repo = original_repo.create_fork()
                    logger.info(f"Successfully created fork: {fork_repo.full_name}")
                except GithubException as e:
                    # Check if error is because fork already exists
                    if "already exists" in str(e).lower() or "already a fork" in str(e).lower():
                        logger.info(f"Fork already exists, attempting to retrieve it")
                        # Try to get the fork again
                        try:
                            fork_repo = user.get_repo(repo_name)
                        except GithubException:
                            logger.error(f"Could not retrieve existing fork: {e}")
                            return {
                                "success": False,
                                "error": f"Fork exists but could not be retrieved: {str(e)}",
                                "original_url": original_url
                            }
                    else:
                        logger.error(f"Failed to create fork: {e}", exc_info=True)
                        return {
                            "success": False,
                            "error": f"Failed to create fork: {str(e)}",
                            "original_url": original_url
                        }
            
            fork_url = fork_repo.clone_url
            fork_html_url = fork_repo.html_url
            fork_owner = fork_repo.owner.login
            
            logger.info(f"Fork operation successful: {fork_owner}/{repo_name}")
            logger.info(f"Fork URL: {fork_url}")
            logger.info(f"Original URL: {original_url}")
            
            return {
                "success": True,
                "fork_url": fork_url,
                "fork_owner": fork_owner,
                "html_url": fork_html_url,
                "original_url": original_url,
                "already_owned": False
            }
        
        except GithubException as e:
            logger.error(f"GitHub API error during fork operation: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"GitHub API error: {str(e)}",
                "original_url": f"https://github.com/{owner}/{repo_name}.git" if owner and repo_name else None
            }
        except Exception as e:
            logger.error(f"Unexpected error during fork operation: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e),
                "original_url": f"https://github.com/{owner}/{repo_name}.git" if owner and repo_name else None
            }
    
    def push_branch(
        self,
        branch_name: str,
        remote: str = "origin"
    ) -> str:
        """
        Push branch to remote.
        
        Args:
            branch_name: Branch name to push
            remote: Remote name (default: origin)
            
        Returns:
            Remote branch reference
        """
        if not self.repo:
            raise ValueError("Not a git repository")
        
        try:
            # Get remote
            remote_obj = self.repo.remote(remote)
            
            # Push branch
            remote_obj.push(branch_name)
            
            logger.info(f"Pushed branch {branch_name} to {remote}")
            return f"{remote}/{branch_name}"
        
        except GitCommandError as e:
            logger.error(f"Error pushing branch: {e}", exc_info=True)
            raise
    
    def create_pr(
        self,
        branch: str,
        title: str,
        description: str
    ) -> Dict[str, Any]:
        """
        Create pull request.
        
        Args:
            branch: Branch name
            title: PR title
            description: PR description
            
        Returns:
            PR information dictionary
        """
        if not self.github:
            return {
                "success": False,
                "error": "GitHub client not initialized",
                "message": "GITHUB_TOKEN not configured"
            }
        
        try:
            # Get repository info
            repo_url = self._get_repo_url()
            if not repo_url:
                return {
                    "success": False,
                    "error": "Could not determine repository URL"
                }
            
            # Parse repo owner and name from URL
            owner, repo_name = self._parse_repo_url(repo_url)
            if not owner or not repo_name:
                return {
                    "success": False,
                    "error": "Could not parse repository URL"
                }
            
            # Get GitHub repository
            github_repo = self.github.get_repo(f"{owner}/{repo_name}")
            
            # Get base branch (usually main or master)
            base_branch = self._get_base_branch()
            
            # Create PR
            pr = github_repo.create_pull(
                title=title,
                body=description,
                head=branch,
                base=base_branch
            )
            
            logger.info(f"Created PR #{pr.number}: {pr.title}")
            
            return {
                "success": True,
                "url": pr.html_url,
                "number": pr.number,
                "id": pr.id,
                "state": pr.state
            }
        
        except GithubException as e:
            logger.error(f"GitHub API error: {e}", exc_info=True)
            return {
                "success": False,
                "error": f"GitHub API error: {str(e)}"
            }
        except Exception as e:
            logger.error(f"Error creating PR: {e}", exc_info=True)
            return {
                "success": False,
                "error": str(e)
            }
    
    def generate_pr_description(
        self,
        plan: Dict[str, Any],
        test_results: Dict[str, Any],
        changes: Dict[str, Any]
    ) -> str:
        """
        Generate PR description from plan, test results, and changes.
        
        Args:
            plan: Plan dictionary
            test_results: Test results dictionary
            changes: Changes dictionary
            
        Returns:
            PR description markdown
        """
        intent = plan.get('intent', {})
        intent_description = intent.get('description', 'Agent-generated changes')
        
        # Get file list
        files_changed = []
        for change in changes.get('changes', []):
            file_path = change.get('file')
            if file_path:
                files_changed.append(file_path)
        
        # Get test summary
        tests_passed = test_results.get('tests_passed', 0)
        tests_failed = test_results.get('tests_failed', 0)
        build_success = test_results.get('build_success', False)
        
        # Build description
        description = f"""## Summary
{intent_description}

## Files Changed
{chr(10).join(f"- {file}" for file in files_changed) if files_changed else "- No files listed"}

## Testing
- Tests passed: {tests_passed}
- Tests failed: {tests_failed}
- Build success: {build_success}
- Lint and type checks: {'Passed' if build_success else 'Failed'}

## Plan Summary
This PR implements the following tasks:
"""
        
        # Add task list
        tasks = plan.get('tasks', [])
        for task in tasks:
            task_desc = task.get('task', 'Unknown task')
            description += f"- {task_desc}\n"
        
        # Add migration info if needed
        if plan.get('migration_required', False):
            description += "\n## Migration\nDatabase migration may be required. Please review migration steps.\n"
        
        # Add rollback info
        description += "\n## Rollback\nTo rollback, revert this branch or use `git revert <commit_sha>`\n"
        
        return description
    
    def _get_repo_url(self) -> Optional[str]:
        """Get repository URL from git remote."""
        if not self.repo:
            return None
        
        try:
            remote = self.repo.remote('origin')
            url = remote.url
            
            # Convert SSH URL to HTTPS if needed
            if url.startswith('git@'):
                # git@github.com:owner/repo.git -> https://github.com/owner/repo
                url = url.replace('git@', 'https://').replace(':', '/').replace('.git', '')
            
            return url
        except Exception as e:
            logger.error(f"Error getting repo URL: {e}", exc_info=True)
            return None
    
    def _parse_repo_url(self, url: str) -> tuple:
        """
        Parse owner and repo name from URL.
        
        Args:
            url: Repository URL
            
        Returns:
            Tuple of (owner, repo_name) or (None, None)
        """
        try:
            # Handle different URL formats
            if 'github.com' in url:
                # https://github.com/owner/repo or git@github.com:owner/repo.git
                parts = url.split('github.com/')[-1].split('github.com:')[-1]
                parts = parts.replace('.git', '').strip('/')
                path_parts = parts.split('/')
                
                if len(path_parts) >= 2:
                    return path_parts[0], path_parts[1]
            
            return None, None
        except Exception as e:
            logger.error(f"Error parsing repo URL: {e}", exc_info=True)
            return None, None
    
    def _get_base_branch(self) -> str:
        """Get base branch (main or master)."""
        if not self.repo:
            return 'main'
        
        try:
            # Check if main exists
            if 'main' in [ref.name.split('/')[-1] for ref in self.repo.heads]:
                return 'main'
            elif 'master' in [ref.name.split('/')[-1] for ref in self.repo.heads]:
                return 'master'
            else:
                # Get default branch from remote
                remote = self.repo.remote('origin')
                refs = remote.refs
                for ref in refs:
                    if ref.remote_head in ['main', 'master']:
                        return ref.remote_head
                
                return 'main'  # Default
        except Exception:
            return 'main'

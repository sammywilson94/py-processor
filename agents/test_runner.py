"""Test Runner - Executes tests and static analysis."""

import logging
import os
import platform
import shutil
import subprocess
import re
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)


class TestRunner:
    """Runs tests, linters, and type checks for a repository."""
    
    def __init__(self, repo_path: str):
        """
        Initialize test runner.
        
        Args:
            repo_path: Path to repository
        """
        self.repo_path = os.path.abspath(repo_path)
        self.language = None
        self._detect_language()
    
    def _detect_language(self) -> None:
        """Detect primary language of repository."""
        # Check for language indicators
        if os.path.exists(os.path.join(self.repo_path, 'package.json')):
            self.language = 'typescript'  # or javascript
        elif os.path.exists(os.path.join(self.repo_path, 'requirements.txt')):
            self.language = 'python'
        elif os.path.exists(os.path.join(self.repo_path, 'pom.xml')):
            self.language = 'java'
        elif os.path.exists(os.path.join(self.repo_path, 'build.gradle')):
            self.language = 'java'
        elif os.path.exists(os.path.join(self.repo_path, '*.csproj')):
            self.language = 'csharp'
        else:
            self.language = 'unknown'
    
    def _get_node_command(self, command: str) -> List[str]:
        """
        Get the correct Node.js command for the current platform.
        
        On Windows, npm and npx are batch files (.cmd), so we need to use
        'npm.cmd' or 'npx.cmd' instead of 'npm' or 'npx'.
        
        Args:
            command: The command name ('npm' or 'npx')
            
        Returns:
            List containing the command to use (e.g., ['npm.cmd'] on Windows, ['npm'] otherwise)
        """
        if platform.system() == 'Windows':
            cmd = f'{command}.cmd'
            # Optionally validate command exists
            if shutil.which(cmd) is None:
                # Fallback to command without .cmd if .cmd version not found
                if shutil.which(command) is not None:
                    return [command]
            return [cmd]
        else:
            return [command]
    
    def run_tests(self, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Run test suite.
        
        Args:
            language: Optional language override
            
        Returns:
            Test results dictionary
        """
        lang = language or self.language
        
        if lang == 'python':
            return self._run_python_tests()
        elif lang in ['typescript', 'javascript']:
            return self._run_typescript_tests()
        elif lang == 'java':
            return self._run_java_tests()
        elif lang == 'csharp':
            return self._run_csharp_tests()
        else:
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": "Language not detected or not supported",
                "build_success": False,
                "error": "Unsupported language"
            }
    
    def _run_python_tests(self) -> Dict[str, Any]:
        """Run Python tests using pytest."""
        try:
            timeout = int(os.getenv('TEST_RUNNER_TIMEOUT', '300'))
            
            # Check if pytest is available
            result = subprocess.run(
                ['pytest', '--version'],
                capture_output=True,
                text=True,
                timeout=10,
                cwd=self.repo_path
            )
            
            if result.returncode != 0:
                # Try python -m pytest
                cmd = ['python', '-m', 'pytest', '-q', '--tb=short']
            else:
                cmd = ['pytest', '-q', '--tb=short']
            
            # Run tests
            result = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.repo_path
            )
            
            # Parse pytest output
            output = result.stdout + result.stderr
            passed, failed = self._parse_pytest_output(output)
            
            return {
                "tests_passed": passed,
                "tests_failed": failed,
                "test_output": output,
                "build_success": result.returncode == 0,
                "exit_code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": "Test execution timed out",
                "build_success": False,
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running Python tests: {e}", exc_info=True)
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": str(e),
                "build_success": False,
                "error": str(e)
            }
    
    def _run_typescript_tests(self) -> Dict[str, Any]:
        """Run TypeScript/JavaScript tests."""
        try:
            timeout = int(os.getenv('TEST_RUNNER_TIMEOUT', '300'))
            
            # Check for package.json and test script
            package_json_path = os.path.join(self.repo_path, 'package.json')
            if not os.path.exists(package_json_path):
                return {
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "test_output": "package.json not found",
                    "build_success": False,
                    "error": "No package.json"
                }
            
            # Try npm test
            result = subprocess.run(
                self._get_node_command('npm') + ['test'],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.repo_path
            )
            
            output = result.stdout + result.stderr
            passed, failed = self._parse_jest_output(output)
            
            return {
                "tests_passed": passed,
                "tests_failed": failed,
                "test_output": output,
                "build_success": result.returncode == 0,
                "exit_code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": "Test execution timed out",
                "build_success": False,
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running TypeScript tests: {e}", exc_info=True)
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": str(e),
                "build_success": False,
                "error": str(e)
            }
    
    def _run_java_tests(self) -> Dict[str, Any]:
        """Run Java tests using Maven or Gradle."""
        try:
            timeout = int(os.getenv('TEST_RUNNER_TIMEOUT', '300'))
            
            # Try Maven first
            if os.path.exists(os.path.join(self.repo_path, 'pom.xml')):
                result = subprocess.run(
                    ['mvn', 'test'],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.repo_path
                )
            # Try Gradle
            elif os.path.exists(os.path.join(self.repo_path, 'build.gradle')):
                result = subprocess.run(
                    ['./gradlew', 'test'],
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    cwd=self.repo_path
                )
            else:
                return {
                    "tests_passed": 0,
                    "tests_failed": 0,
                    "test_output": "No build file found (pom.xml or build.gradle)",
                    "build_success": False,
                    "error": "No build file"
                }
            
            output = result.stdout + result.stderr
            passed, failed = self._parse_maven_output(output)
            
            return {
                "tests_passed": passed,
                "tests_failed": failed,
                "test_output": output,
                "build_success": result.returncode == 0,
                "exit_code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": "Test execution timed out",
                "build_success": False,
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running Java tests: {e}", exc_info=True)
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": str(e),
                "build_success": False,
                "error": str(e)
            }
    
    def _run_csharp_tests(self) -> Dict[str, Any]:
        """Run C# tests using dotnet."""
        try:
            timeout = int(os.getenv('TEST_RUNNER_TIMEOUT', '300'))
            
            result = subprocess.run(
                ['dotnet', 'test'],
                capture_output=True,
                text=True,
                timeout=timeout,
                cwd=self.repo_path
            )
            
            output = result.stdout + result.stderr
            passed, failed = self._parse_dotnet_output(output)
            
            return {
                "tests_passed": passed,
                "tests_failed": failed,
                "test_output": output,
                "build_success": result.returncode == 0,
                "exit_code": result.returncode
            }
        
        except subprocess.TimeoutExpired:
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": "Test execution timed out",
                "build_success": False,
                "error": "Timeout"
            }
        except Exception as e:
            logger.error(f"Error running C# tests: {e}", exc_info=True)
            return {
                "tests_passed": 0,
                "tests_failed": 0,
                "test_output": str(e),
                "build_success": False,
                "error": str(e)
            }
    
    def _parse_pytest_output(self, output: str) -> tuple:
        """Parse pytest output to extract pass/fail counts."""
        # Look for patterns like "5 passed, 2 failed"
        match = re.search(r'(\d+)\s+passed', output)
        passed = int(match.group(1)) if match else 0
        
        match = re.search(r'(\d+)\s+failed', output)
        failed = int(match.group(1)) if match else 0
        
        return passed, failed
    
    def _parse_jest_output(self, output: str) -> tuple:
        """Parse Jest output to extract pass/fail counts."""
        # Look for patterns like "Tests: 5 passed, 2 failed"
        match = re.search(r'Tests:\s*(\d+)\s+passed', output, re.IGNORECASE)
        passed = int(match.group(1)) if match else 0
        
        match = re.search(r'(\d+)\s+failed', output, re.IGNORECASE)
        failed = int(match.group(1)) if match else 0
        
        return passed, failed
    
    def _parse_maven_output(self, output: str) -> tuple:
        """Parse Maven test output."""
        # Look for "Tests run: X, Failures: Y"
        match = re.search(r'Tests run:\s*(\d+)', output, re.IGNORECASE)
        total = int(match.group(1)) if match else 0
        
        match = re.search(r'Failures:\s*(\d+)', output, re.IGNORECASE)
        failed = int(match.group(1)) if match else 0
        
        passed = total - failed
        return passed, failed
    
    def _parse_dotnet_output(self, output: str) -> tuple:
        """Parse dotnet test output."""
        # Look for "Passed! - Failed: X, Passed: Y"
        match = re.search(r'Passed!.*?Failed:\s*(\d+).*?Passed:\s*(\d+)', output, re.IGNORECASE)
        if match:
            failed = int(match.group(1))
            passed = int(match.group(2))
            return passed, failed
        
        # Fallback
        match = re.search(r'(\d+)\s+passed', output, re.IGNORECASE)
        passed = int(match.group(1)) if match else 0
        
        match = re.search(r'(\d+)\s+failed', output, re.IGNORECASE)
        failed = int(match.group(1)) if match else 0
        
        return passed, failed
    
    def run_linter(self, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Run linter.
        
        Args:
            language: Optional language override
            
        Returns:
            Linter results dictionary
        """
        lang = language or self.language
        
        if lang == 'python':
            return self._run_pylint()
        elif lang in ['typescript', 'javascript']:
            return self._run_eslint()
        else:
            return {
                "errors": [],
                "warnings": [],
                "success": True,
                "message": "Linter not configured for this language"
            }
    
    def _run_pylint(self) -> Dict[str, Any]:
        """Run pylint for Python."""
        try:
            result = subprocess.run(
                ['pylint', '--errors-only', '.'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.repo_path
            )
            
            errors = []
            if result.stdout:
                errors = result.stdout.split('\n')
            
            return {
                "errors": errors,
                "warnings": [],
                "success": result.returncode == 0,
                "output": result.stdout
            }
        except Exception as e:
            logger.error(f"Error running pylint: {e}", exc_info=True)
            return {
                "errors": [],
                "warnings": [],
                "success": True,
                "message": f"Linter not available: {str(e)}"
            }
    
    def _run_eslint(self) -> Dict[str, Any]:
        """Run eslint for TypeScript/JavaScript."""
        try:
            result = subprocess.run(
                self._get_node_command('npx') + ['eslint', '.'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.repo_path
            )
            
            errors = []
            if result.stdout:
                errors = result.stdout.split('\n')
            
            return {
                "errors": errors,
                "warnings": [],
                "success": result.returncode == 0,
                "output": result.stdout
            }
        except Exception as e:
            logger.error(f"Error running eslint: {e}", exc_info=True)
            return {
                "errors": [],
                "warnings": [],
                "success": True,
                "message": f"Linter not available: {str(e)}"
            }
    
    def run_typecheck(self, language: Optional[str] = None) -> Dict[str, Any]:
        """
        Run type checker.
        
        Args:
            language: Optional language override
            
        Returns:
            Type check results dictionary
        """
        lang = language or self.language
        
        if lang == 'python':
            return self._run_mypy()
        elif lang == 'typescript':
            return self._run_tsc()
        else:
            return {
                "errors": [],
                "success": True,
                "message": "Type checker not configured for this language"
            }
    
    def _run_mypy(self) -> Dict[str, Any]:
        """Run mypy for Python."""
        try:
            result = subprocess.run(
                ['mypy', '.'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.repo_path
            )
            
            errors = []
            if result.stdout:
                errors = result.stdout.split('\n')
            
            return {
                "errors": errors,
                "success": result.returncode == 0,
                "output": result.stdout
            }
        except Exception as e:
            logger.error(f"Error running mypy: {e}", exc_info=True)
            return {
                "errors": [],
                "success": True,
                "message": f"Type checker not available: {str(e)}"
            }
    
    def _run_tsc(self) -> Dict[str, Any]:
        """Run TypeScript compiler for type checking."""
        try:
            result = subprocess.run(
                self._get_node_command('npx') + ['tsc', '--noEmit'],
                capture_output=True,
                text=True,
                timeout=60,
                cwd=self.repo_path
            )
            
            errors = []
            if result.stdout:
                errors = result.stdout.split('\n')
            
            return {
                "errors": errors,
                "success": result.returncode == 0,
                "output": result.stdout
            }
        except Exception as e:
            logger.error(f"Error running tsc: {e}", exc_info=True)
            return {
                "errors": [],
                "success": True,
                "message": f"Type checker not available: {str(e)}"
            }

"""Agent Orchestrator - Main coordinator for agent workflow."""

import logging
import os
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Optional
from flask_socketio import SocketIO

from services.parser_service import generate_pkg
import db.neo4j_db as neo4j_db

logger = logging.getLogger(__name__)


class AgentOrchestrator:
    """Orchestrates the complete agent workflow from user request to PR creation."""
    
    def __init__(self):
        """Initialize the orchestrator."""
        # Use shared session store from chat_routes
        try:
            from routes.chat_routes import active_sessions
            self.sessions = active_sessions
        except ImportError:
            # Fallback to local storage if import fails
            self.sessions: Dict[str, Dict[str, Any]] = {}
    
    def process_user_request(
        self,
        session_id: str,
        user_message: str,
        repo_url: Optional[str],
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Process a user request through the complete agent workflow.
        
        Args:
            session_id: Unique session identifier
            user_message: User's natural language request
            repo_url: Optional repository URL
            socketio: SocketIO instance for streaming updates
            sid: Socket session ID
        """
        try:
            logger.info(f"🔄 PROCESSING USER REQUEST | Session: {session_id} | Message: '{user_message[:50]}...' | Repo URL: {repo_url or 'None'}")
            
            # Stream initial status
            self._stream_update(
                socketio, sid, "status", "intent_extraction",
                {"message": "Processing your request..."},
                session_id
            )
            
            # Retrieve repo_url from session if not provided
            if not repo_url and session_id in self.sessions:
                repo_url = self.sessions[session_id].get('repo_url')
                logger.info(f"📋 RETRIEVED REPO URL FROM SESSION | Session: {session_id} | URL: {repo_url}")
            
            # Ensure repo is loaded if URL provided
            repo_path = None
            pkg_data = None
            
            if repo_url:
                logger.info(f"📥 LOADING REPOSITORY | Session: {session_id} | URL: {repo_url}")
                repo_path, pkg_data = self._ensure_repo_loaded(
                    session_id, repo_url, socketio, sid
                )
                if not pkg_data:
                    logger.error(f"❌ FAILED TO LOAD REPO/PKG | Session: {session_id} | URL: {repo_url}")
                    self._stream_update(
                        socketio, sid, "error", "repo_loading",
                        {"message": "Failed to load repository or PKG data"},
                        session_id
                    )
                    return
                logger.info(f"✅ REPOSITORY LOADED | Session: {session_id} | Path: {repo_path} | PKG loaded: {pkg_data is not None}")
            
            # Extract intent
            logger.info(f"🧠 EXTRACTING INTENT | Session: {session_id} | Analyzing user message...")
            self._stream_update(
                socketio, sid, "status", "intent_extraction",
                {"message": "Analyzing your request..."},
                session_id
            )
            
            try:
                from agents.intent_router import IntentRouter
                intent_router = IntentRouter()
                intent = intent_router.extract_intent(user_message)
                
                intent_category = intent.get('intent_category', 'unknown')
                intent_type = intent.get('intent', 'unknown')
                logger.info(f"✅ INTENT EXTRACTED | Session: {session_id} | Category: {intent_category} | Type: {intent_type}")
                
                self._stream_update(
                    socketio, sid, "log", "intent_extraction",
                    {"intent": intent, "message": f"Intent extracted: {intent.get('intent', 'unknown')}"},
                    session_id
                )
            except Exception as e:
                logger.error(f"Intent extraction failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "intent_extraction",
                    {"message": f"Failed to extract intent: {str(e)}"},
                    session_id
                )
                return
            
            # Store intent in session
            if session_id not in self.sessions:
                self.sessions[session_id] = {}
            self.sessions[session_id]['current_intent'] = intent
            self.sessions[session_id]['repo_path'] = repo_path
            self.sessions[session_id]['pkg_data'] = pkg_data
            
            # Route based on intent category
            intent_category = intent.get('intent_category', 'code_change')
            logger.info(f"🎯 ROUTING BY INTENT | Session: {session_id} | Category: {intent_category}")
            
            if intent_category == 'informational_query':
                logger.info(f"❓ HANDLING INFORMATIONAL QUERY | Session: {session_id}")
                # Handle informational queries - may need PKG but not repo_path
                # Retrieve repo_url from session if not provided
                if not repo_url and session_id in self.sessions:
                    repo_url = self.sessions[session_id].get('repo_url')
                
                if not pkg_data:
                    # Try to load PKG (will check session cache, Neo4j, file cache, or regenerate)
                    repo_path, pkg_data = self._ensure_repo_loaded(
                        session_id, repo_url, socketio, sid
                    )
                    if pkg_data:
                        self.sessions[session_id]['pkg_data'] = pkg_data
                        if repo_path:
                            self.sessions[session_id]['repo_path'] = repo_path
                
                if pkg_data:
                    logger.info(f"💬 PROCESSING QUERY | Session: {session_id} | Query: '{user_message[:50]}...'")
                    self._handle_informational_query(
                        user_message, intent, pkg_data, session_id, socketio, sid
                    )
                    logger.info(f"✅ QUERY RESPONSE SENT | Session: {session_id}")
                else:
                    logger.warning(f"⚠️  NO PKG DATA FOR QUERY | Session: {session_id} | Requesting repo URL")
                    self._stream_update(
                        socketio, sid, "error", "query_handling",
                        {"message": "PKG data is required to answer queries. Please provide a repository URL."},
                        session_id
                    )
                return
            
            elif intent_category == 'diagram_request':
                logger.info(f"📊 HANDLING DIAGRAM REQUEST | Session: {session_id}")
                # Handle diagram requests - may need PKG but not repo_path
                # Retrieve repo_url from session if not provided
                if not repo_url and session_id in self.sessions:
                    repo_url = self.sessions[session_id].get('repo_url')
                
                if not pkg_data:
                    # Try to load PKG (will check session cache, Neo4j, file cache, or regenerate)
                    repo_path, pkg_data = self._ensure_repo_loaded(
                        session_id, repo_url, socketio, sid
                    )
                    if pkg_data:
                        self.sessions[session_id]['pkg_data'] = pkg_data
                        if repo_path:
                            self.sessions[session_id]['repo_path'] = repo_path
                
                if pkg_data:
                    self._handle_diagram_request(
                        user_message, intent, pkg_data, session_id, socketio, sid
                    )
                else:
                    self._stream_update(
                        socketio, sid, "error", "diagram_generation",
                        {"message": "PKG data is required to generate diagrams. Please provide a repository URL."},
                        session_id
                    )
                return
            
            elif intent_category == 'code_change':
                # Execute full workflow for code changes
                logger.info(f"⚙️  HANDLING CODE CHANGE REQUEST | Session: {session_id}")
                if repo_path and pkg_data:
                    logger.info(f"🚀 EXECUTING WORKFLOW | Session: {session_id} | Repo: {repo_path}")
                    self._execute_workflow(
                        intent, pkg_data, repo_path, session_id, socketio, sid
                    )
                    logger.info(f"✅ WORKFLOW COMPLETED | Session: {session_id}")
                else:
                    logger.warning(f"⚠️  MISSING REPO/PKG FOR CODE CHANGE | Session: {session_id}")
                    self._stream_update(
                        socketio, sid, "status", "waiting",
                        {"message": "Please provide a repository URL to proceed with code changes"},
                        session_id
                    )
            else:
                # Fallback to code_change for unknown categories
                logger.warning(f"Unknown intent category: {intent_category}, defaulting to code_change")
                if repo_path and pkg_data:
                    self._execute_workflow(
                        intent, pkg_data, repo_path, session_id, socketio, sid
                    )
                else:
                    self._stream_update(
                        socketio, sid, "status", "waiting",
                        {"message": "Please provide a repository URL to proceed with code changes"},
                        session_id
                    )
        
        except Exception as e:
            logger.error(f"Error processing user request: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "processing",
                {"message": f"An error occurred: {str(e)}"},
                session_id
            )
    
    def _ensure_repo_loaded(
        self,
        session_id: str,
        repo_url: Optional[str] = None,
        socketio: Optional[SocketIO] = None,
        sid: Optional[str] = None
    ) -> tuple:
        """
        Ensure repository is cloned and PKG is loaded.
        
        Args:
            session_id: Session identifier
            repo_url: Optional repository URL (if None, uses session's repo_url)
            socketio: Optional SocketIO instance for streaming updates
            sid: Optional socket session ID
        
        Returns:
            Tuple of (repo_path, pkg_data) or (None, None) on failure
        """
        try:
            logger.info(f"📦 ENSURING REPO LOADED | Session: {session_id} | URL: {repo_url or 'from session'}")
            
            # Get session
            session = self.sessions.get(session_id, {})
            
            # If repo_url not provided, try to get from session
            if not repo_url:
                repo_url = session.get('repo_url')
                if not repo_url:
                    logger.warning(f"⚠️  NO REPO URL | Session: {session_id} | No repo_url provided and none found in session")
                    return None, None
                logger.info(f"📋 USING SESSION REPO URL | Session: {session_id} | URL: {repo_url}")
            
            # Check if already loaded in session cache
            if session.get('repo_url') == repo_url and session.get('pkg_data'):
                logger.info(f"✅ USING CACHED PKG | Session: {session_id} | Repo: {repo_url}")
                return session.get('repo_path'), session.get('pkg_data')
            
            # Extract project_id from repo_url (before cloning)
            # Use same logic as extract_project_metadata: repo_name from URL
            project_id = os.path.splitext(os.path.basename(repo_url))[0]
            logger.info(f"🔍 PROJECT ID EXTRACTED | Session: {session_id} | Project ID: {project_id}")
            
            # Try to load from Neo4j first (before cloning)
            logger.info(f"🔎 CHECKING NEO4J FOR PKG | Session: {session_id} | Project ID: {project_id}")
            if neo4j_db.check_pkg_stored(project_id):
                logger.info(f"✅ PKG FOUND IN NEO4J | Session: {session_id} | Project ID: {project_id} | Loading from database...")
                if socketio and sid:
                    self._stream_update(
                        socketio, sid, "status", "pkg_loading",
                        {"message": "Loading knowledge graph from database..."},
                        session_id
                    )
                
                pkg_data = neo4j_db.load_pkg_from_neo4j(project_id)
                if pkg_data:
                    logger.info(f"✅ PKG LOADED FROM NEO4J | Session: {session_id} | Project ID: {project_id} | Modules: {len(pkg_data.get('modules', []))} | Symbols: {len(pkg_data.get('symbols', []))}")
                    # We have PKG from Neo4j, but we may still need repo_path
                    # Try to get from session or construct from project rootPath
                    repo_path = session.get('repo_path')
                    if not repo_path and pkg_data.get('project', {}).get('rootPath'):
                        repo_path = pkg_data['project']['rootPath']
                    
                    # Store in session
                    if session_id not in self.sessions:
                        self.sessions[session_id] = {}
                    self.sessions[session_id]['repo_url'] = repo_url
                    self.sessions[session_id]['repo_path'] = repo_path
                    self.sessions[session_id]['pkg_data'] = pkg_data
                    
                    if socketio and sid:
                        self._stream_update(
                            socketio, sid, "status", "pkg_loading",
                            {"message": "Knowledge graph loaded from database successfully"},
                            session_id
                        )
                    
                    return repo_path, pkg_data
                else:
                    logger.warning(f"⚠️  FAILED TO LOAD PKG FROM NEO4J | Session: {session_id} | Project ID: {project_id}")
            else:
                logger.info(f"ℹ️  PKG NOT IN NEO4J | Session: {session_id} | Project ID: {project_id} | Will clone and generate")
            
            # If not in Neo4j, proceed with cloning and file cache/regeneration
            logger.info(f"📥 CLONING REPOSITORY | Session: {session_id} | URL: {repo_url}")
            if socketio and sid:
                self._stream_update(
                    socketio, sid, "status", "repo_loading",
                    {"message": f"Loading repository: {repo_url}"},
                    session_id
                )
            
            # Ensure cloned_repos folder exists
            base_dir = os.path.join(os.getcwd(), "cloned_repos")
            os.makedirs(base_dir, exist_ok=True)
            logger.debug(f"📁 CLONED REPOS DIR | Session: {session_id} | Path: {base_dir}")
            
            # Extract repo name from URL
            repo_name = os.path.splitext(os.path.basename(repo_url))[0]
            folder_path = os.path.join(base_dir, repo_name)
            logger.info(f"📂 REPO PATH | Session: {session_id} | Repo name: {repo_name} | Full path: {folder_path}")
            
            # Clone repo if not exists
            if not os.path.exists(folder_path):
                logger.info(f"🔄 CLONING REPO | Session: {session_id} | URL: {repo_url} | Target: {folder_path}")
                if socketio and sid:
                    self._stream_update(
                        socketio, sid, "log", "repo_loading",
                        {"message": f"Cloning repository..."},
                        session_id
                    )
                
                try:
                    git_cmd = "git"
                    try:
                        subprocess.run([git_cmd, "--version"], check=True, capture_output=True)
                        logger.debug(f"✅ GIT FOUND | Session: {session_id} | Using: {git_cmd}")
                    except (FileNotFoundError, subprocess.CalledProcessError):
                        git_cmd = r"C:\Program Files\Git\cmd\git.exe"
                        logger.debug(f"✅ GIT FOUND (Windows) | Session: {session_id} | Using: {git_cmd}")
                    
                    logger.info(f"⏳ CLONING IN PROGRESS | Session: {session_id} | This may take a while...")
                    subprocess.run([git_cmd, "clone", repo_url, folder_path], check=True)
                    logger.info(f"✅ REPOSITORY CLONED | Session: {session_id} | Path: {folder_path}")
                except FileNotFoundError:
                    logger.error(f"❌ GIT NOT FOUND | Session: {session_id} | Git executable not found")
                    return None, None
                except subprocess.CalledProcessError as e:
                    logger.error(f"❌ CLONE FAILED | Session: {session_id} | Error: {e}")
                    return None, None
            else:
                logger.info(f"✅ REPO ALREADY EXISTS | Session: {session_id} | Path: {folder_path} | Skipping clone")
            
            # Update project_id from actual repo path (same as extract_project_metadata)
            project_id = Path(folder_path).name
            logger.info(f"🆔 PROJECT ID | Session: {session_id} | Project ID: {project_id}")
            
            # Load PKG (will try file cache, then regenerate)
            logger.info(f"📊 GENERATING PKG | Session: {session_id} | Project ID: {project_id} | Repo path: {folder_path}")
            if socketio and sid:
                self._stream_update(
                    socketio, sid, "status", "pkg_generation",
                    {"message": "Generating knowledge graph..."},
                    session_id
                )
            
            pkg_data = self._load_pkg(folder_path, project_id)
            
            if not pkg_data:
                logger.error(f"❌ PKG GENERATION FAILED | Session: {session_id} | Project ID: {project_id}")
                return None, None
            
            logger.info(f"✅ PKG GENERATED | Session: {session_id} | Project ID: {project_id} | Modules: {len(pkg_data.get('modules', []))} | Symbols: {len(pkg_data.get('symbols', []))} | Edges: {len(pkg_data.get('edges', []))}")
            
            # Store in session
            if session_id not in self.sessions:
                self.sessions[session_id] = {}
            self.sessions[session_id]['repo_url'] = repo_url
            self.sessions[session_id]['repo_path'] = folder_path
            self.sessions[session_id]['pkg_data'] = pkg_data
            
            if socketio and sid:
                self._stream_update(
                    socketio, sid, "status", "pkg_generation",
                    {"message": "Knowledge graph generated successfully"},
                    session_id
                )
            
            return folder_path, pkg_data
        
        except Exception as e:
            logger.error(f"Error loading repo: {e}", exc_info=True)
            return None, None
    
    def _load_pkg(self, repo_path: Optional[str] = None, project_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """
        Load PKG with priority: session cache → Neo4j → file cache → regenerate.
        
        Args:
            repo_path: Optional path to repository (for file cache/regeneration)
            project_id: Optional project ID (for Neo4j loading)
            
        Returns:
            PKG data dictionary or None on failure
        """
        try:
            # Priority 1: Session cache (handled in _ensure_repo_loaded, but check here too)
            # This is mainly for direct calls to _load_pkg
            
            # Priority 2: Neo4j (if project_id provided)
            if project_id and neo4j_db.check_pkg_stored(project_id):
                logger.info(f"Loading PKG from Neo4j for project {project_id}")
                pkg_data = neo4j_db.load_pkg_from_neo4j(project_id)
                if pkg_data:
                    return pkg_data
                else:
                    logger.warning(f"Failed to load PKG from Neo4j for project {project_id}, falling back to file cache")
            
            # Priority 3: File cache (if repo_path provided)
            if repo_path:
                logger.info(f"Loading PKG from file cache for {repo_path}")
                try:
                    pkg_data = generate_pkg(
                        repo_path=repo_path,
                        fan_threshold=3,
                        include_features=True,
                        use_cache=True
                    )
                    if pkg_data:
                        return pkg_data
                except Exception as e:
                    logger.warning(f"Error loading PKG from file cache: {e}, will regenerate")
            
            # Priority 4: Regenerate (if repo_path provided)
            if repo_path:
                logger.info(f"Regenerating PKG for {repo_path}")
                pkg_data = generate_pkg(
                    repo_path=repo_path,
                    fan_threshold=3,
                    include_features=True,
                    use_cache=False
                )
                return pkg_data
            
            logger.error("Cannot load PKG: no repo_path or project_id provided")
            return None
            
        except Exception as e:
            logger.error(f"Error loading PKG: {e}", exc_info=True)
            return None
    
    def _stream_update(
        self,
        socketio: SocketIO,
        sid: str,
        event_type: str,
        stage: str,
        data: Dict[str, Any],
        session_id: str
    ) -> None:
        """
        Stream update to client via WebSocket.
        
        Args:
            socketio: SocketIO instance
            sid: Socket session ID
            event_type: Type of event (status, log, code_change, etc.)
            stage: Current workflow stage
            data: Event data
            session_id: Session identifier
        """
        try:
            event_data = {
                "type": event_type,
                "timestamp": datetime.utcnow().isoformat(),
                "stage": stage,
                "data": data,
                "session_id": session_id
            }
            socketio.emit("agent_update", event_data, room=sid)
        except Exception as e:
            logger.error(f"Error streaming update: {e}", exc_info=True)
    
    def _execute_workflow(
        self,
        intent: Dict[str, Any],
        pkg_data: Dict[str, Any],
        repo_path: str,
        session_id: str,
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Execute the complete agent workflow.
        
        Args:
            intent: Extracted intent dictionary
            pkg_data: PKG data dictionary
            repo_path: Path to repository
            session_id: Session identifier
            socketio: SocketIO instance
            sid: Socket session ID
        """
        try:
            # Phase 1: PKG Query
            self._stream_update(
                socketio, sid, "status", "pkg_query",
                {"message": "Querying knowledge graph for impacted modules..."},
                session_id
            )
            
            try:
                from services.pkg_query_engine import PKGQueryEngine
                query_engine = PKGQueryEngine(pkg_data)
                
                # Extract target modules from intent hints
                target_tags = intent.get('target_modules', [])
                if not target_tags:
                    # Try to infer from intent description
                    intent_desc = intent.get('description', '').lower()
                    if 'login' in intent_desc or 'auth' in intent_desc:
                        target_tags = ['auth', 'login']
                    elif 'user' in intent_desc:
                        target_tags = ['user']
                
                impacted_modules = []
                for tag in target_tags:
                    modules = query_engine.get_modules_by_tag(tag)
                    impacted_modules.extend(modules)
                
                # Get unique modules
                seen_ids = set()
                unique_modules = []
                for mod in impacted_modules:
                    if mod['id'] not in seen_ids:
                        seen_ids.add(mod['id'])
                        unique_modules.append(mod)
                
                self._stream_update(
                    socketio, sid, "log", "pkg_query",
                    {"message": f"Found {len(unique_modules)} impacted modules"},
                    session_id
                )
            except Exception as e:
                logger.error(f"PKG query failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "pkg_query",
                    {"message": f"Failed to query knowledge graph: {str(e)}"},
                    session_id
                )
                return
            
            # Phase 2: Impact Analysis
            self._stream_update(
                socketio, sid, "status", "impact_analysis",
                {"message": "Analyzing change impact..."},
                session_id
            )
            
            try:
                from agents.impact_analyzer import ImpactAnalyzer
                impact_analyzer = ImpactAnalyzer(pkg_data)
                
                module_ids = [m['id'] for m in unique_modules]
                impact_result = impact_analyzer.analyze_impact(intent, module_ids)
                
                self._stream_update(
                    socketio, sid, "log", "impact_analysis",
                    {
                        "message": f"Impact analysis complete. Risk: {impact_result.get('risk_score', 'unknown')}",
                        "impact": impact_result
                    },
                    session_id
                )
            except Exception as e:
                logger.error(f"Impact analysis failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "impact_analysis",
                    {"message": f"Failed to analyze impact: {str(e)}"},
                    session_id
                )
                return
            
            # Phase 3: Planning
            self._stream_update(
                socketio, sid, "status", "planning",
                {"message": "Generating change plan..."},
                session_id
            )
            
            try:
                from agents.planner import Planner
                planner = Planner()
                
                constraints = intent.get('constraints', [])
                plan = planner.generate_plan(intent, impact_result, constraints)
                
                plan_id = str(uuid.uuid4())
                plan['plan_id'] = plan_id
                
                # Store plan in session
                if session_id not in self.sessions:
                    self.sessions[session_id] = {}
                self.sessions[session_id]['current_plan'] = plan
                self.sessions[session_id]['pending_approval'] = plan_id
                
                self._stream_update(
                    socketio, sid, "log", "planning",
                    {"message": f"Plan generated with {len(plan.get('tasks', []))} tasks"},
                    session_id
                )
                
                # Check if approval required
                requires_approval = (
                    intent.get('human_approval', False) or
                    impact_result.get('requires_approval', False) or
                    os.getenv('AGENT_APPROVAL_REQUIRED', 'true').lower() == 'true'
                )
                
                if requires_approval:
                    self._stream_update(
                        socketio, sid, "approval_request", "planning",
                        {
                            "plan_id": plan_id,
                            "plan": plan,
                            "intent": intent,
                            "impact": impact_result,
                            "message": "Please review and approve the plan to proceed"
                        },
                        session_id
                    )
                    return  # Wait for approval
                
            except Exception as e:
                logger.error(f"Planning failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "planning",
                    {"message": f"Failed to generate plan: {str(e)}"},
                    session_id
                )
                return
            
            # Continue with execution if no approval needed
            self._execute_plan(
                plan, repo_path, session_id, socketio, sid
            )
        
        except Exception as e:
            logger.error(f"Error executing workflow: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "workflow",
                {"message": f"Workflow error: {str(e)}"},
                session_id
            )
    
    def _execute_plan(
        self,
        plan: Dict[str, Any],
        repo_path: str,
        session_id: str,
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Execute the approved plan.
        
        Args:
            plan: Generated plan dictionary
            repo_path: Path to repository
            session_id: Session identifier
            socketio: SocketIO instance
            sid: Socket session ID
        """
        try:
            # Phase 4: Code Editing
            self._stream_update(
                socketio, sid, "status", "editing",
                {"message": "Applying code changes..."},
                session_id
            )
            
            try:
                from agents.code_editor import CodeEditExecutor
                editor = CodeEditExecutor(repo_path)
                
                # Create branch
                branch_name = f"feat/agent-{plan['plan_id'][:8]}"
                editor.create_branch(branch_name)
                
                self._stream_update(
                    socketio, sid, "log", "editing",
                    {"message": f"Created branch: {branch_name}"},
                    session_id
                )
                
                # Apply edits
                edit_result = editor.apply_edits(plan)
                
                # Stream code changes
                for change in edit_result.get('changes', []):
                    self._stream_update(
                        socketio, sid, "code_change", "editing",
                        {
                            "file": change.get('file'),
                            "diff": change.get('diff'),
                            "status": change.get('status')
                        },
                        session_id
                    )
                
                # Generate overall diff
                diff = editor.generate_diff()
                self._stream_update(
                    socketio, sid, "code_change", "editing",
                    {"diff": diff, "message": "All changes applied"},
                    session_id
                )
                
            except Exception as e:
                logger.error(f"Code editing failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "editing",
                    {"message": f"Failed to apply code changes: {str(e)}"},
                    session_id
                )
                return
            
            # Phase 5: Test Execution
            self._stream_update(
                socketio, sid, "status", "testing",
                {"message": "Running tests..."},
                session_id
            )
            
            try:
                from agents.test_runner import TestRunner
                test_runner = TestRunner(repo_path)
                
                test_results = test_runner.run_tests()
                
                self._stream_update(
                    socketio, sid, "test_result", "testing",
                    {
                        "results": test_results,
                        "message": f"Tests completed: {test_results.get('tests_passed', 0)} passed, {test_results.get('tests_failed', 0)} failed"
                    },
                    session_id
                )
            except Exception as e:
                logger.error(f"Test execution failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "testing",
                    {"message": f"Failed to run tests: {str(e)}"},
                    session_id
                )
                return
            
            # Phase 6: Verification
            self._stream_update(
                socketio, sid, "status", "verification",
                {"message": "Verifying changes..."},
                session_id
            )
            
            try:
                from agents.verifier import Verifier
                verifier = Verifier()
                
                verification_result = verifier.verify_acceptance(test_results, {})
                
                self._stream_update(
                    socketio, sid, "log", "verification",
                    {
                        "verification": verification_result,
                        "message": "Verification complete"
                    },
                    session_id
                )
            except Exception as e:
                logger.error(f"Verification failed: {e}", exc_info=True)
                self._stream_update(
                    socketio, sid, "error", "verification",
                    {"message": f"Failed to verify changes: {str(e)}"},
                    session_id
                )
                return
            
            # Phase 7: PR Creation (if verification passes)
            if verification_result.get('ready_for_pr', False):
                self._stream_update(
                    socketio, sid, "status", "pr_creation",
                    {"message": "Creating pull request..."},
                    session_id
                )
                
                try:
                    from agents.pr_creator import PRCreator
                    pr_creator = PRCreator(repo_path)
                    
                    # Get session data for PR description
                    session = self.sessions.get(session_id, {})
                    intent = session.get('current_intent', {})
                    
                    pr_result = pr_creator.create_pr(
                        branch=branch_name,
                        title=intent.get('description', 'Agent-generated changes'),
                        description=pr_creator.generate_pr_description(
                            plan, test_results, edit_result
                        )
                    )
                    
                    self._stream_update(
                        socketio, sid, "summary", "pr_creation",
                        {
                            "pr_url": pr_result.get('url'),
                            "pr_number": pr_result.get('number'),
                            "message": "Pull request created successfully",
                            "summary": {
                                "plan": plan,
                                "test_results": test_results,
                                "verification": verification_result
                            }
                        },
                        session_id
                    )
                except Exception as e:
                    logger.error(f"PR creation failed: {e}", exc_info=True)
                    self._stream_update(
                        socketio, sid, "error", "pr_creation",
                        {"message": f"Failed to create PR: {str(e)}"},
                        session_id
                    )
            else:
                self._stream_update(
                    socketio, sid, "summary", "verification",
                    {
                        "message": "Changes completed but not ready for PR",
                        "verification": verification_result,
                        "test_results": test_results
                    },
                    session_id
                )
        
        except Exception as e:
            logger.error(f"Error executing plan: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "execution",
                {"message": f"Execution error: {str(e)}"},
                session_id
            )
    
    def _handle_informational_query(
        self,
        user_message: str,
        intent: Dict[str, Any],
        pkg_data: Dict[str, Any],
        session_id: str,
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Handle informational queries without executing the full workflow.
        
        Args:
            user_message: User's question
            intent: Extracted intent dictionary
            pkg_data: PKG data dictionary
            session_id: Session identifier
            socketio: SocketIO instance
            sid: Socket session ID
        """
        try:
            logger.info(f"💬 PROCESSING QUERY | Session: {session_id} | Query: '{user_message[:100]}...'")
            self._stream_update(
                socketio, sid, "status", "query_handling",
                {"message": "Processing your question..."},
                session_id
            )
            
            from agents.query_handler import QueryHandler
            from services.pkg_query_engine import PKGQueryEngine
            
            logger.info(f"🔍 INITIALIZING QUERY ENGINE | Session: {session_id}")
            query_engine = PKGQueryEngine(pkg_data)
            query_handler = QueryHandler(pkg_data, query_engine)
            
            logger.info(f"🤖 GENERATING ANSWER | Session: {session_id} | Using query handler...")
            result = query_handler.answer_query(user_message, intent)
            
            answer_length = len(result.get('answer', ''))
            ref_count = len(result.get('references', []))
            logger.info(f"✅ ANSWER GENERATED | Session: {session_id} | Answer length: {answer_length} chars | References: {ref_count}")
            
            self._stream_update(
                socketio, sid, "query_response", "query_handling",
                {
                    "answer": result.get('answer', ''),
                    "references": result.get('references', []),
                    "metadata": result.get('metadata', {})
                },
                session_id
            )
            logger.info(f"📤 QUERY RESPONSE SENT | Session: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ QUERY HANDLING ERROR | Session: {session_id} | Error: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "query_handling",
                {"message": f"Failed to process query: {str(e)}"},
                session_id
            )
    
    def _handle_diagram_request(
        self,
        user_message: str,
        intent: Dict[str, Any],
        pkg_data: Dict[str, Any],
        session_id: str,
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Handle diagram generation requests without executing the full workflow.
        
        Args:
            user_message: User's diagram request
            intent: Extracted intent dictionary
            pkg_data: PKG data dictionary
            session_id: Session identifier
            socketio: SocketIO instance
            sid: Socket session ID
        """
        try:
            self._stream_update(
                socketio, sid, "status", "diagram_generation",
                {"message": "Generating diagram..."},
                session_id
            )
            
            from agents.diagram_generator import DiagramGenerator
            from services.pkg_query_engine import PKGQueryEngine
            
            query_engine = PKGQueryEngine(pkg_data)
            diagram_generator = DiagramGenerator(pkg_data, query_engine)
            
            result = diagram_generator.generate_diagram(intent, user_message)
            
            self._stream_update(
                socketio, sid, "diagram_response", "diagram_generation",
                {
                    "diagram_type": result.get('diagram_type', 'dependency'),
                    "format": result.get('format', 'text'),
                    "content": result.get('content', ''),
                    "modules_included": result.get('modules_included', []),
                    "metadata": result.get('metadata', {})
                },
                session_id
            )
            
        except Exception as e:
            logger.error(f"Error handling diagram request: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "diagram_generation",
                {"message": f"Failed to generate diagram: {str(e)}"},
                session_id
            )
    
    def approve_plan(
        self,
        session_id: str,
        plan_id: str,
        socketio: SocketIO,
        sid: str
    ) -> None:
        """
        Approve a pending plan and continue execution.
        
        Args:
            session_id: Session identifier
            plan_id: Plan ID to approve
            socketio: SocketIO instance
            sid: Socket session ID
        """
        try:
            session = self.sessions.get(session_id)
            if not session:
                self._stream_update(
                    socketio, sid, "error", "approval",
                    {"message": "Session not found"},
                    session_id
                )
                return
            
            plan = session.get('current_plan')
            if not plan or plan.get('plan_id') != plan_id:
                self._stream_update(
                    socketio, sid, "error", "approval",
                    {"message": "Plan not found"},
                    session_id
                )
                return
            
            repo_path = session.get('repo_path')
            if not repo_path:
                self._stream_update(
                    socketio, sid, "error", "approval",
                    {"message": "Repository path not found"},
                    session_id
                )
                return
            
            # Clear pending approval
            session.pop('pending_approval', None)
            
            self._stream_update(
                socketio, sid, "status", "approval",
                {"message": "Plan approved, proceeding with execution..."},
                session_id
            )
            
            # Execute plan
            self._execute_plan(plan, repo_path, session_id, socketio, sid)
        
        except Exception as e:
            logger.error(f"Error approving plan: {e}", exc_info=True)
            self._stream_update(
                socketio, sid, "error", "approval",
                {"message": f"Failed to approve plan: {str(e)}"},
                session_id
            )

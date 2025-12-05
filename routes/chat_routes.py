"""WebSocket chat routes for real-time communication with agents."""

import logging
import uuid
from datetime import datetime
from typing import Dict, Any, Optional
from flask import request
from flask_socketio import emit

logger = logging.getLogger(__name__)

# Store active sessions (in production, use Redis or database)
active_sessions: Dict[str, Dict[str, Any]] = {}


def register_chat_events(socketio):
    """
    Register all WebSocket event handlers with SocketIO.
    
    Args:
        socketio: SocketIO instance to register events with
    """
    
    @socketio.on('connect')
    def handle_connect():
        """Handle client WebSocket connection."""
        try:
            session_id = str(uuid.uuid4())
            client_ip = request.remote_addr
            origin = request.headers.get('Origin', 'unknown')
            
            logger.info(f"WebSocket connection attempt from {client_ip} (Origin: {origin})")
            
            # Store session information
            active_sessions[session_id] = {
                'session_id': session_id,
                'connected_at': datetime.utcnow().isoformat(),
                'client_ip': client_ip,
                'origin': origin,
                'sid': request.sid
            }
            
            # IMPORTANT: Emit connection confirmation immediately
            # Use callback to ensure it's sent
            emit('connected', {
                'session_id': session_id,
                'status': 'connected',
                'message': 'WebSocket connection established',
                'timestamp': datetime.utcnow().isoformat()
            }, callback=lambda: logger.debug(f"Connected event sent for session {session_id}"))
            
            logger.info(f"WebSocket connection established - Session ID: {session_id}, SID: {request.sid}")
            
            return True  # Accept the connection
            
        except Exception as e:
            logger.error(f"Error handling WebSocket connection: {e}", exc_info=True)
            try:
                emit('error', {
                    'type': 'connection_error',
                    'message': f'Failed to establish connection: {str(e)}',
                    'timestamp': datetime.utcnow().isoformat()
                })
            except:
                pass  # If we can't emit, at least log it
            return False  # Reject the connection
    
    
    @socketio.on('disconnect')
    def handle_disconnect(*args, **kwargs):
        """Handle client WebSocket disconnection."""
        try:
            sid = request.sid if hasattr(request, 'sid') else None
            
            if not sid:
                logger.warning("WebSocket disconnect called but no SID available")
                return
            
            # Find and remove session by SID
            session_to_remove = None
            for session_id, session_data in active_sessions.items():
                if session_data.get('sid') == sid:
                    session_to_remove = session_id
                    break
            
            if session_to_remove:
                session_data = active_sessions.pop(session_to_remove)
                logger.info(f"WebSocket disconnected - Session ID: {session_to_remove}, SID: {sid}")
            else:
                logger.warning(f"WebSocket disconnect for unknown SID: {sid}")
                
        except Exception as e:
            logger.error(f"Error handling WebSocket disconnection: {e}", exc_info=True)
    
    
    @socketio.on('chat_message')
    def handle_chat_message(data: Dict[str, Any]):
        """
        Handle incoming chat messages from clients.
        
        Expected payload:
        {
            "message": "User's message text",
            "repo_url": "https://github.com/user/repo.git" (optional),
            "session_id": "optional-session-uuid"
        }
        """
        try:
            # Extract message data
            message = data.get('message', '').strip()
            repo_url = data.get('repo_url', '').strip()
            session_id = data.get('session_id')
            sid = request.sid
            
            # Validate message
            if not message:
                emit('error', {
                    'type': 'validation_error',
                    'message': 'Message cannot be empty',
                    'timestamp': datetime.utcnow().isoformat()
                })
                logger.warning(f"Empty message received from SID: {sid}")
                return
            
            # Get or create session
            if not session_id:
                # Find session by SID
                for sid_key, session_data in active_sessions.items():
                    if session_data.get('sid') == sid:
                        session_id = sid_key
                        break
                
                # If still no session, create one
                if not session_id:
                    session_id = str(uuid.uuid4())
                    active_sessions[session_id] = {
                        'session_id': session_id,
                        'connected_at': datetime.utcnow().isoformat(),
                        'client_ip': request.remote_addr,
                        'sid': sid
                    }
            
            logger.info(f"📨 USER MESSAGE RECEIVED | Session: {session_id} | Message: {message[:100]}... | Length: {len(message)} chars")
            
            # Store repo_url and session info
            if repo_url:
                logger.info(f"🔗 REPO URL PROVIDED | Session: {session_id} | URL: {repo_url}")
                active_sessions[session_id]['repo_url'] = repo_url
                active_sessions[session_id]['repo_path'] = None  # Will be set when PKG is loaded
            else:
                logger.info(f"ℹ️  NO REPO URL | Session: {session_id} | Using existing session data if available")
            
            # Emit acknowledgment
            emit('agent_update', {
                'type': 'status',
                'data': {
                    'message': 'Message received and processing...',
                    'user_message': message,
                    'repo_url': repo_url if repo_url else None
                },
                'session_id': session_id,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Integrate with agent orchestrator
            try:
                logger.info(f"🚀 STARTING AGENT PROCESSING | Session: {session_id} | Processing user request...")
                from services.agent_orchestrator import AgentOrchestrator
                orchestrator = AgentOrchestrator()
                orchestrator.process_user_request(
                    session_id=session_id,
                    user_message=message,
                    repo_url=repo_url,
                    socketio=socketio,
                    sid=sid
                )
                logger.info(f"✅ AGENT PROCESSING COMPLETED | Session: {session_id}")
            except ImportError as e:
                logger.error(f"Failed to import agent orchestrator: {e}", exc_info=True)
                emit('error', {
                    'type': 'import_error',
                    'message': 'Agent orchestrator not available',
                    'timestamp': datetime.utcnow().isoformat()
                })
            except Exception as e:
                logger.error(f"Error processing with orchestrator: {e}", exc_info=True)
                emit('error', {
                    'type': 'processing_error',
                    'message': f'Failed to process request: {str(e)}',
                    'timestamp': datetime.utcnow().isoformat()
                })
            
        except KeyError as e:
            logger.error(f"Missing required field in chat message: {e}", exc_info=True)
            emit('error', {
                'type': 'validation_error',
                'message': f'Invalid message format: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            })
        except Exception as e:
            logger.error(f"Error handling chat message: {e}", exc_info=True)
            emit('error', {
                'type': 'processing_error',
                'message': f'Failed to process message: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            })
    
    
    @socketio.on('approve_plan')
    def handle_approve_plan(data: Dict[str, Any]):
        """
        Handle plan approval from user.
        
        Expected payload:
        {
            "session_id": "session-uuid",
            "plan_id": "plan-uuid" (optional)
        }
        """
        try:
            session_id = data.get('session_id')
            plan_id = data.get('plan_id')
            
            if not session_id:
                emit('error', {
                    'type': 'validation_error',
                    'message': 'session_id is required',
                    'timestamp': datetime.utcnow().isoformat()
                })
                return
            
            logger.info(f"Plan approval received - Session: {session_id}, Plan: {plan_id}")
            
            emit('agent_update', {
                'type': 'status',
                'data': {
                    'message': 'Plan approved, proceeding with execution...',
                    'plan_id': plan_id
                },
                'session_id': session_id,
                'timestamp': datetime.utcnow().isoformat()
            })
            
            # Integrate with agent orchestrator to proceed with plan execution
            try:
                from services.agent_orchestrator import AgentOrchestrator
                orchestrator = AgentOrchestrator()
                orchestrator.approve_plan(session_id, plan_id, socketio, request.sid)
            except Exception as e:
                logger.error(f"Error approving plan: {e}", exc_info=True)
                emit('error', {
                    'type': 'processing_error',
                    'message': f'Failed to approve plan: {str(e)}',
                    'timestamp': datetime.utcnow().isoformat()
                })
            
        except Exception as e:
            logger.error(f"Error handling plan approval: {e}", exc_info=True)
            emit('error', {
                'type': 'processing_error',
                'message': f'Failed to process approval: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            })
    
    
    @socketio.on('reject_plan')
    def handle_reject_plan(data: Dict[str, Any]):
        """
        Handle plan rejection from user.
        
        Expected payload:
        {
            "session_id": "session-uuid",
            "plan_id": "plan-uuid" (optional),
            "reason": "rejection reason" (optional)
        }
        """
        try:
            session_id = data.get('session_id')
            plan_id = data.get('plan_id')
            reason = data.get('reason', 'No reason provided')
            
            if not session_id:
                emit('error', {
                    'type': 'validation_error',
                    'message': 'session_id is required',
                    'timestamp': datetime.utcnow().isoformat()
                })
                return
            
            logger.info(f"Plan rejection received - Session: {session_id}, Plan: {plan_id}, Reason: {reason}")
            
            emit('agent_update', {
                'type': 'status',
                'data': {
                    'message': 'Plan rejected. Please provide new instructions.',
                    'plan_id': plan_id,
                    'reason': reason
                },
                'session_id': session_id,
                'timestamp': datetime.utcnow().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error handling plan rejection: {e}", exc_info=True)
            emit('error', {
                'type': 'processing_error',
                'message': f'Failed to process rejection: {str(e)}',
                'timestamp': datetime.utcnow().isoformat()
            })
    
    
    @socketio.on_error_default
    def default_error_handler(e):
        """Default error handler for unhandled WebSocket errors."""
        try:
            logger.error(f"Unhandled WebSocket error: {e}", exc_info=True)
            sid = request.sid if hasattr(request, 'sid') else None
            if sid:
                try:
                    emit('error', {
                        'type': 'unhandled_error',
                        'message': f'An unexpected error occurred: {str(e)}',
                        'timestamp': datetime.utcnow().isoformat()
                    })
                except Exception as emit_error:
                    logger.error(f"Failed to emit error to client {sid}: {emit_error}")
        except Exception as handler_error:
            logger.error(f"Error in default error handler: {handler_error}", exc_info=True)
    
    
    logger.info("Chat event handlers registered successfully")

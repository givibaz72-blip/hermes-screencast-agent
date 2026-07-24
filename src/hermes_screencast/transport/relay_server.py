"""
Relay server for remote desktop transport.

Routes messages between backend and Windows companion via pairing codes.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import logging
import os
import secrets
import shutil
import ssl
import sys
import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Dict, Optional, Set, Tuple

import websockets

logger = logging.getLogger(__name__)


class MessageType(str, Enum):
    """Message types for relay protocol."""
    # Companion -> Relay
    REGISTER = "register"
    HEARTBEAT = "heartbeat"
    RESPONSE = "response"
    ERROR = "error"
    DISCONNECT = "disconnect"
    
    # Backend -> Relay
    COMMAND = "command"
    CANCEL = "cancel"
    PAIR = "pair"
    
    # Relay -> Companion
    FORWARD_COMMAND = "forward_command"
    
    # Relay -> Backend
    FORWARD_RESPONSE = "forward_response"
    COMPANION_REGISTERED = "companion_registered"
    COMPANION_DISCONNECTED = "companion_disconnected"
    SESSION_ENDED = "session_ended"
    
    # Both directions
    PONG = "pong"


class PairingCodeStatus(str, Enum):
    """Status of a pairing code."""
    PENDING = "pending"
    USED = "used"
    EXPIRED = "expired"
    REVOKED = "revoked"


@dataclass
class PairingCode:
    """One-time pairing code for backend-companion binding."""
    code: str
    created_at: float
    expires_at: float
    status: PairingCodeStatus = PairingCodeStatus.PENDING
    
    def is_valid(self) -> bool:
        return self.status == PairingCodeStatus.PENDING and time.time() < self.expires_at
    
    def mark_used(self) -> None:
        self.status = PairingCodeStatus.USED
    
    def fingerprint(self) -> str:
        """Return short fingerprint for safe logging."""
        import hashlib
        return hashlib.sha256(self.code.encode()).hexdigest()[:12]


@dataclass
class BackendConnection:
    """A connected backend waiting for or paired with a companion."""
    backend_id: str
    websocket: Any
    pairing_code: Optional[str] = None
    companion_id: Optional[str] = None
    session_id: Optional[str] = None
    capability_token: Optional[str] = None
    connected_at: float = field(default_factory=time.time)
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)

def capability_fingerprint(token: str) -> str:
    """Return SHA-256 fingerprint of capability token; does not expose token characters."""
    if not token:
        return ""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()[:12]


@dataclass
class CompanionConnection:
    """A registered Windows companion."""
    companion_id: str
    websocket: Any
    pairing_code: Optional[str] = None
    session_id: Optional[str] = None
    capability_token: Optional[str] = None
    platform: str = "windows"
    version: str = "1.0.0"
    last_heartbeat: float = field(default_factory=time.time)
    pending_requests: Dict[str, asyncio.Future] = field(default_factory=dict)
    recording_sessions: Set[str] = field(default_factory=set)


class RelayServer:
    """
    WebSocket relay server for remote desktop transport.
    
    Coordinates connection between backend and Windows companion
    via one-time pairing codes.
    """
    
    def __init__(
        self,
        host: str = "127.0.0.1",
        port: int = 8765,
        ssl_cert: Optional[str] = None,
        ssl_key: Optional[str] = None,
        pairing_ttl: int = 300,
        session_ttl: int = 3600,
        admin_socket: Optional[str] = None,
        allow_public_bind: bool = False,
    ):
        self._validate_host(host, allow_public_bind, ssl_cert, ssl_key)
        
        self.host = host
        self.port = port
        self.ssl_cert = ssl_cert
        self.ssl_key = ssl_key
        self.pairing_ttl = pairing_ttl
        self.session_ttl = session_ttl
        self.admin_socket = admin_socket
        self.allow_public_bind = allow_public_bind
        
        # Pairing code management
        self._pairing_codes: Dict[str, PairingCode] = {}
        self._code_to_backend: Dict[str, str] = {}  # pairing_code -> backend_id
        self._code_to_companion: Dict[str, str] = {}  # pairing_code -> companion_id
        
        # Connection management
        self._backends: Dict[str, BackendConnection] = {}
        self._companions: Dict[str, CompanionConnection] = {}
        self._session_to_companion: Dict[str, str] = {}  # session_id -> companion_id
        self._session_to_backend: Dict[str, str] = {}  # session_id -> backend_id
        
        self._server: Optional[websockets.WebSocketServer] = None
        self._ssl_context: Optional[ssl.SSLContext] = None
        self._running = False
        self._cleanup_task: Optional[asyncio.Task] = None
        self._admin_task: Optional[asyncio.Task] = None
        self._admin_server: Optional[asyncio.Server] = None
    
    def _validate_host(
        self,
        host: str,
        allow_public_bind: bool,
        ssl_cert: Optional[str],
        ssl_key: Optional[str],
    ) -> None:
        """Validate host binding policy."""
        # Check for explicit public bind
        if host in ("0.0.0.0", "::", "::0"):
            if not allow_public_bind:
                raise ValueError(
                    f"Binding to {host} requires --allow-public-bind flag. "
                    f"Default is 127.0.0.1. For production, use reverse proxy with TLS."
                )
            if not ssl_cert or not ssl_key:
                raise ValueError(
                    "Public binding requires TLS certificate and key (--ssl-cert, --ssl-key)"
                )
        
        # Check for non-loopback addresses
        import ipaddress
        try:
            addr = ipaddress.ip_address(host)
            if not addr.is_loopback and not allow_public_bind:
                raise ValueError(
                    f"Binding to non-loopback address {host} requires --allow-public-bind flag"
                )
            if not addr.is_loopback and allow_public_bind and not (ssl_cert and ssl_key):
                raise ValueError("Public binding requires TLS certificate and key")
        except ValueError:
            raise
        except Exception:
            # If not a valid IP address, let it pass (could be hostname)
            pass
    
    def _create_ssl_context(self) -> ssl.SSLContext:
        """Create SSL context for TLS."""
        ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
        ctx.load_cert_chain(self.ssl_cert, self.ssl_key)
        # Require client certs? Not for now - we use pairing codes for auth
        return ctx
    
    def create_pairing_code(self, ttl: Optional[int] = None) -> PairingCode:
        """Create a new one-time pairing code."""
        ttl = ttl or self.pairing_ttl
        code = secrets.token_urlsafe(24)
        now = time.time()
        pc = PairingCode(
            code=code,
            created_at=now,
            expires_at=now + ttl,
        )
        self._pairing_codes[code] = pc
        return pc
    
    async def start(self) -> None:
        """Start the relay server."""
        if self.ssl_cert and self.ssl_key:
            self._ssl_context = self._create_ssl_context()
            logger.info(f"Starting relay server with TLS on {self.host}:{self.port}")
        else:
            logger.warning("Starting relay server WITHOUT TLS - only for local testing")
        
        self._running = True
        
        # Start WebSocket server
        self._server = await websockets.serve(
            self._handle_connection,
            self.host,
            self.port,
            ssl=self._ssl_context,
            ping_interval=20,
            ping_timeout=10,
        )
        
        # Start cleanup task
        self._cleanup_task = asyncio.create_task(self._cleanup_loop())
        
        # Start admin socket if configured
        if self.admin_socket:
            await self._start_admin_socket()
        
        logger.info(f"Relay server started on {self.host}:{self.port}")
    
    async def _start_admin_socket(self) -> None:
        """Start Unix domain socket for admin commands."""
        socket_path = Path(self.admin_socket)
        
        # Remove existing socket
        if socket_path.exists():
            socket_path.unlink()
        
        # Ensure directory exists with safe permissions
        socket_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        
        self._admin_server = await asyncio.start_unix_server(
            self._handle_admin_connection,
            path=self.admin_socket,
        )
        
        # Set socket permissions to 0600
        os.chmod(self.admin_socket, 0o600)
        
        logger.info(f"Admin socket listening on {self.admin_socket}")
    
    async def stop(self) -> None:
        """Stop the relay server."""
        self._running = False
        
        if self._cleanup_task:
            self._cleanup_task.cancel()
            try:
                await self._cleanup_task
            except asyncio.CancelledError:
                pass
        
        if self._admin_server:
            self._admin_server.close()
            await self._admin_server.wait_closed()
            if self.admin_socket and Path(self.admin_socket).exists():
                Path(self.admin_socket).unlink()
        
        if self._server:
            self._server.close()
            await self._server.wait_closed()
        
        # Close all connections
        for backend in self._backends.values():
            try:
                await backend.websocket.close()
            except Exception:
                pass
        for companion in self._companions.values():
            try:
                await companion.websocket.close()
            except Exception:
                pass
        
        logger.info("Relay server stopped")
    
    async def _handle_connection(self, websocket: Any) -> None:
        """Handle incoming WebSocket connection."""
        try:
            async for message in websocket:
                try:
                    data = json.loads(message)
                except json.JSONDecodeError:
                    await self._send_error(websocket, "Invalid JSON")
                    continue
                
                msg_type = data.get("type")
                
                if msg_type == MessageType.REGISTER.value:
                    await self._handle_companion_register(websocket, data)
                elif msg_type == MessageType.HEARTBEAT.value:
                    await self._handle_heartbeat(websocket, data)
                elif msg_type == MessageType.RESPONSE.value:
                    await self._handle_companion_response(websocket, data)
                elif msg_type == MessageType.ERROR.value:
                    await self._handle_error(websocket, data)
                elif msg_type == MessageType.DISCONNECT.value:
                    await self._handle_disconnect(websocket, data)
                elif msg_type == MessageType.PAIR.value:
                    await self._handle_backend_pair(websocket, data)
                elif msg_type == MessageType.COMMAND.value:
                    await self._handle_backend_command(websocket, data)
                elif msg_type == MessageType.CANCEL.value:
                    await self._handle_backend_cancel(websocket, data)
                else:
                    await self._send_error(websocket, f"Unknown message type: {msg_type}")
        except websockets.exceptions.ConnectionClosed:
            pass
        except Exception as e:
            logger.error(f"Connection handler error: {e}")
        finally:
            await self._cleanup_connection(websocket)
    
    async def _handle_companion_register(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle companion registration with pairing code."""
        pairing_code = data.get("pairing_code")
        companion_id = data.get("companion_id") or str(uuid.uuid4())
        platform = data.get("platform", "windows")
        version = data.get("version", "1.0.0")
        
        if not pairing_code:
            await self._send_error(websocket, "Missing pairing_code")
            return
        
        pc = self._pairing_codes.get(pairing_code)
        
        # Check if companion already registered with this code (before checking validity)
        existing_companion_id = self._code_to_companion.get(pairing_code)
        if existing_companion_id and existing_companion_id in self._companions:
            await self._send_error(websocket, "Pairing code already used")
            return
        
        if not pc or not pc.is_valid():
            await self._send_error(websocket, "Invalid or expired pairing code")
            return
        
        # Create capability token
        capability_token = secrets.token_urlsafe(32)
        
        # Register companion
        companion = CompanionConnection(
            companion_id=companion_id,
            websocket=websocket,
            pairing_code=pairing_code,
            capability_token=capability_token,
            platform=platform,
            version=version,
        )
        
        self._companions[companion_id] = companion
        self._code_to_companion[pairing_code] = companion_id
        pc.mark_used()
        
        # Notify waiting backend if any
        backend_id = self._code_to_backend.get(pairing_code)
        if backend_id and backend_id in self._backends:
            backend = self._backends[backend_id]
            backend.companion_id = companion_id
            backend.capability_token = capability_token
            
            await self._send(backend.websocket, {
                "type": MessageType.COMPANION_REGISTERED.value,
                "companion_id": companion_id,
                "capability_token": capability_token,
                "fingerprint": capability_fingerprint(capability_token),  # SHA-256 fingerprint; does not expose token characters
            })
            logger.info(f"Backend {backend_id} paired with companion {companion_id}")
        
        # Acknowledge companion
        await self._send(websocket, {
            "type": MessageType.REGISTER.value,
            "success": True,
            "companion_id": companion_id,
            "capability_token": capability_token,
        })
        
        logger.info(f"Companion registered: {companion_id} (pairing: {pc.fingerprint()})")
    
    async def _handle_heartbeat(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle heartbeat from companion."""
        companion_id = data.get("companion_id")
        if companion_id and companion_id in self._companions:
            self._companions[companion_id].last_heartbeat = time.time()
            await self._send(websocket, {"type": MessageType.PONG.value})
    
    async def _handle_companion_response(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle response from companion to a command."""
        request_id = data.get("request_id")
        if not request_id:
            return
        
        # Find which backend has this pending request
        for backend in self._backends.values():
            if request_id in backend.pending_requests:
                future = backend.pending_requests.pop(request_id)
                if not future.done():
                    future.set_result(data)
                break
    
    async def _handle_error(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle error from companion."""
        request_id = data.get("request_id")
        error = data.get("error", "Unknown error")
        
        for backend in self._backends.values():
            if request_id in backend.pending_requests:
                future = backend.pending_requests.pop(request_id)
                if not future.done():
                    future.set_exception(Exception(error))
                break
    
    async def _handle_disconnect(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle explicit companion disconnect."""
        companion_id = data.get("companion_id")
        if companion_id:
            await self._unregister_companion(companion_id)
    
    async def _handle_backend_pair(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle backend pairing with pairing code."""
        pairing_code = data.get("pairing_code")
        backend_id = data.get("backend_id", str(uuid.uuid4()))
        
        if not pairing_code:
            await self._send_error(websocket, "Missing pairing_code")
            return
        
        pc = self._pairing_codes.get(pairing_code)
        if not pc or pc.status != PairingCodeStatus.PENDING:
            await self._send_error(websocket, "Invalid or expired pairing code")
            return
        
        # Create backend connection record
        backend = BackendConnection(
            backend_id=backend_id,
            websocket=websocket,
            pairing_code=pairing_code,
        )
        self._backends[backend_id] = backend
        self._code_to_backend[pairing_code] = backend_id
        
        # Check if companion already registered
        existing_companion_id = self._code_to_companion.get(pairing_code)
        if existing_companion_id and existing_companion_id in self._companions:
            # Companion already waiting, complete pairing immediately
            companion = self._companions[existing_companion_id]
            companion.capability_token = secrets.token_urlsafe(32)
            
            backend.companion_id = existing_companion_id
            backend.capability_token = companion.capability_token
            
            await self._send(websocket, {
                "type": MessageType.COMPANION_REGISTERED.value,
                "companion_id": existing_companion_id,
                "capability_token": companion.capability_token,
                "fingerprint": capability_fingerprint(companion.capability_token),
            })
            logger.info(f"Backend {backend_id} immediately paired with companion {existing_companion_id}")
        else:
            # Wait for companion
            await self._send(websocket, {
                "type": MessageType.PAIR.value,
                "success": True,
                "backend_id": backend_id,
                "status": "waiting_for_companion",
            })
            logger.info(f"Backend {backend_id} waiting for companion (pairing: {pc.fingerprint()})")
    
    async def _unregister_companion(self, companion_id: str) -> None:
        """Unregister a companion and clean up."""
        companion = self._companions.pop(companion_id, None)
        if not companion:
            return
        
        # Clean up pairing code mappings
        if companion.pairing_code:
            self._code_to_companion.pop(companion.pairing_code, None)
            pc = self._pairing_codes.get(companion.pairing_code)
            if pc:
                pc.status = PairingCodeStatus.REVOKED
        
        # Clean up session mappings
        if companion.session_id:
            self._session_to_companion.pop(companion.session_id, None)
            backend_id = self._session_to_backend.pop(companion.session_id, None)
            if backend_id and backend_id in self._backends:
                backend = self._backends[backend_id]
                backend.session_id = None
                backend.capability_token = None
        
        # Cancel pending requests
        for future in companion.pending_requests.values():
            if not future.done():
                future.cancel()
        
        # Notify backend of disconnect
        if companion.pairing_code:
            backend_id = self._code_to_backend.get(companion.pairing_code)
            if backend_id and backend_id in self._backends:
                backend = self._backends[backend_id]
                try:
                    await self._send(backend.websocket, {
                        "type": MessageType.COMPANION_DISCONNECTED.value,
                        "companion_id": companion_id,
                        "session_id": companion.session_id,
                    })
                except Exception:
                    pass
        
        # Stop any recording sessions
        for session_id in companion.recording_sessions:
            logger.warning(f"Companion disconnected during recording: {session_id}")
        
        logger.info(f"Companion unregistered: {companion_id}")
    
    async def _cleanup_connection(self, websocket: Any) -> None:
        """Clean up connection state on disconnect."""
        # Check if it was a companion
        for companion_id, companion in list(self._companions.items()):
            if companion.websocket == websocket:
                await self._unregister_companion(companion_id)
                break
        
        # Check if it was a backend
        for backend_id, backend in list(self._backends.items()):
            if backend.websocket == websocket:
                # Clean up pairing code mapping
                if backend.pairing_code:
                    self._code_to_backend.pop(backend.pairing_code, None)
                del self._backends[backend_id]
                break
    
    async def _cleanup_loop(self) -> None:
        """Periodic cleanup of expired pairing codes and stale connections."""
        while self._running:
            try:
                now = time.time()
                
                # Clean expired pairing codes (by time only, not by USED status)
                expired_codes = [
                    code for code, pc in self._pairing_codes.items()
                    if now > pc.expires_at
                ]
                for code in expired_codes:
                    if code in self._code_to_backend:
                        backend_id = self._code_to_backend.pop(code)
                        if backend_id in self._backends:
                            try:
                                await self._send(self._backends[backend_id].websocket, {
                                    "type": "error",
                                    "error": "Pairing code expired",
                                })
                            except Exception:
                                pass
                    if code in self._code_to_companion:
                        self._code_to_companion.pop(code, None)
                    del self._pairing_codes[code]
                
                # Clean stale companions (no heartbeat)
                stale_companions = [
                    cid for cid, c in self._companions.items()
                    if now - c.last_heartbeat > 60
                ]
                for cid in stale_companions:
                    logger.warning(f"Companion stale, disconnecting: {cid}")
                    await self._unregister_companion(cid)
                
                # Clean stale backends
                stale_backends = [
                    bid for bid, b in self._backends.items()
                    if now - b.connected_at > self.session_ttl
                ]
                for bid in stale_backends:
                    del self._backends[bid]
                
            except Exception as e:
                logger.error(f"Cleanup loop error: {e}")
            
            await asyncio.sleep(10)
    
    # Admin socket handlers
    async def _handle_admin_connection(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter
    ) -> None:
        """Handle admin socket connection."""
        try:
            data = await reader.read(4096)
            request = json.loads(data.decode())
            cmd = request.get("command")
            
            if cmd == "create-pairing":
                ttl = request.get("ttl", self.pairing_ttl)
                pc = self.create_pairing_code(ttl)
                response = {
                    "success": True,
                    "pairing_code": pc.code,
                    "fingerprint": pc.fingerprint(),
                    "expires_at": pc.expires_at,
                }
            elif cmd == "list-pairings":
                response = {
                    "success": True,
                    "pairings": [
                        {
                            "fingerprint": pc.fingerprint(),
                            "created_at": pc.created_at,
                            "expires_at": pc.expires_at,
                            "status": pc.status.value,
                        }
                        for pc in self._pairing_codes.values()
                    ],
                }
            elif cmd == "doctor":
                response = await self._doctor_check(request)
            else:
                response = {"success": False, "error": f"Unknown command: {cmd}"}
            
            writer.write(json.dumps(response).encode())
            await writer.drain()
        except Exception as e:
            logger.error(f"Admin connection error: {e}")
        finally:
            writer.close()
            await writer.wait_closed()
    
    async def _doctor_check(self, request: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Comprehensive health check for relay server."""
        request = request or {}
        checks = {}
        all_ok = True
        
        # TLS certificate check
        tls_ok, tls_reason = self._check_tls_certificate()
        checks["tls_certificate"] = {"ok": tls_ok, "reason": tls_reason}
        if not tls_ok:
            all_ok = False
        
        # TLS key check
        key_ok, key_reason = self._check_tls_key()
        checks["tls_key"] = {"ok": key_ok, "reason": key_reason}
        if not key_ok:
            all_ok = False
        
        # Certificate/key match
        match_ok, match_reason = self._check_cert_key_match()
        checks["certificate_match"] = {"ok": match_ok, "reason": match_reason}
        if not match_ok:
            all_ok = False
        
        # Certificate validity period
        valid_ok, valid_reason = self._check_cert_validity(request.get("expected_hostname"))
        checks["certificate_validity"] = {"ok": valid_ok, "reason": valid_reason}
        if not valid_ok:
            all_ok = False
        
        # Port availability
        port_ok, port_reason = self._check_port_available()
        checks["port_available"] = {"ok": port_ok, "reason": port_reason}
        if not port_ok:
            all_ok = False
        
        # Admin socket
        admin_ok, admin_reason = self._check_admin_socket()
        checks["admin_socket"] = {"ok": admin_ok, "reason": admin_reason}
        if not admin_ok:
            all_ok = False
        
        # Disk space
        disk_ok, disk_reason = self._check_disk_space()
        checks["disk_space"] = {"ok": disk_ok, "reason": disk_reason}
        if not disk_ok:
            all_ok = False
        
        # WebSockets dependency
        ws_ok = True
        try:
            import websockets
        except ImportError:
            ws_ok = False
        checks["websockets"] = {"ok": ws_ok, "reason": "websockets module importable" if ws_ok else "websockets not installed"}
        if not ws_ok:
            all_ok = False
        
        # TTL validation
        ttl_ok, ttl_reason = self._check_ttl_values()
        checks["ttl_values"] = {"ok": ttl_ok, "reason": ttl_reason}
        if not ttl_ok:
            all_ok = False
        
        return {
            "success": all_ok,
            "checks": checks,
            "pairing_codes_active": len(self._pairing_codes),
            "companions_connected": len(self._companions),
            "backends_connected": len(self._backends),
        }
    
    def _check_tls_certificate(self) -> Tuple[bool, str]:
        """Check SSL certificate file."""
        if not self.ssl_cert:
            return False, "No SSL certificate configured"
        
        cert_path = Path(self.ssl_cert)
        if not cert_path.exists():
            return False, f"Certificate file not found: {self.ssl_cert}"
        if not cert_path.is_file():
            return False, f"Certificate path is not a file: {self.ssl_cert}"
        
        try:
            with open(cert_path, 'rb') as f:
                cert_data = f.read()
            cert = ssl._ssl._test_decode_cert(cert_data)
            return True, "Certificate file is readable and parseable"
        except Exception as e:
            return False, f"Certificate not parseable: {e}"
    
    def _check_tls_key(self) -> Tuple[bool, str]:
        """Check SSL private key file."""
        if not self.ssl_key:
            return False, "No SSL key configured"
        
        key_path = Path(self.ssl_key)
        if not key_path.exists():
            return False, f"Key file not found: {self.ssl_key}"
        if not key_path.is_file():
            return False, f"Key path is not a file: {self.ssl_key}"
        
        try:
            with open(key_path, 'rb') as f:
                key_data = f.read()
            # Try to load it
            ssl._ssl._test_decode_cert(key_data)  # This will fail for key, but we just check readability
            return True, "Key file is readable"
        except Exception as e:
            return False, f"Key not readable: {e}"
    
    def _check_cert_key_match(self) -> Tuple[bool, str]:
        """Check if certificate and key match."""
        if not self.ssl_cert or not self.ssl_key:
            return False, "Both certificate and key required"
        
        try:
            ctx = ssl.create_default_context(ssl.Purpose.CLIENT_AUTH)
            ctx.load_cert_chain(self.ssl_cert, self.ssl_key)
            return True, "Certificate and key match"
        except Exception as e:
            return False, f"Certificate and key do not match: {e}"
    
    def _check_cert_validity(self, expected_hostname: Optional[str] = None) -> Tuple[bool, str]:
        """Check certificate validity period and SAN."""
        if not self.ssl_cert:
            return False, "No certificate configured"
        
        try:
            cert_path = Path(self.ssl_cert)
            with open(cert_path, 'rb') as f:
                cert_data = f.read()
            cert = ssl._ssl._test_decode_cert(cert_data)
            
            # Check notBefore/notAfter
            import datetime
            not_before = datetime.datetime.strptime(cert['notBefore'], '%b %d %H:%M:%S %Y %Z')
            not_after = datetime.datetime.strptime(cert['notAfter'], '%b %d %H:%M:%S %Y %Z')
            now = datetime.datetime.utcnow()
            
            if now < not_before:
                return False, f"Certificate not yet valid (starts {not_before})"
            if now > not_after:
                return False, f"Certificate expired ({not_after})"
            
            # Check SAN if hostname provided
            if expected_hostname:
                san = cert.get('subjectAltName', [])
                dns_names = [v for k, v in san if k == 'DNS']
                if expected_hostname not in dns_names:
                    # Check CN as fallback
                    cn = ''
                    for attr in cert.get('subject', []):
                        for k, v in attr:
                            if k == 'commonName':
                                cn = v
                                break
                    if expected_hostname != cn:
                        return False, f"Certificate does not cover hostname {expected_hostname}"
            
            return True, f"Certificate valid until {not_after}"
        except Exception as e:
            return False, f"Could not verify certificate validity: {e}"
    
    def _check_port_available(self) -> Tuple[bool, str]:
        """Check if relay port is available (or already bound by us)."""
        import socket
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
                s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
                s.bind((self.host, self.port))
                return True, f"Port {self.port} available"
        except OSError as e:
            if e.errno == 98:  # Address already in use
                # Check if it's our server
                if self._server and self._server.sockets:
                    return True, f"Port {self.port} already bound by this server"
                return False, f"Port {self.port} already in use: {e}"
            return False, f"Port check failed: {e}"
    
    def _check_admin_socket(self) -> Tuple[bool, str]:
        """Check admin socket directory and permissions."""
        if not self.admin_socket:
            return True, "Admin socket not configured (optional)"
        
        socket_path = Path(self.admin_socket)
        
        # Check directory
        if not socket_path.parent.exists():
            return False, f"Admin socket directory does not exist: {socket_path.parent}"
        
        # Check directory permissions
        try:
            dir_stat = socket_path.parent.stat()
            if dir_stat.st_mode & 0o077:
                return False, f"Admin socket directory has group/other permissions: {oct(dir_stat.st_mode)}"
        except OSError:
            return False, f"Cannot stat admin socket directory: {socket_path.parent}"
        
        # Check socket file if exists
        if socket_path.exists():
            if socket_path.is_symlink():
                return False, "Admin socket is a symlink (security risk)"
            try:
                sock_stat = socket_path.stat()
                if sock_stat.st_mode & 0o077:
                    return False, f"Admin socket has group/other permissions: {oct(sock_stat.st_mode)}"
            except OSError:
                return False, "Cannot stat admin socket file"
        
        return True, "Admin socket directory permissions OK"
    
    def _check_disk_space(self) -> Tuple[bool, str]:
        """Check available disk space."""
        try:
            total, used, free = shutil.disk_usage("/")
            free_gb = free / (1024**3)
            if free_gb < 1:
                return False, f"Low disk space: {free_gb:.1f} GB free"
            return True, f"Disk space OK: {free_gb:.1f} GB free"
        except Exception as e:
            return False, f"Disk space check failed: {e}"
    
    def _check_ttl_values(self) -> Tuple[bool, str]:
        """Check TTL values are reasonable."""
        if self.pairing_ttl <= 0 or self.pairing_ttl > 86400:
            return False, f"Pairing TTL out of range (1-86400s): {self.pairing_ttl}"
        if self.session_ttl <= 0 or self.session_ttl > 604800:
            return False, f"Session TTL out of range (1-604800s): {self.session_ttl}"
        return True, f"TTLs OK: pairing={self.pairing_ttl}s, session={self.session_ttl}s"
    
    async def _send(self, websocket: Any, data: Dict[str, Any]) -> None:
        """Send JSON message over WebSocket."""
        try:
            await websocket.send(json.dumps(data))
        except Exception as e:
            logger.error(f"Failed to send message: {e}")
    
    async def _send_error(self, websocket: Any, error: str) -> None:
        """Send error message."""
        await self._send(websocket, {
            "type": MessageType.ERROR.value,
            "error": error,
        })
    
    async def _handle_backend_command(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle command from backend to companion."""
        session_id = data.get("session_id")
        capability_token = data.get("capability_token")
        request_id = data.get("request_id", str(uuid.uuid4()))
        
        if not session_id:
            await self._send_error(websocket, "Missing session_id")
            return
        
        if not capability_token:
            await self._send_error(websocket, "Missing capability_token")
            return
        
        # Find companion by session
        companion_id = self._session_to_companion.get(session_id)
        if not companion_id or companion_id not in self._companions:
            await self._send_error(websocket, f"No companion for session: {session_id}")
            return
        
        companion = self._companions[companion_id]
        
        # Validate capability token
        if companion.capability_token != capability_token:
            await self._send_error(websocket, "Invalid capability token")
            return
        
        # Find the backend that owns this session
        backend_id = self._session_to_backend.get(session_id)
        if not backend_id or backend_id not in self._backends:
            await self._send_error(websocket, f"No backend for session: {session_id}")
            return
        
        backend = self._backends[backend_id]
        
        # Store future for response in BACKEND (not companion)
        future = asyncio.get_event_loop().create_future()
        backend.pending_requests[request_id] = future
        
        # Forward command to companion
        await self._send(companion.websocket, {
            "type": MessageType.FORWARD_COMMAND.value,
            "request_id": request_id,
            "command": data.get("command"),
            "payload": data.get("payload", {}),
        })
        
        try:
            # Wait for response with timeout
            response_data = await asyncio.wait_for(future, timeout=30.0)
            await self._send(websocket, {
                "type": MessageType.FORWARD_RESPONSE.value,
                "request_id": request_id,
                "success": response_data.get("success", False),
                "payload": response_data.get("payload", {}),
                "error": response_data.get("error"),
            })
        except asyncio.TimeoutError:
            backend.pending_requests.pop(request_id, None)
            await self._send(websocket, {
                "type": MessageType.FORWARD_RESPONSE.value,
                "request_id": request_id,
                "success": False,
                "error": "Command timeout",
            })
        except Exception as e:
            backend.pending_requests.pop(request_id, None)
            await self._send(websocket, {
                "type": MessageType.FORWARD_RESPONSE.value,
                "request_id": request_id,
                "success": False,
                "error": str(e),
            })
    
    async def _handle_backend_cancel(
        self,
        websocket: Any,
        data: Dict[str, Any]
    ) -> None:
        """Handle command cancellation from backend."""
        request_id = data.get("request_id")
        if not request_id:
            return
        
        for companion in self._companions.values():
            if request_id in companion.pending_requests:
                future = companion.pending_requests.pop(request_id)
                if not future.done():
                    future.cancel()
                break


async def run_relay_server(
    host: str = "127.0.0.1",
    port: int = 8765,
    ssl_cert: Optional[str] = None,
    ssl_key: Optional[str] = None,
    admin_socket: Optional[str] = None,
    pairing_ttl: int = 300,
    session_ttl: int = 3600,
    allow_public_bind: bool = False,
) -> None:
    """Run the relay server."""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    
    server = RelayServer(
        host=host,
        port=port,
        ssl_cert=ssl_cert,
        ssl_key=ssl_key,
        pairing_ttl=pairing_ttl,
        session_ttl=session_ttl,
        admin_socket=admin_socket,
        allow_public_bind=allow_public_bind,
    )
    
    try:
        await server.start()
        while True:
            await asyncio.sleep(1)
    except KeyboardInterrupt:
        pass
    finally:
        await server.stop()


def _build_cli_parser() -> argparse.ArgumentParser:
    """Build CLI argument parser."""
    parser = argparse.ArgumentParser(description="Hermes Relay Server")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=8765, help="Port to listen")
    parser.add_argument("--ssl-cert", help="SSL certificate file")
    parser.add_argument("--ssl-key", help="SSL key file")
    parser.add_argument("--admin-socket", help="Unix socket for admin commands")
    parser.add_argument("--pairing-ttl", type=int, default=300, help="Pairing code TTL seconds")
    parser.add_argument("--session-ttl", type=int, default=3600, help="Session TTL seconds")
    parser.add_argument("--allow-public-bind", action="store_true", 
                       help="Allow binding to 0.0.0.0 or non-loopback (requires TLS)")
    
    subparsers = parser.add_subparsers(dest="subcommand", help="Admin commands")
    
    # create-pairing
    create_parser = subparsers.add_parser("create-pairing", help="Create a pairing code")
    create_parser.add_argument("--ttl", type=int, default=300, help="TTL in seconds")
    create_parser.add_argument("--admin-socket", required=True, help="Admin socket path")
    create_parser.add_argument("--output", help="Write pairing code to file (mode 0600)")
    create_parser.add_argument("--force", action="store_true", help="Overwrite output file if exists")
    create_parser.add_argument("--json", action="store_true", help="Output JSON instead of plain code")
    
    # doctor
    doctor_parser = subparsers.add_parser("doctor", help="Health check")
    doctor_parser.add_argument("--ssl-cert", help="SSL certificate")
    doctor_parser.add_argument("--ssl-key", help="SSL key")
    doctor_parser.add_argument("--admin-socket", required=True, help="Admin socket path")
    doctor_parser.add_argument("--expected-hostname", help="Expected hostname for certificate SAN check")
    doctor_parser.add_argument("--json", action="store_true", help="Output JSON")
    
    return parser


async def _run_admin_create_pairing(args) -> int:
    """Run create-pairing admin command."""
    reader, writer = await asyncio.open_unix_connection(args.admin_socket)
    writer.write(json.dumps({"command": "create-pairing", "ttl": args.ttl}).encode())
    await writer.drain()
    response = json.loads((await reader.read(4096)).decode())
    writer.close()
    await writer.wait_closed()
    
    if not response.get("success"):
        print(f"Error: {response.get('error')}", file=sys.stderr)
        return 1
    
    pairing_code = response["pairing_code"]
    
    if args.output:
        output_path = Path(args.output)
        if output_path.exists() and not args.force:
            print(f"Error: Output file exists (use --force): {args.output}", file=sys.stderr)
            return 1
        
        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(pairing_code + "\n")
        output_path.chmod(0o600)
        print(f"Pairing code written to {args.output} (mode 0600)")
    elif args.json:
        print(json.dumps(response, indent=2))
    else:
        print(pairing_code)
    
    return 0


async def _run_admin_doctor(args) -> int:
    """Run doctor admin command."""
    reader, writer = await asyncio.open_unix_connection(args.admin_socket)
    request = {"command": "doctor"}
    if args.expected_hostname:
        request["expected_hostname"] = args.expected_hostname
    writer.write(json.dumps(request).encode())
    await writer.drain()
    response = json.loads((await reader.read(8192)).decode())
    writer.close()
    await writer.wait_closed()
    
    if args.json:
        print(json.dumps(response, indent=2))
    else:
        if response.get("success"):
            print("✓ All checks passed")
        else:
            print("✗ Some checks failed")
        for check_name, check_data in response.get("checks", {}).items():
            status = "✓" if check_data.get("ok") else "✗"
            print(f"  {status} {check_name}: {check_data.get('reason')}")
    
    return 0 if response.get("success") else 1


async def _main_async() -> int:
    """Main async entry point."""
    parser = _build_cli_parser()
    args = parser.parse_args()
    
    if args.subcommand == "create-pairing":
        return await _run_admin_create_pairing(args)
    elif args.subcommand == "doctor":
        return await _run_admin_doctor(args)
    else:
        await run_relay_server(
            host=args.host,
            port=args.port,
            ssl_cert=args.ssl_cert,
            ssl_key=args.ssl_key,
            admin_socket=args.admin_socket,
            pairing_ttl=args.pairing_ttl,
            session_ttl=args.session_ttl,
            allow_public_bind=args.allow_public_bind,
        )
    return 0


def main() -> int:
    """Main entry point."""
    return asyncio.run(_main_async())


if __name__ == "__main__":
    sys.exit(main())
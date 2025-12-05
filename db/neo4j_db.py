"""Neo4j database operations for storing and querying PKG data."""

import json
import os
import logging
import time
from contextlib import contextmanager
from typing import Dict, Any, List, Optional
from dotenv import load_dotenv
from neo4j import GraphDatabase, Session, Transaction

# Load .env file
load_dotenv()

# Configure logging
logger = logging.getLogger(__name__)

# Read env vars
uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE", "repos")
max_retries = int(os.getenv("NEO4J_MAX_RETRIES", "3"))
retry_delay = float(os.getenv("NEO4J_RETRY_DELAY", "1.0"))
batch_size = int(os.getenv("NEO4J_BATCH_SIZE", "1000"))

# Global driver instance
driver: Optional[GraphDatabase.driver] = None


def _initialize_driver() -> Optional[GraphDatabase.driver]:
    """
    Initialize Neo4j driver with retry logic.
    
    Returns:
        Driver instance or None if connection fails
    """
    global driver
    
    if not uri or not user or not password:
        logger.warning("Neo4j credentials not configured. Skipping Neo4j initialization.")
        return None
    
    for attempt in range(max_retries):
        try:
            driver = GraphDatabase.driver(uri, auth=(user, password))
            driver.verify_connectivity()
            logger.info(f"Neo4j connection established to {uri}")
            
            # Create indexes for better query performance
            _create_indexes(driver)
            
            return driver
        except Exception as e:
            logger.warning(f"Neo4j connection attempt {attempt + 1}/{max_retries} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(retry_delay * (2 ** attempt))  # Exponential backoff
            else:
                logger.error(f"Failed to connect to Neo4j after {max_retries} attempts")
                return None
    
    return None


def _create_indexes(driver_instance: GraphDatabase.driver) -> None:
    """Create indexes on frequently queried properties."""
    try:
        with driver_instance.session() as session:
            # Indexes for nodes
            session.run("CREATE INDEX IF NOT EXISTS FOR (p:Project) ON (p.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (m:Module) ON (m.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (s:Symbol) ON (s.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (e:Endpoint) ON (e.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (f:Feature) ON (f.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (pkg:Package) ON (pkg.id)")
            session.run("CREATE INDEX IF NOT EXISTS FOR (d:Document) ON (d.url)")
            
            logger.info("Neo4j indexes created/verified")
    except Exception as e:
        logger.warning(f"Failed to create indexes: {e}")


def verify_connection() -> bool:
    """
    Verify Neo4j connection is healthy.
    
    Returns:
        True if connection is healthy, False otherwise
    """
    global driver
    
    if driver is None:
        logger.debug("Neo4j driver not initialized, attempting initialization...")
        driver = _initialize_driver()
    
    if driver is None:
        logger.warning("Neo4j driver initialization failed. Check NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD environment variables.")
        return False
    
    try:
        driver.verify_connectivity()
        logger.debug("Neo4j connection verified successfully")
        return True
    except Exception as e:
        logger.error(f"Neo4j connection verification failed: {e}")
        driver = None  # Reset driver to force re-initialization
        return False


@contextmanager
def get_session():
    """
    Context manager for Neo4j sessions with automatic error handling.
    
    Yields:
        Session instance
    """
    global driver
    
    if driver is None:
        driver = _initialize_driver()
    
    if driver is None:
        raise ConnectionError("Neo4j driver not initialized. Check connection settings.")
    session = driver.session(database=database)
    try:
        yield session
    except Exception as e:
        logger.error(f"Neo4j session error: {e}", exc_info=True)
        raise
    finally:
        session.close()


def _store_package_tx(tx: Transaction, pkg: Dict[str, Any]) -> None:
    """Transaction function to store Package node."""
    tx.run("""
        MERGE (p:Package {id: $project_id})
        SET p.version = $version,
            p.generatedAt = $generatedAt,
            p.gitSha = $gitSha,
            p.timestamp = datetime()
    """, {
        "project_id": pkg["project"]["id"],
        "version": pkg.get("version", "1.0.0"),
        "generatedAt": pkg.get("generatedAt"),
        "gitSha": pkg.get("gitSha")
    })


def _store_project_tx(tx: Transaction, pkg: Dict[str, Any]) -> None:
    """Transaction function to store Project node and metadata."""
    project = pkg["project"]
    project_id = project["id"]
    
    # Create Project node
    tx.run("""
        MERGE (proj:Project {id: $project_id})
        SET proj.name = $name,
            proj.rootPath = $rootPath,
            proj.languages = $languages
    """, {
        "project_id": project_id,
        "name": project.get("name", ""),
        "rootPath": project.get("rootPath", ""),
        "languages": project.get("languages", [])
    })
    
    # Create Metadata node
    tx.run("""
        MERGE (m:Metadata {projectId: $project_id})
        SET m += $metadata
    """, {
        "project_id": project_id,
        "metadata": project.get("metadata", {})
    })
    
    # Connect Project -> Metadata
    tx.run("""
        MATCH (proj:Project {id: $project_id})
        MATCH (m:Metadata {projectId: $project_id})
        MERGE (proj)-[:HAS_METADATA]->(m)
    """, {"project_id": project_id})


def _store_modules_tx(tx: Transaction, modules: List[Dict[str, Any]], project_id: str) -> None:
    """Transaction function to store modules using UNWIND batch operation."""
    if not modules:
        return
    
    # Prepare module data for batch insert
    module_data = []
    for m in modules:
        module_id = m.get("id")
        if not module_id:
            logger.warning(f"Skipping module - missing id: {m}")
            continue
        
        # Filter out None values
        module_props = {k: v for k, v in m.items() if v is not None and k != "id"}
        module_data.append({
            "id": module_id,
            "data": module_props,
            "projectId": project_id
        })
    
    if not module_data:
        return
    
    # Batch insert using UNWIND
    tx.run("""
        UNWIND $modules AS module
        MERGE (mod:Module {id: module.id})
        SET mod += module.data
        WITH mod, module.projectId AS projectId
        MATCH (proj:Project {id: projectId})
        MERGE (proj)-[:HAS_MODULE]->(mod)
    """, {"modules": module_data})


def _store_symbols_tx(tx: Transaction, symbols: List[Dict[str, Any]], project_id: str) -> None:
    """Transaction function to store symbols using UNWIND batch operation."""
    if not symbols:
        return
    
    # Prepare symbol data for batch insert
    symbol_data = []
    for s in symbols:
        symbol_id = s.get("id")
        if not symbol_id:
            # Fallback to name if id not available (for backward compatibility)
            symbol_id = s.get("name")
            if not symbol_id:
                logger.warning(f"Skipping symbol - missing id and name: {s}")
                continue
        
        # Filter out None values
        symbol_props = {k: v for k, v in s.items() if v is not None and k not in ["id", "name"]}
        symbol_data.append({
            "id": symbol_id,
            "name": s.get("name", ""),
            "data": symbol_props,
            "projectId": project_id
        })
    
    if not symbol_data:
        return
    
    # Batch insert using UNWIND - using id as identifier
    tx.run("""
        UNWIND $symbols AS symbol
        MERGE (sym:Symbol {id: symbol.id})
        SET sym.name = symbol.name,
            sym += symbol.data
        WITH sym, symbol.projectId AS projectId
        MATCH (proj:Project {id: projectId})
        MERGE (proj)-[:HAS_SYMBOL]->(sym)
    """, {"symbols": symbol_data})

def _store_endpoints_tx(tx: Transaction, endpoints: List[Dict[str, Any]], project_id: str) -> None:
    """Transaction function to store endpoints using UNWIND batch operation."""
    if not endpoints:
        return
    
    # Prepare endpoint data for batch insert
    endpoint_data = []
    for e in endpoints:
        endpoint_id = e.get("id")
        path = e.get("path")
        if not endpoint_id and not path:
            logger.warning(f"Skipping endpoint - missing id and path: {e}")
            continue
        
        # Use id if available, otherwise use path
        identifier = endpoint_id if endpoint_id else path
        
        # Filter out None values
        endpoint_props = {k: v for k, v in e.items() if v is not None and k not in ["id", "path"]}
        endpoint_data.append({
            "id": identifier,
            "path": path or identifier,
            "data": endpoint_props,
            "projectId": project_id
        })
    
    if not endpoint_data:
        return
    
    # Batch insert using UNWIND
    tx.run("""
        UNWIND $endpoints AS endpoint
        MERGE (end:Endpoint {id: endpoint.id})
        SET end.path = endpoint.path,
            end += endpoint.data
        WITH end, endpoint.projectId AS projectId
        MATCH (proj:Project {id: projectId})
        MERGE (proj)-[:HAS_ENDPOINT]->(end)
    """, {"endpoints": endpoint_data})


def _store_edges_tx(tx: Transaction, edges: List[Dict[str, Any]]) -> None:
    """Transaction function to store edges using UNWIND batch operation with type-specific matching."""
    if not edges:
        return
    
    # Group edges by relationship type for efficient batch processing
    rel_types = {}
    for edge in edges:
        from_id = edge.get("from")
        to_id = edge.get("to")
        if not from_id or not to_id:
            logger.warning(f"Skipping edge due to missing IDs: {edge}")
            continue
        
        rel_type = edge.get("type", "DEPENDS_ON").upper()
        if rel_type not in rel_types:
            rel_types[rel_type] = []
        
        rel_types[rel_type].append({
            "from": from_id,
            "to": to_id,
            "weight": edge.get("weight", 1)
        })
    
    if not rel_types:
        return
    
    # Process each relationship type separately (required for dynamic relationship types)
    for rel_type, typed_edges in rel_types.items():
        # Use type-specific matching to avoid wrong matches
        # Match nodes that could be Module or Symbol based on ID prefix
        tx.run(f"""
            UNWIND $edges AS edge
            MATCH (a)
            WHERE (a:Module OR a:Symbol) AND a.id = edge.from
            MATCH (b)
            WHERE (b:Module OR b:Symbol) AND b.id = edge.to
            MERGE (a)-[r:{rel_type}]->(b)
            ON CREATE SET r.weight = edge.weight
            ON MATCH SET r.weight = edge.weight
        """, {"edges": typed_edges})


def _store_features_tx(tx: Transaction, features: List[Dict[str, Any]], project_id: str) -> None:
    """Transaction function to store features using UNWIND batch operation."""
    if not features:
        return
    
    # Prepare feature data for batch insert
    feature_data = []
    for feature in features:
        feature_id = feature.get("id")
        if not feature_id:
            logger.warning(f"Skipping feature - missing id: {feature}")
            continue
        
        module_ids = feature.get("moduleIds", [])
        feature_data.append({
            "feature_id": feature_id,
            "name": feature.get("name", ""),
            "path": feature.get("path", ""),
            "projectId": project_id,
            "moduleIds": module_ids
        })
    
    if not feature_data:
        return
    
    # Batch insert features
    tx.run("""
        UNWIND $features AS feature
        MERGE (f:Feature {id: feature.feature_id})
        SET f.name = feature.name,
            f.path = feature.path
        WITH f, feature.projectId AS projectId
        MATCH (proj:Project {id: projectId})
        MERGE (proj)-[:HAS_FEATURE]->(f)
    """, {"features": feature_data})
    
    # Batch connect features to modules
    feature_module_data = []
    for feature in features:
        feature_id = feature.get("id")
        if not feature_id:
            continue
        for module_id in feature.get("moduleIds", []):
            feature_module_data.append({
                "feature_id": feature_id,
                "module_id": module_id
            })
    
    if feature_module_data:
        tx.run("""
            UNWIND $feature_modules AS fm
            MATCH (f:Feature {id: fm.feature_id})
            MATCH (m:Module {id: fm.module_id})
            MERGE (f)-[:CONTAINS]->(m)
        """, {"feature_modules": feature_module_data})


def store_pkg(pkg: Dict[str, Any]) -> bool:
    """
    Store PKG data to Neo4j with transaction management and batch optimizations.
    
    Args:
        pkg: PKG dictionary containing project, modules, symbols, endpoints, edges, features
        
    Returns:
        True if successful, False otherwise
    """
    project_id = pkg.get('project', {}).get('id', 'unknown')
    
    logger.info(f"💾 STORING PKG TO NEO4J | Project ID: {project_id}")
    
    if not verify_connection():
        logger.error(f"❌ NEO4J CONNECTION UNAVAILABLE | Project ID: {project_id} | Cannot store PKG")
        return False
    
    try:
        with get_session() as session:
            try:
                # Store Package node
                logger.debug(f"📦 STORING PACKAGE NODE | Project ID: {project_id}")
                session.execute_write(_store_package_tx, pkg)
                logger.debug(f"✅ PACKAGE NODE STORED | Project ID: {project_id}")
                
                # Store Project node
                logger.debug(f"📋 STORING PROJECT NODE | Project ID: {project_id}")
                session.execute_write(_store_project_tx, pkg)
                logger.debug(f"✅ PROJECT NODE STORED | Project ID: {project_id}")
                
                # Batch store modules
                modules = pkg.get("modules", [])
                if modules:
                    logger.info(f"📦 STORING MODULES | Project ID: {project_id} | Count: {len(modules)} | Batch size: {batch_size}")
                    for i in range(0, len(modules), batch_size):
                        batch = modules[i:i + batch_size]
                        session.execute_write(_store_modules_tx, batch, project_id)
                    logger.info(f"✅ MODULES STORED | Project ID: {project_id} | Count: {len(modules)}")
                
                # Batch store symbols
                symbols = pkg.get("symbols", [])
                if symbols:
                    logger.info(f"🔤 STORING SYMBOLS | Project ID: {project_id} | Count: {len(symbols)} | Batch size: {batch_size}")
                    for i in range(0, len(symbols), batch_size):
                        batch = symbols[i:i + batch_size]
                        session.execute_write(_store_symbols_tx, batch, project_id)
                    logger.info(f"✅ SYMBOLS STORED | Project ID: {project_id} | Count: {len(symbols)}")
                
                # Batch store endpoints
                endpoints = pkg.get("endpoints", [])
                if endpoints:
                    logger.info(f"🌐 STORING ENDPOINTS | Project ID: {project_id} | Count: {len(endpoints)} | Batch size: {batch_size}")
                    for i in range(0, len(endpoints), batch_size):
                        batch = endpoints[i:i + batch_size]
                        session.execute_write(_store_endpoints_tx, batch, project_id)
                    logger.info(f"✅ ENDPOINTS STORED | Project ID: {project_id} | Count: {len(endpoints)}")
                
                # Batch store edges
                edges = pkg.get("edges", [])
                if edges:
                    logger.info(f"🔗 STORING EDGES | Project ID: {project_id} | Count: {len(edges)} | Batch size: {batch_size}")
                    for i in range(0, len(edges), batch_size):
                        batch = edges[i:i + batch_size]
                        session.execute_write(_store_edges_tx, batch)
                    logger.info(f"✅ EDGES STORED | Project ID: {project_id} | Count: {len(edges)}")
                
                # Store features
                features = pkg.get("features", [])
                if features:
                    logger.info(f"📁 STORING FEATURES | Project ID: {project_id} | Count: {len(features)}")
                    session.execute_write(_store_features_tx, features, project_id)
                    logger.info(f"✅ FEATURES STORED | Project ID: {project_id} | Count: {len(features)}")
                
                logger.info(f"✅ PKG STORED TO NEO4J | Project ID: {project_id} | Modules: {len(modules)} | Symbols: {len(symbols)} | Endpoints: {len(endpoints)} | Edges: {len(edges)} | Features: {len(features)}")
                return True
                
            except Exception as tx_error:
                logger.error(
                    f"❌ TRANSACTION ERROR | Project ID: {project_id} | Error: {tx_error}",
                    exc_info=True
                )
                raise  # Re-raise to be caught by outer try-except
                
    except ConnectionError as e:
        logger.error(f"❌ NEO4J CONNECTION ERROR | Project ID: {project_id} | Error: {e}")
        return False
    except Exception as e:
        logger.error(
            f"❌ STORE PKG ERROR | Project ID: {project_id} | Error: {e}",
            exc_info=True
        )
        return False


def store_pkg_version(pkg: Dict[str, Any], version: Optional[str] = None) -> bool:
    """
    Store PKG with version information for version tracking.
    
    Args:
        pkg: PKG dictionary
        version: Optional version string (defaults to timestamp-based version)
        
    Returns:
        True if successful, False otherwise
    """
    if version is None:
        from datetime import datetime
        version = datetime.utcnow().isoformat()
    
    # Add version to pkg
    pkg_with_version = pkg.copy()
    pkg_with_version["version"] = version
    
    return store_pkg(pkg_with_version)


def close_driver() -> None:
    """Close Neo4j driver connection."""
    global driver
    if driver:
        try:
            driver.close()
            logger.info("Neo4j driver closed.")
        except Exception as e:
            logger.error(f"Error closing Neo4j driver: {e}")
        finally:
            driver = None


def check_pkg_stored(project_id: str) -> bool:
    """
    Check if PKG for a project is already stored in Neo4j.
    
    Args:
        project_id: Project ID to check
        
    Returns:
        True if project exists in Neo4j, False otherwise
    """
    logger.debug(f"🔍 CHECKING PKG IN NEO4J | Project ID: {project_id}")
    if not verify_connection():
        logger.warning(f"⚠️  NEO4J NOT CONNECTED | Project ID: {project_id} | Cannot check PKG")
        return False
    
    try:
        with get_session() as session:
            result = session.run(
                "MATCH (p:Project {id: $project_id}) RETURN p",
                {"project_id": project_id}
            )
            record = result.single()
            exists = record is not None
            if exists:
                logger.info(f"✅ PKG FOUND IN NEO4J | Project ID: {project_id}")
            else:
                logger.info(f"ℹ️  PKG NOT IN NEO4J | Project ID: {project_id}")
            return exists
    except Exception as e:
        logger.error(f"❌ ERROR CHECKING PKG | Project ID: {project_id} | Error: {e}")
        return False


def load_pkg_from_neo4j(project_id: str) -> Optional[Dict[str, Any]]:
    """
    Load PKG data from Neo4j and reconstruct the full PKG JSON structure.
    
    Args:
        project_id: Project ID to load
        
    Returns:
        Complete PKG dictionary matching the schema from pkg_generator.py,
        or None if project not found or on error
    """
    logger.info(f"📥 LOADING PKG FROM NEO4J | Project ID: {project_id}")
    if not verify_connection():
        logger.warning(f"⚠️  NEO4J NOT CONNECTED | Project ID: {project_id} | Cannot load PKG")
        return None
    
    # Check if project exists first
    if not check_pkg_stored(project_id):
        logger.warning(f"⚠️  PROJECT NOT FOUND | Project ID: {project_id} | Not in Neo4j")
        return None
    
    try:
        with get_session() as session:
            # 1. Load Package node (version, generatedAt, gitSha)
            package_data = {}
            result = session.run(
                "MATCH (pkg:Package {id: $project_id}) RETURN pkg",
                {"project_id": project_id}
            )
            record = result.single()
            if record:
                pkg_node = record["pkg"]
                package_data = {
                    "version": pkg_node.get("version", "1.0.0"),
                    "generatedAt": pkg_node.get("generatedAt"),
                    "gitSha": pkg_node.get("gitSha")
                }
            
            # 2. Load Project node and Metadata
            project_data = {}
            metadata_data = {}
            result = session.run("""
                MATCH (proj:Project {id: $project_id})
                OPTIONAL MATCH (proj)-[:HAS_METADATA]->(m:Metadata {projectId: $project_id})
                RETURN proj, m
            """, {"project_id": project_id})
            record = result.single()
            if record:
                proj_node = record["proj"]
                project_data = {
                    "id": proj_node.get("id", project_id),
                    "name": proj_node.get("name", ""),
                    "rootPath": proj_node.get("rootPath", ""),
                    "languages": proj_node.get("languages", [])
                }
                if record["m"]:
                    meta_node = record["m"]
                    # Extract all metadata properties except projectId
                    metadata_data = {k: v for k, v in meta_node.items() if k != "projectId"}
            
            if not project_data:
                logger.warning(f"Project node not found for {project_id}")
                return None
            
            project_data["metadata"] = metadata_data
            
            # 3. Load Modules
            modules = []
            result = session.run("""
                MATCH (proj:Project {id: $project_id})-[:HAS_MODULE]->(mod:Module)
                RETURN mod
                ORDER BY mod.id
            """, {"project_id": project_id})
            for record in result:
                mod_node = record["mod"]
                module_dict = {"id": mod_node.get("id")}
                # Add all other properties
                for key, value in mod_node.items():
                    if key != "id" and value is not None:
                        module_dict[key] = value
                modules.append(module_dict)
            
            # 4. Load Symbols
            symbols = []
            result = session.run("""
                MATCH (proj:Project {id: $project_id})-[:HAS_SYMBOL]->(sym:Symbol)
                RETURN sym
                ORDER BY sym.id
            """, {"project_id": project_id})
            for record in result:
                sym_node = record["sym"]
                symbol_dict = {
                    "id": sym_node.get("id"),
                    "name": sym_node.get("name", "")
                }
                # Add all other properties except id and name
                for key, value in sym_node.items():
                    if key not in ["id", "name"] and value is not None:
                        symbol_dict[key] = value
                symbols.append(symbol_dict)
            
            # 5. Load Endpoints
            endpoints = []
            result = session.run("""
                MATCH (proj:Project {id: $project_id})-[:HAS_ENDPOINT]->(end:Endpoint)
                RETURN end
                ORDER BY end.id
            """, {"project_id": project_id})
            for record in result:
                end_node = record["end"]
                endpoint_dict = {
                    "id": end_node.get("id"),
                    "path": end_node.get("path", "")
                }
                # Add all other properties except id and path
                for key, value in end_node.items():
                    if key not in ["id", "path"] and value is not None:
                        endpoint_dict[key] = value
                endpoints.append(endpoint_dict)
            
            # 6. Load Features
            features = []
            feature_module_map = {}  # feature_id -> [module_ids]
            result = session.run("""
                MATCH (proj:Project {id: $project_id})-[:HAS_FEATURE]->(f:Feature)
                RETURN f
                ORDER BY f.id
            """, {"project_id": project_id})
            for record in result:
                feat_node = record["f"]
                feature_id = feat_node.get("id")
                feature_dict = {
                    "id": feature_id,
                    "name": feat_node.get("name", ""),
                    "path": feat_node.get("path", ""),
                    "moduleIds": []
                }
                features.append(feature_dict)
                feature_module_map[feature_id] = []
            
            # 7. Load Feature-Module links
            if feature_module_map:
                feature_ids = list(feature_module_map.keys())
                result = session.run("""
                    MATCH (f:Feature)-[:CONTAINS]->(m:Module)
                    WHERE f.id IN $feature_ids
                    RETURN f.id AS feature_id, m.id AS module_id
                """, {"feature_ids": feature_ids})
                for record in result:
                    feat_id = record["feature_id"]
                    mod_id = record["module_id"]
                    if feat_id in feature_module_map:
                        feature_module_map[feat_id].append(mod_id)
                
                # Update features with module IDs
                for feature in features:
                    feature_id = feature["id"]
                    if feature_id in feature_module_map:
                        feature["moduleIds"] = feature_module_map[feature_id]
            
            # 8. Load Edges (relationships between Modules/Symbols)
            edges = []
            # Query all relationship types between Module and Symbol nodes that belong to this project
            result = session.run("""
                MATCH (proj:Project {id: $project_id})
                MATCH (proj)-[:HAS_MODULE|HAS_SYMBOL]->(a)
                MATCH (a)-[r]->(b)
                WHERE (b:Module OR b:Symbol)
                AND (
                    EXISTS { MATCH (proj)-[:HAS_MODULE]->(b) } OR
                    EXISTS { MATCH (proj)-[:HAS_SYMBOL]->(b) }
                )
                RETURN type(r) AS rel_type, a.id AS from_id, b.id AS to_id, r.weight AS weight
            """, {"project_id": project_id})
            for record in result:
                edge_dict = {
                    "from": record["from_id"],
                    "to": record["to_id"],
                    "type": record["rel_type"]
                }
                if record["weight"] is not None:
                    edge_dict["weight"] = record["weight"]
                edges.append(edge_dict)
            
            # Reconstruct PKG dict matching the schema
            pkg = {
                "version": package_data.get("version", "1.0.0"),
                "generatedAt": package_data.get("generatedAt"),
                "gitSha": package_data.get("gitSha"),
                "project": project_data,
                "modules": modules,
                "symbols": symbols,
                "endpoints": endpoints,
                "edges": edges
            }
            
            # Add features if they exist
            if features:
                pkg["features"] = features
            
            logger.info(f"✅ PKG LOADED FROM NEO4J | Project ID: {project_id} | Modules: {len(modules)} | Symbols: {len(symbols)} | Endpoints: {len(endpoints)} | Edges: {len(edges)} | Features: {len(features)}")
            
            return pkg
            
    except ConnectionError as e:
        logger.error(f"❌ NEO4J CONNECTION ERROR | Project ID: {project_id} | Error: {e}")
        return None
    except Exception as e:
        logger.error(
            f"❌ LOAD PKG ERROR | Project ID: {project_id} | Error: {e}",
            exc_info=True
        )
        return None


# Initialize driver on module import
if uri and user and password:
    driver = _initialize_driver()
else:
    logger.warning("Neo4j not configured. Set NEO4J_URI, NEO4J_USER, and NEO4J_PASSWORD environment variables.")

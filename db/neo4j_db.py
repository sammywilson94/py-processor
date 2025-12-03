import json
import os
from dotenv import load_dotenv
from neo4j import GraphDatabase

# Load .env file
load_dotenv()

# Read env vars
uri = os.getenv("NEO4J_URI")
user = os.getenv("NEO4J_USER")
password = os.getenv("NEO4J_PASSWORD")
database = os.getenv("NEO4J_DATABASE","repos")

# Connect
driver = GraphDatabase.driver(uri, auth=(user, password))
# with GraphDatabase.driver(uri, auth=(user, password)) as driver:
#     driver.verify_connectivity()
#     print("Connection established.")


# def store_pkg(pkg):

#     with driver.session() as session:

#         # Create Package node
#         session.run("""
#             MERGE (p:Package {id: $project.id})
#             SET p.version = $version,
#                 p.generatedAt = $generatedAt,
#                 p.gitSha = $gitSha
#             """, pkg)

#         # 1. Create Project node (without metadata)
#         session.run("""
#             MERGE (proj:Project {
#                 id: $project.id
#             })
#             SET proj.name = $project.name,
#                 proj.rootPath = $project.rootPath,
#                 proj.languages = $project.languages
#         """, pkg)

#         # 2. Create Metadata node with flattened dict
#         session.run("""
#             MERGE (m:Metadata {projectId: $project.id})
#             SET m += $project.metadata
#         """, pkg)

#         # 3. Connect Project → Metadata
#         session.run("""
#             MATCH (proj:Project {id: $project.id})
#             MATCH (m:Metadata {projectId: $project.id})
#             MERGE (proj)-[:HAS_METADATA]->(m)
#         """, pkg)

#         # # Create Modules
#         for m in pkg["modules"]:
#             session.run("""
#                 MERGE (mod:Module {name: $name})
#                 SET mod += $module
#                 WITH mod
#                 MATCH (proj:Project {id: $projectId})
#                 MERGE (proj)-[:HAS_MODULE]->(mod)
#             """, {
#                 "name": m.get("name"),
#                 "module": m,
#                 "projectId": pkg["project"]["id"]
#             })

#         # # Create Symbols
#         for s in pkg["symbols"]:
#             session.run("""
#                 MERGE (sym:Symbol {name: $name})
#                 SET sym += $symbol
#                 WITH sym
#                 MATCH (proj:Project {id: $projectId})
#                 MERGE (proj)-[:HAS_SYMBOL]->(sym)
#             """, {
#                 "name": s.get("name"),
#                 "symbol": s,
#                 "projectId": pkg["project"]["id"]
#             })

#         # # Create Endpoints
#         for e in pkg["endpoints"]:
#             session.run("""
#                 MERGE (end:Endpoint {path: $path})
#                 SET end += $endpoint
#                 WITH end
#                 MATCH (proj:Project {id: $projectId})
#                 MERGE (proj)-[:HAS_ENDPOINT]->(end)
#             """, {
#                 "path": e.get("path"),
#                 "endpoint": e,
#                 "projectId": pkg["project"]["id"]
#             })

#         # # Create Edges (relationships)
#         for edge in pkg["edges"]:
#             session.run("""
#                 MATCH (a {id: $from})
#                 MATCH (b {id: $to})
#                 MERGE (a)-[:DEPENDS_ON]->(b)
#             """, edge)

def store_pkg(pkg):
    with driver.session() as session:

        # --------------------------
        # CREATE PACKAGE
        # --------------------------
        session.run("""
            MERGE (p:Package {id: $project.id})
            SET p.version = $version,
                p.generatedAt = $generatedAt,
                p.gitSha = $gitSha
        """, pkg)

        # --------------------------
        # CREATE PROJECT
        # --------------------------
        session.run("""
            MERGE (proj:Project {id: $project.id})
            SET proj.name = $project.name,
                proj.rootPath = $project.rootPath,
                proj.languages = $project.languages
        """, pkg)

        # --------------------------
        # CREATE METADATA NODE
        # --------------------------
        session.run("""
            MERGE (m:Metadata {projectId: $project.id})
            SET m += $project.metadata
        """, pkg)

        session.run("""
            MATCH (proj:Project {id: $project.id})
            MATCH (m:Metadata {projectId: $project.id})
            MERGE (proj)-[:HAS_METADATA]->(m)
        """, pkg)

        # --------------------------
        # CREATE MODULES
        # --------------------------
        for m in pkg["modules"]:
            module_id = m.get("id")
            if not module_id:
                print("Skipping module - missing id:", m)
                continue

            session.run("""
                MERGE (mod:Module {id: $id})
                SET mod += $data
                WITH mod
                MATCH (proj:Project {id: $projectId})
                MERGE (proj)-[:HAS_MODULE]->(mod)
            """, {
                "id": module_id,
                "data": {k: v for k, v in m.items() if v is not None},
                "projectId": pkg["project"]["id"]
            })

        # --------------------------
        # CREATE SYMBOLS
        # --------------------------
        for s in pkg["symbols"]:
            name = s.get("name")
            if not name:
                print("Skipping symbol due to missing name:", s)
                continue

            session.run("""
                MERGE (sym:Symbol {name: $name})
                SET sym += $data
                WITH sym
                MATCH (proj:Project {id: $projectId})
                MERGE (proj)-[:HAS_SYMBOL]->(sym)
            """, {
                "name": name,
                "data": {k: v for k, v in s.items() if v is not None},
                "projectId": pkg["project"]["id"]
            })

        # --------------------------
        # CREATE ENDPOINTS
        # --------------------------
        for e in pkg["endpoints"]:
            path = e.get("path")
            if not path:
                print("Skipping endpoint due to missing path:", e)
                continue

            session.run("""
                MERGE (end:Endpoint {path: $path})
                SET end += $data
                WITH end
                MATCH (proj:Project {id: $projectId})
                MERGE (proj)-[:HAS_ENDPOINT]->(end)
            """, {
                "path": path,
                "data": {k: v for k, v in e.items() if v is not None},
                "projectId": pkg["project"]["id"]
            })

        # --------------------------
        # CREATE EDGES
        # --------------------------
        for edge in pkg["edges"]:
            if not edge.get("from") or not edge.get("to"):
                print("Skipping edge due to missing IDs:", edge)
                continue

            rel_type = edge.get("type", "DEPENDS_ON").upper()  # Default to DEPENDS_ON if no type

            session.run(f"""
                MATCH (a {{id: $from}})
                MATCH (b {{id: $to}})
                MERGE (a)-[r:{rel_type}]->(b)
                ON CREATE SET r.weight = $weight
            """, {
                "from": edge["from"],
                "to": edge["to"],
                "weight": edge.get("weight", 1)
            })


        # --------------------------
        # CREATE FEATURE -> MODULE EDGES
        # --------------------------
        for feature in pkg.get("features", []):
            feature_id = feature["id"]
            
            session.run("""
            MERGE (f:Feature {id: $feature_id})
            SET f.name = $name, f.path = $path
            """, {
                "feature_id": feature_id,
                "name": feature.get("name"),
                "path": feature.get("path")
            })

            # Connect feature to project
            session.run("""
                MATCH (proj:Project {id: $project_id})
                MATCH (f:Feature {id: $feature_id})
                MERGE (proj)-[:HAS_FEATURE]->(f)
            """, {
                "project_id": pkg["project"]["id"],
                "feature_id": feature_id
            })

            # Connect feature to modules
            for module_id in feature.get("moduleIds", []):
                session.run("""
                    MATCH (f:Feature {id: $feature_id})
                    MATCH (m:Module {id: $module_id})
                    MERGE (f)-[:CONTAINS]->(m)
                """, {
                    "feature_id": feature_id,
                    "module_id": module_id
                })

def close_driver():
    driver.close()
    print("Neo4j driver closed.")

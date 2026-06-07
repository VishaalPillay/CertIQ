# integrations/microsoft_learn_mcp.py
from functools import lru_cache
import random
from typing import Any

from data.loader import load_certifications, get_certification, get_certification_by_code

class MicrosoftLearnMCP:
    """
    Mock MCP client. Reads from certifications.json and returns
    JSON-RPC 2.0 formatted responses identical in shape to what the
    real Microsoft Learn MCP server returns.

    Production upgrade: replace _call() with:
        import httpx
        response = httpx.post("https://learn.microsoft.com/api/mcp", json=payload)
        return response.json()
    """

    def _build_response(self, result: Any) -> dict[str, Any]:
        # MCP_MOCK: replace this with live HTTP call to https://learn.microsoft.com/api/mcp
        return {
            "jsonrpc": "2.0",
            "id": random.randint(1000, 9999),
            "result": result
        }

    def get_certification_details(self, cert_id: str) -> dict[str, Any]:
        """
        JSON-RPC method: learn.certification.get
        """
        cert = get_certification(cert_id)
        if not cert:
            cert = get_certification_by_code(cert_id)
        
        result = cert if cert else {}
        # MCP_MOCK: replace this with live HTTP call to https://learn.microsoft.com/api/mcp
        return self._build_response(result)

    def get_learning_path(self, role: str) -> dict[str, Any]:
        """
        JSON-RPC method: learn.learningPath.getForRole
        """
        certs = load_certifications()
        role_lower = role.lower()
        aligned = []
        for c in certs:
            alignments = c.get("role_alignment", [])
            if any(role_lower in r.lower() for r in alignments):
                aligned.append({
                    "id": c["id"],
                    "code": c["code"],
                    "name": c["name"],
                    "level": c["level"]
                })
        # MCP_MOCK: replace this with live HTTP call to https://learn.microsoft.com/api/mcp
        return self._build_response({"role": role, "learning_path": aligned})

    def get_prerequisites(self, cert_id: str) -> dict[str, Any]:
        """
        JSON-RPC method: learn.certification.getPrerequisites
        """
        cert = get_certification(cert_id)
        if not cert:
            cert = get_certification_by_code(cert_id)
            
        prereqs = cert.get("prerequisites", []) if cert else []
        prereq_type = cert.get("prerequisite_type", "none") if cert else "none"
        
        # MCP_MOCK: replace this with live HTTP call to https://learn.microsoft.com/api/mcp
        return self._build_response({
            "certification_id": cert["id"] if cert else cert_id,
            "certification_code": cert["code"] if cert else cert_id,
            "prerequisites": prereqs,
            "prerequisite_type": prereq_type
        })

    def search_modules(self, query: str, cert_id: str = None) -> dict[str, Any]:
        """
        JSON-RPC method: learn.modules.search
        """
        certs = load_certifications()
        query_lower = query.lower()
        matched_modules = []
        
        for c in certs:
            if cert_id and c["id"] != cert_id and c["code"] != cert_id:
                continue
            for m in c.get("modules", []):
                title_match = query_lower in m.get("title", "").lower()
                skills_match = any(query_lower in s.lower() for s in m.get("skills", []))
                if title_match or skills_match:
                    matched_modules.append({
                        "certification_code": c["code"],
                        "module_id": m["module_id"],
                        "title": m["title"],
                        "skills": m["skills"],
                        "bloom_level": m["bloom_level"],
                        "estimated_hours": m["estimated_hours"]
                    })
                    
        # MCP_MOCK: replace this with live HTTP call to https://learn.microsoft.com/api/mcp
        return self._build_response({"query": query, "modules": matched_modules})

@lru_cache(maxsize=1)
def get_microsoft_learn_mcp() -> MicrosoftLearnMCP:
    return MicrosoftLearnMCP()

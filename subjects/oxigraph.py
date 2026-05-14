"""HTTP client for the Oxigraph SPARQL store.

Oxigraph is a sidecar service holding our Wikidata subject mirror as RDF,
with one named graph per mirrored entity. This module exposes a thin
wrapper over the SPARQL Protocol and Graph Store Protocol HTTP endpoints.
"""

import logging

import requests
from django.conf import settings
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

logger = logging.getLogger(__name__)

WIKIDATA_ENTITY_IRI_BASE = "http://www.wikidata.org/entity"


def entity_graph_iri(wikidata_id):
    """Return the named-graph IRI for a Wikidata entity (e.g. Q12345)."""
    return f"{WIKIDATA_ENTITY_IRI_BASE}/{wikidata_id}"


def create_oxigraph_session():
    """A requests session with retry on transient Oxigraph failures."""
    session = requests.Session()
    retry_strategy = Retry(
        total=3,
        backoff_factor=0.5,
        status_forcelist=[500, 502, 503, 504],
        allowed_methods=["GET", "POST", "PUT", "DELETE"],
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("http://", adapter)
    session.mount("https://", adapter)
    return session


class OxigraphClient:
    """Thin wrapper over Oxigraph's SPARQL Protocol HTTP API.

    Construct fresh per task / request and either call ``close()`` or use
    as a context manager.
    """

    def __init__(self, base_url=None, session=None, timeout=None):
        self.base_url = (base_url or settings.OXIGRAPH_URL).rstrip("/")
        self.timeout = timeout if timeout is not None else settings.OXIGRAPH_TIMEOUT
        self._session = session
        self._owns_session = session is None

    @property
    def session(self):
        if self._session is None:
            self._session = create_oxigraph_session()
        return self._session

    def close(self):
        if self._owns_session and self._session is not None:
            self._session.close()
            self._session = None

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    def query(self, sparql):
        """Run a SPARQL query, return the raw parsed JSON response."""
        resp = self.session.post(
            f"{self.base_url}/query",
            data=sparql.encode("utf-8"),
            headers={
                "Content-Type": "application/sparql-query",
                "Accept": "application/sparql-results+json",
            },
            timeout=self.timeout,
        )
        resp.raise_for_status()
        return resp.json()

    def select(self, sparql):
        """Run a SELECT, return a list of {var: value_as_str} dicts."""
        data = self.query(sparql)
        return [
            {var: binding["value"] for var, binding in row.items()}
            for row in data.get("results", {}).get("bindings", [])
        ]

    def ask(self, sparql):
        """Run an ASK query, return the boolean answer."""
        return bool(self.query(sparql).get("boolean", False))

    def update(self, sparql):
        """Run a SPARQL Update (INSERT / DELETE / DROP / LOAD)."""
        resp = self.session.post(
            f"{self.base_url}/update",
            data=sparql.encode("utf-8"),
            headers={"Content-Type": "application/sparql-update"},
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def load_turtle(self, turtle, graph_iri):
        """Replace ``graph_iri``'s contents with the given Turtle.

        Uses the SPARQL 1.1 Graph Store Protocol: PUT to ``/store?graph=<iri>``
        atomically replaces the graph's contents.
        """
        data = turtle.encode("utf-8") if isinstance(turtle, str) else turtle
        resp = self.session.put(
            f"{self.base_url}/store",
            params={"graph": graph_iri},
            data=data,
            headers={"Content-Type": "text/turtle"},
            timeout=self.timeout,
        )
        resp.raise_for_status()

    def drop_graph(self, graph_iri):
        """Drop a named graph if it exists (no-op if it doesn't)."""
        self.update(f"DROP SILENT GRAPH <{graph_iri}>")

    def triple_count(self):
        """Total triple count across all graphs - handy for liveness checks."""
        rows = self.select("SELECT (COUNT(*) AS ?n) WHERE { ?s ?p ?o }")
        return int(rows[0]["n"]) if rows else 0

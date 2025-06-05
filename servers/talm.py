"""
TALM MCP Server - Topology Aware Lifecycle Manager for Red Hat ACM
A Model Context Protocol server for managing cluster lifecycle operations.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient
from mcp.server.fastmcp import Context, FastMCP
from mcp.server.fastmcp.exceptions import ResourceError, ToolError

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


@dataclass
class TALMContext:
    """Shared context for TALM operations"""

    k8s_client: client.ApiClient | None = None
    dynamic_client: DynamicClient | None = None


def get_ctx_or_raise() -> TALMContext:
    """Get TALM context or raise proper MCP error"""
    ctx: Context = mcp.get_context()
    lifespan_context = ctx.request_context.lifespan_context
    if lifespan_context.dynamic_client is None:
        raise ResourceError(
            "No cluster connection available. Server started in offline mode - check your kubeconfig and cluster connectivity"
        )
    return lifespan_context


@asynccontextmanager
async def talm_lifespan(server: FastMCP) -> AsyncIterator[TALMContext]:
    """Initialize Kubernetes clients and clean up on shutdown"""
    logger.info("Initializing TALM MCP Server...")

    k8s_client = None
    try:
        # Load kubeconfig (try in-cluster first, then local)
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster configuration")
        except Exception:
            try:
                config.load_kube_config()
                logger.info("Loaded local kubeconfig")
            except Exception as e:
                logger.error(f"Failed to load kubeconfig: {e}")
                # Create mock context for testing without real cluster
                logger.warning(
                    "Creating mock context for testing - some features may not work"
                )
                yield TALMContext()
                return

        # Initialize clients with connection validation
        try:
            k8s_client = client.ApiClient()
            dynamic_client = DynamicClient(k8s_client)

            logger.info("Testing cluster connectivity...")
            # Test connection by attempting to list namespaces
            core_v1 = client.CoreV1Api()
            core_v1.list_namespace(limit=1)

            logger.info("TALM MCP Server initialized successfully")

        except Exception as conn_error:
            logger.error(f"Cluster connection failed: {conn_error}")
            logger.warning(
                "Creating limited context - cluster operations will fail gracefully"
            )

            # Create limited context that will handle errors gracefully
            yield TALMContext(k8s_client=k8s_client)
            return

        ctx = TALMContext(k8s_client=k8s_client, dynamic_client=dynamic_client)

        yield ctx

    except Exception as e:
        logger.error(f"Failed to initialize TALM server: {e}")
        raise
    finally:
        logger.info("Shutting down TALM MCP Server...")
        if k8s_client is not None:
            try:
                k8s_client.close()
            except Exception as e:
                logger.warning(f"Error closing k8s client: {e}")


# Create FastMCP server with lifespan
mcp = FastMCP("TALM MCP Server", lifespan=talm_lifespan)


# ================================
# RESOURCES - Read-only data access
# ================================


@mcp.resource("talm://clusters")
def list_clusters() -> list[dict[str, Any]]:
    """List all managed clusters in ACM"""
    try:
        ctx = get_ctx_or_raise()

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1", kind="ManagedCluster"
        )

        clusters = managed_cluster_api.get()
        # Convert to serializable format
        return [cluster.to_dict() for cluster in clusters.items]

    except ApiException as e:
        raise ResourceError(f"Kubernetes API error: {e.reason}") from e
    except Exception as e:
        logger.error(f"Failed to list clusters: {e}")
        raise ResourceError(f"Failed to list clusters: {str(e)}") from e


@mcp.resource("talm://policies")
def list_policies() -> list[dict[str, Any]]:
    """List all policies bound to managed clusters"""
    try:
        ctx = get_ctx_or_raise()

        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1", kind="Policy"
        )

        policies = policy_api.get()
        # Convert to serializable format
        return [policy.to_dict() for policy in policies.items]

    except ApiException as e:
        raise ResourceError(f"Kubernetes API error: {e.reason}") from e
    except Exception as e:
        logger.error(f"Failed to list policies: {e}")
        raise ResourceError(f"Failed to list policies: {str(e)}") from e


@mcp.resource("talm://clusters/{cluster_name}/status")
def get_cluster_status(cluster_name: str) -> dict[str, Any]:
    """Get detailed status for a specific cluster"""
    try:
        ctx = get_ctx_or_raise()

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1", kind="ManagedCluster"
        )

        cluster = managed_cluster_api.get(name=cluster_name)

        # Get associated CGUs
        cluster_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            cluster_cgus = [
                cgu
                for cgu in cgus.items
                if cluster_name in cgu.spec.get("clusters", [])
            ]
        except Exception as e:
            logger.warning(f"Could not fetch CGUs: {e}")

        result = {
            "cluster": cluster.to_dict(),
            "cgus": [cgu.to_dict() for cgu in cluster_cgus],
        }

        return result

    except ApiException as e:
        if e.status == 404:
            raise ResourceError(f"Cluster {cluster_name} not found") from e
        raise ResourceError(f"Kubernetes API error: {e.reason}") from e
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        raise ResourceError(f"Failed to get cluster status: {str(e)}") from e


# ================================
# TOOLS - Actions with side effects
# ================================


@mcp.tool()
def server_status() -> str:
    """Check TALM MCP Server status and Kubernetes cluster connectivity.

    Returns a JSON object with server component status, cluster connection state,
    and troubleshooting recommendations if issues are detected.

    Returns:
        JSON string containing server status, client availability, and recommendations
    """
    try:
        ctx: Context = mcp.get_context()
        lifespan_ctx = ctx.request_context.lifespan_context

        status = {
            "server_running": True,
            "kubernetes_client": lifespan_ctx.k8s_client is not None,
            "dynamic_client": lifespan_ctx.dynamic_client is not None,
            "cluster_connected": lifespan_ctx.dynamic_client is not None,
            "recommendations": [],
        }

        if lifespan_ctx.dynamic_client is None:
            status["recommendations"] = [
                "Check your kubeconfig file",
                "Ensure cluster is accessible",
                "Verify network connectivity",
                "Restart the MCP server",
            ]

        return json.dumps(status, indent=2)

    except Exception as e:
        return json.dumps({"error": f"Server status check failed: {str(e)}"})


@mcp.tool()
def remediate_cluster(cluster_name: str) -> str:
    """Create a ClusterGroupUpgrade to remediate policy compliance issues for a specific cluster.

    This tool creates a TALM ClusterGroupUpgrade resource that will re-apply all
    non-compliant policies to bring the cluster back into compliance.

    Args:
        cluster_name: Name of the ManagedCluster to remediate

    Returns:
        JSON string with remediation status, CGU name, and monitoring information
    """
    try:
        ctx = get_ctx_or_raise()

        # Check if cluster exists (v1)
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1", kind="ManagedCluster"
        )

        try:
            managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                raise ToolError(f"Cluster {cluster_name} not found") from e
            raise ToolError(f"Kubernetes API error: {e.reason}") from e

        # Create ClusterGroupUpgrade for remediation (v1alpha1)
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )

        timestamp = int(datetime.now().timestamp())
        cgu_name = f"{cluster_name}-remediate-{timestamp}"

        # Build CGU spec according to CRD
        cgu_spec = {
            "apiVersion": "ran.openshift.io/v1alpha1",
            "kind": "ClusterGroupUpgrade",
            "metadata": {"name": cgu_name, "namespace": "ztp-install"},
            "spec": {
                "clusters": [cluster_name],
                "enable": True,
                "managedPolicies": [],  # Auto-discovered
                "remediationStrategy": {
                    "maxConcurrency": 1,
                    "timeout": 240,  # Default from CRD
                },
            },
        }

        # Create the CGU
        cgu_api.create(body=cgu_spec, namespace="ztp-install")

        return json.dumps(
            {
                "success": True,
                "cgu_name": cgu_name,
                "cluster_name": cluster_name,
                "namespace": "ztp-install",
                "message": "Remediation CGU created successfully",
                "monitor_resource": f"talm://clusters/{cluster_name}/status",
                "remediation_strategy": {"max_concurrency": 1, "timeout": 240},
            }
        )

    except Exception as e:
        logger.error(f"Failed to remediate cluster {cluster_name}: {e}")
        raise ToolError(
            f"Failed to remediate cluster '{cluster_name}': {str(e)}"
        ) from e


@mcp.tool()
def check_cluster_health(cluster_name: str) -> dict[str, Any]:
    """Analyze the health status of a specific managed cluster.

    Args:
        cluster_name: Name of the ManagedCluster to check

    Returns:
        Dictionary with cluster and CGU data for AI analysis
    """
    try:
        ctx = get_ctx_or_raise()

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1", kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                raise ToolError(f"Cluster {cluster_name} not found") from e
            raise

        # Get associated CGUs
        recent_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            recent_cgus = [
                cgu
                for cgu in cgus.items
                if cluster_name in cgu.spec.get("clusters", [])
            ]
        except Exception as e:
            logger.warning(f"Could not fetch CGUs for health check: {e}")

        return {
            "cluster": cluster.to_dict(),
            "cgus": [cgu.to_dict() for cgu in recent_cgus],
        }

    except Exception as e:
        logger.error(f"Failed to check cluster health: {e}")
        raise ToolError(f"Failed to check health: {str(e)}") from e


@mcp.tool()
def list_active_cgus() -> list[dict[str, Any]]:
    """List all currently active ClusterGroupUpgrade operations.

    Returns:
        List of active CGUs for AI analysis
    """
    try:
        ctx = get_ctx_or_raise()

        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )

        cgus = cgu_api.get()

        # Filter for active CGUs
        active_cgus = []
        for cgu in cgus.items:
            status = cgu.status.get("status", {}).get("status", "Unknown")
            if status in ["InProgress", "Timedout", "PartiallyDone"]:
                active_cgus.append(cgu)

        # Convert to serializable format
        return [cgu.to_dict() for cgu in active_cgus]

    except Exception as e:
        logger.error(f"Failed to list active CGUs: {e}")
        raise ToolError(f"Failed to list active CGUs: {str(e)}") from e


# ================================
# PROMPTS - Reusable templates
# ================================


@mcp.prompt()
def remediate_cluster_prompt(cluster_name: str) -> str:
    """Generate a remediation plan for a specific cluster"""
    return f"""I need to remediate cluster '{cluster_name}' to fix policy compliance issues.

Please help me:
1. Check the current health status of the cluster
2. Review what policies are non-compliant
3. Execute the remediation process
4. Monitor the progress

Use the available TALM tools to perform these operations step by step."""


@mcp.prompt()
def cluster_health_audit() -> str:
    """Generate a comprehensive cluster health audit prompt"""
    return """I need to perform a comprehensive health audit of all managed clusters.

Please help me:
1. List all managed clusters and their current status
2. Identify any clusters with health issues
3. Check for any active upgrade operations
4. Provide recommendations for clusters that need attention

Use the TALM resources and tools to gather this information."""


@mcp.prompt()
def batch_remediation_prompt(batch_size: str = "5") -> str:
    """Generate a batch remediation strategy"""
    return f"""I need to remediate multiple clusters in batches to ensure stability.

Please help me create a strategy to:
1. List all clusters that need remediation
2. Group them into batches of {batch_size} clusters
3. Execute remediation for each batch sequentially
4. Monitor progress and handle any failures

Use the TALM tools to implement this batch processing approach."""


# ================================
# MAIN EXECUTION
# ================================


def main() -> None:
    """Main entry point for the TALM MCP Server"""
    import argparse

    parser = argparse.ArgumentParser(description="TALM MCP Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "streamable-http"],
        default="stdio",
        help="Transport method (default: stdio)",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=8080,
        help="Port for streamable HTTP transport (default: 8080)",
    )

    args = parser.parse_args()

    if args.transport == "stdio":
        mcp.run()
    else:
        # Update port setting for HTTP transport
        mcp.settings.port = args.port
        mcp.run(transport="streamable-http")


if __name__ == "__main__":
    main()
    # policy from the cluster (look at a policy in ns)
    # go look at all my cluster - for any that are not complient and go remediate

    # delete the existing

    # oran sql
    # how far from vllm

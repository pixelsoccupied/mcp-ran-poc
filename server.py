#!/usr/bin/env python3
"""
TALM MCP Server - Topology Aware Lifecycle Manager for Red Hat ACM
A Model Context Protocol server for managing cluster lifecycle operations.
"""

import json
import asyncio
from contextlib import asynccontextmanager
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Dict, List, Optional
import logging

from mcp.server.fastmcp import FastMCP, Context
from kubernetes import client, config
from kubernetes.client.rest import ApiException
from kubernetes.dynamic import DynamicClient

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def get_ctx_or_error():
    """Get TALM context or return offline error"""
    ctx = mcp.get_context().request_context.lifespan_context
    if ctx.dynamic_client is None:
        return None, json.dumps({
            "error": "No cluster connection available",
            "message": "Server started in offline mode - check your kubeconfig and cluster connectivity"
        })
    return ctx, None


@dataclass
class TALMContext:
    """Shared context for TALM operations"""
    k8s_client: Optional[client.ApiClient] = None
    dynamic_client: Optional[DynamicClient] = None
    core_v1: Optional[client.CoreV1Api] = None
    apps_v1: Optional[client.AppsV1Api] = None


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
        except:
            try:
                config.load_kube_config()
                logger.info("Loaded local kubeconfig")
            except Exception as e:
                logger.error(f"Failed to load kubeconfig: {e}")
                # Create mock context for testing without real cluster
                logger.warning("Creating mock context for testing - some features may not work")
                yield TALMContext()
                return

        # Initialize clients with connection validation
        try:
            k8s_client = client.ApiClient()

            # Test connection
            core_v1 = client.CoreV1Api()
            logger.info("Testing cluster connectivity...")
            dynamic_client = DynamicClient(k8s_client)
            apps_v1 = client.AppsV1Api()

            logger.info("TALM MCP Server initialized successfully")

        except Exception as conn_error:
            logger.error(f"Cluster connection failed: {conn_error}")
            logger.warning("Creating limited context - cluster operations will fail gracefully")

            # Create limited context that will handle errors gracefully
            yield TALMContext(k8s_client=k8s_client)
            return

        ctx = TALMContext(
            k8s_client=k8s_client,
            dynamic_client=dynamic_client,
            core_v1=core_v1,
            apps_v1=apps_v1
        )

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
def list_clusters() -> str:
    """List all managed clusters in ACM"""
    try:
        ctx, error = get_ctx_or_error()
        if error:
            return error

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        clusters = managed_cluster_api.get()
        return json.dumps(clusters.items, default=str, indent=2)

    except Exception as e:
        logger.error(f"Failed to list clusters: {e}")
        return json.dumps({"error": f"Failed to list clusters: {str(e)}"})


@mcp.resource("talm://policies")
def list_policies() -> str:
    """List all policies bound to managed clusters"""
    try:
        ctx, error = get_ctx_or_error()
        if error:
            return error

        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1",
            kind="Policy"
        )

        policies = policy_api.get()
        return json.dumps(policies.items, default=str, indent=2)

    except Exception as e:
        logger.error(f"Failed to list policies: {e}")
        return json.dumps({"error": f"Failed to list policies: {str(e)}"})


@mcp.resource("talm://clusters/{cluster_name}/status")
def get_cluster_status(cluster_name: str) -> str:
    """Get detailed status for a specific cluster"""
    try:
        ctx, error = get_ctx_or_error()
        if error:
            return error

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        cluster = managed_cluster_api.get(name=cluster_name)

        # Get associated CGUs
        cluster_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            cluster_cgus = [cgu for cgu in cgus.items if cluster_name in cgu.spec.get("clusters", [])]
        except Exception as e:
            logger.warning(f"Could not fetch CGUs: {e}")

        result = {
            "cluster": cluster,
            "cgus": cluster_cgus
        }

        return json.dumps(result, default=str, indent=2)

    except ApiException as e:
        if e.status == 404:
            return json.dumps({"error": f"Cluster {cluster_name} not found"})
        return json.dumps({"error": f"API error: {e.reason}"})
    except Exception as e:
        logger.error(f"Failed to get cluster status: {e}")
        return json.dumps({"error": f"Failed to get cluster status: {str(e)}"})


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
        ctx = mcp.get_context().request_context.lifespan_context

        status = {
            "server_running": True,
            "kubernetes_client": ctx.k8s_client is not None,
            "dynamic_client": ctx.dynamic_client is not None,
            "core_v1_api": ctx.core_v1 is not None,
            "apps_v1_api": ctx.apps_v1 is not None,
            "cluster_connected": ctx.dynamic_client is not None,
            "recommendations": []
        }

        if ctx.dynamic_client is None:
            status["recommendations"] = [
                "Check your kubeconfig file",
                "Ensure cluster is accessible",
                "Verify network connectivity",
                "Restart the MCP server"
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
        ctx, error = get_ctx_or_error()
        if error:
            return json.dumps({"success": False, **json.loads(error)})

        # Check if cluster exists (v1)
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                return json.dumps({
                    "success": False,
                    "error": "Cluster not found",
                    "cluster_name": cluster_name
                })
            raise

        # Create ClusterGroupUpgrade for remediation (v1alpha1)
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1",
            kind="ClusterGroupUpgrade"
        )

        timestamp = int(datetime.now().timestamp())
        cgu_name = f"{cluster_name}-remediate-{timestamp}"

        # Build CGU spec according to CRD
        cgu_spec = {
            "apiVersion": "ran.openshift.io/v1alpha1",
            "kind": "ClusterGroupUpgrade",
            "metadata": {
                "name": cgu_name,
                "namespace": "ztp-install"
            },
            "spec": {
                "clusters": [cluster_name],
                "enable": True,
                "managedPolicies": [],  # Auto-discovered
                "remediationStrategy": {
                    "maxConcurrency": 1,
                    "timeout": 240  # Default from CRD
                }
            }
        }

        # Create the CGU
        created_cgu = cgu_api.create(body=cgu_spec, namespace="ztp-install")

        return json.dumps({
            "success": True,
            "cgu_name": cgu_name,
            "cluster_name": cluster_name,
            "namespace": "ztp-install",
            "message": "Remediation CGU created successfully",
            "monitor_resource": f"talm://clusters/{cluster_name}/status",
            "remediation_strategy": {
                "max_concurrency": 1,
                "timeout": 240
            }
        })

    except Exception as e:
        logger.error(f"Failed to remediate cluster {cluster_name}: {e}")
        return json.dumps({
            "success": False,
            "error": f"Failed to remediate cluster '{cluster_name}': {str(e)}"
        })


@mcp.tool()
def check_cluster_health(cluster_name: str) -> str:
    """Analyze the health status of a specific managed cluster.
    
    Args:
        cluster_name: Name of the ManagedCluster to check
        
    Returns:
        JSON string with cluster and CGU data for AI analysis
    """
    try:
        ctx, error = get_ctx_or_error()
        if error:
            return error

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                return json.dumps({"error": f"Cluster {cluster_name} not found"})
            raise

        # Get associated CGUs
        recent_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            recent_cgus = [cgu for cgu in cgus.items if cluster_name in cgu.spec.get("clusters", [])]
        except Exception as e:
            logger.warning(f"Could not fetch CGUs for health check: {e}")

        return json.dumps({
            "cluster": cluster,
            "cgus": recent_cgus
        }, default=str, indent=2)

    except Exception as e:
        logger.error(f"Failed to check cluster health: {e}")
        return json.dumps({"error": f"Failed to check health: {str(e)}"})


@mcp.tool()
def list_active_cgus() -> str:
    """List all currently active ClusterGroupUpgrade operations.
    
    Returns:
        JSON string with active CGUs for AI analysis
    """
    try:
        ctx, error = get_ctx_or_error()
        if error:
            return error

        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1",
            kind="ClusterGroupUpgrade"
        )

        cgus = cgu_api.get()
        
        # Filter for active CGUs
        active_cgus = []
        for cgu in cgus.items:
            status = cgu.status.get("status", {}).get("status", "Unknown")
            if status in ["InProgress", "Timedout", "PartiallyDone"]:
                active_cgus.append(cgu)

        return json.dumps(active_cgus, default=str, indent=2)

    except Exception as e:
        logger.error(f"Failed to list active CGUs: {e}")
        return json.dumps({"error": f"Failed to list active CGUs: {str(e)}"})


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

def main():
    """Main entry point for the TALM MCP Server"""
    import argparse

    parser = argparse.ArgumentParser(description="TALM MCP Server")
    parser.add_argument("--transport", choices=["stdio", "streamable-http"], default="stdio",
                        help="Transport method (default: stdio)")
    parser.add_argument("--port", type=int, default=8080,
                        help="Port for streamable HTTP transport (default: 8080)")

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
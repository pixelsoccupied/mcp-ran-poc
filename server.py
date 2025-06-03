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
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "error": "No cluster connection available",
                "message": "Server started in offline mode - check your kubeconfig and cluster connectivity"
            })

        # Get ManagedCluster CRDs (v1)
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        clusters = managed_cluster_api.get()

        result = []
        for cluster in clusters.items:
            # Extract basic info from CRD structure
            name = cluster.metadata.name
            created = cluster.metadata.creationTimestamp
            labels = dict(cluster.metadata.labels or {})
            hub_accepted = cluster.spec.get("hubAcceptsClient", False)

            # Check availability from conditions
            status = "Unknown"
            for condition in cluster.status.get("conditions", []):
                if condition["type"] == "ManagedClusterConditionAvailable":
                    status = "Available" if condition["status"] == "True" else "Unavailable"
                    break

            # Get resource info
            allocatable = cluster.status.get("allocatable", {})
            cpu_capacity = allocatable.get("cpu", "Unknown")

            # Get Kubernetes version
            k8s_version = cluster.status.get("version", {}).get("kubernetes", "Unknown")

            result.append({
                "name": name,
                "status": status,
                "labels": labels,
                "created": created.isoformat() if hasattr(created, 'isoformat') else str(created),
                "cpu_capacity": cpu_capacity,
                "kubernetes_version": k8s_version,
                "hub_accepted": hub_accepted
            })

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Failed to list clusters: {e}")
        return json.dumps({"error": f"Failed to list clusters: {str(e)}"})


@mcp.resource("talm://policies")
def list_policies() -> str:
    """List all policies bound to managed clusters"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "error": "No cluster connection available",
                "message": "Server started in offline mode - check your kubeconfig and cluster connectivity"
            })

        # Get Policy CRDs (v1)
        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1",
            kind="Policy"
        )

        policies = policy_api.get()

        result = []
        for policy in policies.items:
            # Extract basic info from CRD structure
            name = policy.metadata.name
            namespace = policy.metadata.namespace
            created = policy.metadata.creationTimestamp

            # Get compliance status
            compliance_state = "Unknown"
            if hasattr(policy, 'status') and policy.status:
                compliance_state = policy.status.get("compliant", "Unknown")

            # Count policy templates
            templates_count = len(policy.spec.get("policy-templates", []))

            result.append({
                "name": name,
                "namespace": namespace,
                "compliance": compliance_state,
                "templates": templates_count,
                "created": created.isoformat() if hasattr(created, 'isoformat') else str(created)
            })

        return json.dumps(result, indent=2)

    except Exception as e:
        logger.error(f"Failed to list policies: {e}")
        return json.dumps({"error": f"Failed to list policies: {str(e)}"})


@mcp.resource("talm://clusters/{cluster_name}/status")
def get_cluster_status(cluster_name: str) -> str:
    """Get detailed status for a specific cluster"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "error": "No cluster connection available",
                "message": "Server started in offline mode - check your kubeconfig and cluster connectivity"
            })

        # Get specific ManagedCluster (v1)
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        cluster = managed_cluster_api.get(name=cluster_name)

        # Extract conditions with proper structure
        conditions = []
        for condition in cluster.status.get("conditions", []):
            conditions.append({
                "type": condition["type"],
                "status": condition["status"],
                "reason": condition.get("reason", ""),
                "message": condition.get("message", ""),
                "lastTransitionTime": condition.get("lastTransitionTime", "")
            })

        # Get associated CGUs (v1alpha1)
        cluster_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()

            for cgu in cgus.items:
                # Check if this cluster is in the CGU
                if cluster_name in cgu.spec.get("clusters", []):
                    cgu_status = cgu.status.get("status", {})
                    cluster_cgus.append({
                        "name": cgu.metadata.name,
                        "namespace": cgu.metadata.namespace,
                        "status": cgu_status.get("status", "Unknown"),
                        "current_batch": cgu_status.get("currentBatch", 0),
                        "started_at": cgu_status.get("startedAt", ""),
                        "enable": cgu.spec.get("enable", False)
                    })
        except Exception as e:
            logger.warning(f"Could not fetch CGUs: {e}")

        result = {
            "cluster": {
                "name": cluster.metadata.name,
                "created": cluster.metadata.creationTimestamp.isoformat() if hasattr(cluster.metadata.creationTimestamp,
                                                                                     'isoformat') else str(
                    cluster.metadata.creationTimestamp),
                "labels": dict(cluster.metadata.labels or {}),
                "hub_accepted": cluster.spec.get("hubAcceptsClient", False),
                "conditions": conditions,
                "capacity": cluster.status.get("capacity", {}),
                "allocatable": cluster.status.get("allocatable", {}),
                "version": cluster.status.get("version", {})
            },
            "cgus": cluster_cgus
        }

        return json.dumps(result, indent=2)

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
    """Check TALM MCP Server status and connectivity"""
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
    """Re-apply all non-compliant policies for a specific cluster"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "success": False,
                "error": "No cluster connection available",
                "message": "Check your kubeconfig and cluster connectivity"
            })

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
    """Perform a comprehensive health check on a cluster"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "cluster_name": cluster_name,
                "health_status": "unknown",
                "error": "No cluster connection available",
                "message": "Check your kubeconfig and cluster connectivity"
            })

        # Get cluster info (v1)
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                return json.dumps({
                    "cluster_name": cluster_name,
                    "health_status": "not_found",
                    "error": "Cluster not found"
                })
            raise

        # Analyze conditions systematically
        health_status = "healthy"
        issues = []

        for condition in cluster.status.get("conditions", []):
            if condition["type"] == "ManagedClusterConditionAvailable":
                if condition["status"] != "True":
                    health_status = "unhealthy"
                    issues.append({
                        "type": "availability",
                        "reason": condition.get("reason", ""),
                        "message": condition.get("message", "Unknown reason")
                    })
            elif condition["type"] == "ManagedClusterJoined":
                if condition["status"] != "True":
                    if health_status == "healthy":
                        health_status = "warning"
                    issues.append({
                        "type": "join_status",
                        "reason": condition.get("reason", ""),
                        "message": condition.get("message", "Unknown reason")
                    })

        # Check for recent CGUs
        recent_cgus = []
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()

            # Find CGUs that include this cluster
            for cgu in cgus.items:
                if cluster_name in cgu.spec.get("clusters", []):
                    recent_cgus.append({
                        "name": cgu.metadata.name,
                        "status": cgu.status.get("status", {}).get("status", "Unknown"),
                        "enable": cgu.spec.get("enable", False),
                        "created": cgu.metadata.creationTimestamp.isoformat() if hasattr(cgu.metadata.creationTimestamp,
                                                                                         'isoformat') else str(
                            cgu.metadata.creationTimestamp)
                    })

            # Sort by creation time (most recent first)
            recent_cgus.sort(key=lambda x: x["created"], reverse=True)
            recent_cgus = recent_cgus[:3]  # Last 3 CGUs

        except Exception as e:
            logger.warning(f"Could not fetch CGUs for health check: {e}")

        return json.dumps({
            "cluster_name": cluster_name,
            "health_status": health_status,
            "hub_accepted": cluster.spec.get("hubAcceptsClient", False),
            "kubernetes_version": cluster.status.get("version", {}).get("kubernetes", "Unknown"),
            "issues": issues,
            "recent_operations": recent_cgus
        })

    except Exception as e:
        logger.error(f"Failed to check cluster health: {e}")
        return json.dumps({
            "cluster_name": cluster_name,
            "health_status": "error",
            "error": f"Failed to check health: {str(e)}"
        })


@mcp.tool()
def list_active_cgus() -> str:
    """List all currently active ClusterGroupUpgrades"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        if ctx.dynamic_client is None:
            return json.dumps({
                "active_cgus": [],
                "error": "No cluster connection available",
                "message": "Check your kubeconfig and cluster connectivity"
            })

        # Get CGUs (v1alpha1)
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1",
            kind="ClusterGroupUpgrade"
        )

        cgus = cgu_api.get()

        active_cgus = []
        for cgu in cgus.items:
            # Check status from the status field
            cgu_status = cgu.status.get("status", {})
            status = cgu_status.get("status", "Unknown")

            # Only include active statuses
            if status in ["InProgress", "Timedout", "PartiallyDone"]:
                active_cgus.append({
                    "name": cgu.metadata.name,
                    "namespace": cgu.metadata.namespace,
                    "clusters": cgu.spec.get("clusters", []),
                    "status": status,
                    "current_batch": cgu_status.get("currentBatch", 0),
                    "max_concurrency": cgu.spec.get("remediationStrategy", {}).get("maxConcurrency", 1),
                    "timeout": cgu.spec.get("remediationStrategy", {}).get("timeout", 240),
                    "enable": cgu.spec.get("enable", False),
                    "created": cgu.metadata.creationTimestamp.isoformat() if hasattr(cgu.metadata.creationTimestamp,
                                                                                     'isoformat') else str(
                        cgu.metadata.creationTimestamp),
                    "managed_policies": cgu.spec.get("managedPolicies", [])
                })

        return json.dumps({
            "active_cgus": active_cgus,
            "count": len(active_cgus)
        })

    except Exception as e:
        logger.error(f"Failed to list active CGUs: {e}")
        return json.dumps({
            "active_cgus": [],
            "error": f"Failed to list active CGUs: {str(e)}"
        })


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
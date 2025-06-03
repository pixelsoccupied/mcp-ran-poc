#!/usr/bin/env python3
# /// script
# requires-python =

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
    k8s_client: client.ApiClient
    dynamic_client: DynamicClient
    core_v1: client.CoreV1Api
    apps_v1: client.AppsV1Api


@asynccontextmanager
async def talm_lifespan(server: FastMCP) -> AsyncIterator[TALMContext]:
    """Initialize Kubernetes clients and clean up on shutdown"""
    logger.info("Initializing TALM MCP Server...")

    try:
        # Load kubeconfig (try in-cluster first, then local)
        try:
            config.load_incluster_config()
            logger.info("Loaded in-cluster configuration")
        except:
            config.load_kube_config()
            logger.info("Loaded local kubeconfig")

        # Initialize clients
        k8s_client = client.ApiClient()
        dynamic_client = DynamicClient(k8s_client)
        core_v1 = client.CoreV1Api()
        apps_v1 = client.AppsV1Api()

        ctx = TALMContext(
            k8s_client=k8s_client,
            dynamic_client=dynamic_client,
            core_v1=core_v1,
            apps_v1=apps_v1
        )

        logger.info("TALM MCP Server initialized successfully")
        yield ctx

    except Exception as e:
        logger.error(f"Failed to initialize TALM server: {e}")
        raise
    finally:
        logger.info("Shutting down TALM MCP Server...")
        if 'k8s_client' in locals():
            await k8s_client.close()


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

        # Get ManagedCluster CRDs
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        clusters = managed_cluster_api.get()

        result = []
        for cluster in clusters.items:
            status = "Unknown"
            ready_condition = next(
                (c for c in cluster.get("status", {}).get("conditions", [])
                 if c.get("type") == "ManagedClusterConditionAvailable"),
                None
            )
            if ready_condition:
                status = "Available" if ready_condition.get("status") == "True" else "Unavailable"

            result.append({
                "name": cluster.metadata.name,
                "status": status,
                "labels": dict(cluster.metadata.get("labels", {})),
                "created": cluster.metadata.creationTimestamp.isoformat() if cluster.metadata.creationTimestamp else None,
                "nodes": cluster.get("status", {}).get("allocatable", {}).get("cpu", "Unknown")
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

        # Get Policy CRDs
        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1",
            kind="Policy"
        )

        policies = policy_api.get()

        result = []
        for policy in policies.items:
            compliance_state = "Unknown"
            if hasattr(policy, 'status') and policy.status:
                compliance_state = policy.status.get("compliant", "Unknown")

            result.append({
                "name": policy.metadata.name,
                "namespace": policy.metadata.namespace,
                "compliance": compliance_state,
                "templates": len(policy.spec.get("policy-templates", [])),
                "created": policy.metadata.creationTimestamp.isoformat() if policy.metadata.creationTimestamp else None
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

        # Get specific ManagedCluster
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        cluster = managed_cluster_api.get(name=cluster_name)

        # Get associated CGUs
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            cluster_cgus = [
                cgu for cgu in cgus.items
                if cluster_name in cgu.spec.get("clusters", [])
            ]
        except:
            cluster_cgus = []

        result = {
            "cluster": {
                "name": cluster.metadata.name,
                "status": cluster.get("status", {}),
                "labels": dict(cluster.metadata.get("labels", {})),
            },
            "cgus": [
                {
                    "name": cgu.metadata.name,
                    "status": cgu.get("status", {}).get("status", "Unknown"),
                    "progress": cgu.get("status", {}).get("status", {})
                }
                for cgu in cluster_cgus
            ]
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
def remediate_cluster(cluster_name: str) -> str:
    """Re-apply all non-compliant policies for a specific cluster"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        # Check if cluster exists
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                return f"❌ Error: Cluster '{cluster_name}' not found"
            raise

        # Create ClusterGroupUpgrade for remediation
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1",
            kind="ClusterGroupUpgrade"
        )

        timestamp = int(datetime.now().timestamp())
        cgu_name = f"{cluster_name}-remediate-{timestamp}"

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
                "managedPolicies": [],  # Will be auto-discovered
                "remediationStrategy": {
                    "maxConcurrency": 1,
                    "timeout": 240
                }
            }
        }

        # Create the CGU
        created_cgu = cgu_api.create(body=cgu_spec, namespace="ztp-install")

        return f"✅ Created remediation CGU '{cgu_name}' for cluster '{cluster_name}'\n" \
               f"📋 CGU will automatically discover and remediate non-compliant policies\n" \
               f"🔍 Monitor progress with: talm://clusters/{cluster_name}/status"

    except Exception as e:
        logger.error(f"Failed to remediate cluster {cluster_name}: {e}")
        return f"❌ Failed to remediate cluster '{cluster_name}': {str(e)}"


@mcp.tool()
def check_cluster_health(cluster_name: str) -> str:
    """Perform a comprehensive health check on a cluster"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        # Get cluster info
        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1",
            kind="ManagedCluster"
        )

        try:
            cluster = managed_cluster_api.get(name=cluster_name)
        except ApiException as e:
            if e.status == 404:
                return f"❌ Cluster '{cluster_name}' not found"
            raise

        # Check conditions
        conditions = cluster.get("status", {}).get("conditions", [])
        health_status = "🟢 Healthy"
        issues = []

        for condition in conditions:
            if condition.get("type") == "ManagedClusterConditionAvailable":
                if condition.get("status") != "True":
                    health_status = "🔴 Unhealthy"
                    issues.append(f"Cluster not available: {condition.get('message', 'Unknown reason')}")

            elif condition.get("type") == "ManagedClusterJoined":
                if condition.get("status") != "True":
                    health_status = "🟡 Warning"
                    issues.append(f"Cluster not properly joined: {condition.get('message', 'Unknown reason')}")

        # Check for recent CGUs
        try:
            cgu_api = ctx.dynamic_client.resources.get(
                api_version="ran.openshift.io/v1alpha1",
                kind="ClusterGroupUpgrade"
            )
            cgus = cgu_api.get()
            recent_cgus = [
                cgu for cgu in cgus.items
                if cluster_name in cgu.spec.get("clusters", [])
            ]
            recent_cgus.sort(key=lambda x: x.metadata.creationTimestamp, reverse=True)
            recent_cgus = recent_cgus[:3]  # Last 3 CGUs
        except:
            recent_cgus = []

        result = f"{health_status} Cluster '{cluster_name}'\n\n"

        if issues:
            result += "⚠️  Issues Found:\n"
            for issue in issues:
                result += f"  • {issue}\n"
            result += "\n"

        if recent_cgus:
            result += "📊 Recent Operations:\n"
            for cgu in recent_cgus:
                status = cgu.get("status", {}).get("status", "Unknown")
                result += f"  • {cgu.metadata.name}: {status}\n"
        else:
            result += "📊 No recent upgrade operations found\n"

        return result

    except Exception as e:
        logger.error(f"Failed to check cluster health: {e}")
        return f"❌ Failed to check health for cluster '{cluster_name}': {str(e)}"


@mcp.tool()
def list_active_cgus() -> str:
    """List all currently active ClusterGroupUpgrades"""
    try:
        ctx = mcp.get_context().request_context.lifespan_context

        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1",
            kind="ClusterGroupUpgrade"
        )

        cgus = cgu_api.get()

        active_cgus = []
        for cgu in cgus.items:
            status = cgu.get("status", {}).get("status", "Unknown")
            if status in ["InProgress", "Timedout", "PartiallyDone"]:
                active_cgus.append({
                    "name": cgu.metadata.name,
                    "namespace": cgu.metadata.namespace,
                    "clusters": cgu.spec.get("clusters", []),
                    "status": status,
                    "created": cgu.metadata.creationTimestamp.isoformat() if cgu.metadata.creationTimestamp else None
                })

        if not active_cgus:
            return "✅ No active ClusterGroupUpgrades found"

        result = f"🔄 Found {len(active_cgus)} active CGU(s):\n\n"
        for cgu in active_cgus:
            result += f"📋 {cgu['name']}\n"
            result += f"   Status: {cgu['status']}\n"
            result += f"   Clusters: {', '.join(cgu['clusters'])}\n"
            result += f"   Created: {cgu['created']}\n\n"

        return result

    except Exception as e:
        logger.error(f"Failed to list active CGUs: {e}")
        return f"❌ Failed to list active CGUs: {str(e)}"


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
        # Streamable HTTP is the modern replacement for SSE
        mcp.run(transport="streamable-http", port=args.port)


if __name__ == "__main__":
    main()
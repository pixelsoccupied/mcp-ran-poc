"""
TALM MCP Server - Topology Aware Lifecycle Manager for Red Hat ACM
A Model Context Protocol server for managing cluster lifecycle operations.
"""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
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
def get_clusters_by_label(label_key: str, label_value: str) -> str:
    """Get all ManagedClusters matching a specific label for CGU analysis.

    The AI should analyze the returned clusters for CGU readiness by checking:

    CLUSTER HEALTH VALIDATION:
    - status.conditions[] where type="ManagedClusterConditionAvailable" should have status="True"
    - status.conditions[] where type="HubAcceptedManagedCluster" should have status="True"
    - Look for any conditions with status="False" or reason indicating issues

    CLUSTER READINESS INDICATORS:
    - Check if cluster has been recently created (may need time to stabilize)
    - Look for version skew in status.version if doing upgrades
    - Check allocatable resources in status if resource-intensive policies

    LABELS TO VERIFY:
    - Confirm the target label is present: metadata.labels[label_key] == label_value
    - Look for other relevant labels like cluster-role, environment, etc.
    - Check for any conflicting labels that might affect policy application

    Args:
        label_key: Label key to match clusters (e.g., "environment")
        label_value: Label value to match (e.g., "test")

    Returns:
        JSON string with all matching ManagedCluster CRs for AI analysis
    """
    try:
        ctx = get_ctx_or_raise()

        managed_cluster_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1", kind="ManagedCluster"
        )

        all_clusters = managed_cluster_api.get()
        matching_clusters = []

        for cluster in all_clusters.items:
            labels = cluster.metadata.get("labels", {})
            if labels.get(label_key) == label_value:
                matching_clusters.append(cluster.to_dict())

        return json.dumps(
            {
                "label_selector": f"{label_key}={label_value}",
                "cluster_count": len(matching_clusters),
                "clusters": matching_clusters,
            },
            indent=2,
        )

    except Exception as e:
        raise ToolError(f"Failed to get clusters: {str(e)}") from e


@mcp.tool()
def get_policies_by_label(label_key: str, label_value: str) -> str:
    """Get all Policies that target clusters with the specified label for CGU analysis.

    The AI should analyze the returned data to validate CGU prerequisites:

    POLICY VALIDATION:
    - Check metadata.annotations["talm.io/upgrade-policy"] == "true" for CGU eligibility
    - Verify remediationAction is set appropriately (inform/enforce)
    - Look for policy.spec.disabled != true

    PLACEMENT VALIDATION:
    - Ensure each policy has a corresponding Placement that targets label_key=label_value
    - Check placement.spec.predicates[].requiredClusterSelector.labelSelector.matchExpressions[]
    - Verify the placement has key=label_key, operator="In", values=[label_value]

    BINDING VALIDATION:
    - Confirm each policy has a PlacementBinding connecting it to its Placement
    - Check binding.subjects[] contains the policy name
    - Verify binding.placementRef.name matches the placement name

    POLICY CONTENT VALIDATION:
    - Look at policy.spec.policy-templates[].objectDefinition.spec.object-templates[]
    - Check for conflicting policies (same resources, different configs)
    - Identify policies that require cluster restarts or disruption

    NAMESPACE CONSISTENCY:
    - All related CRs (Policy, Placement, PlacementBinding) should be in same namespace
    - This namespace will be used for the CGU

    Args:
        label_key: Label key that policies should target (e.g., "environment")
        label_value: Label value that policies should target (e.g., "test")

    Returns:
        JSON string with Policies, Placements, and PlacementBindings for AI analysis
    """
    try:
        ctx = get_ctx_or_raise()

        # Get all Policies
        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1", kind="Policy"
        )
        all_policies = policy_api.get()

        # Get all Placements
        placement_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1beta1", kind="Placement"
        )
        all_placements = placement_api.get()

        # Get all PlacementBindings
        binding_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1", kind="PlacementBinding"
        )
        all_bindings = binding_api.get()

        return json.dumps(
            {
                "label_selector": f"{label_key}={label_value}",
                "policies": [p.to_dict() for p in all_policies.items],
                "placements": [p.to_dict() for p in all_placements.items],
                "placement_bindings": [b.to_dict() for b in all_bindings.items],
            },
            indent=2,
        )

    except Exception as e:
        raise ToolError(f"Failed to get policies: {str(e)}") from e


@mcp.tool()
def get_active_cgus() -> str:
    """Get all ClusterGroupUpgrade CRs to check for conflicts before creating new CGUs.

    The AI should analyze existing CGUs to prevent conflicts:

    CGU CONFLICT DETECTION:
    - Look for CGUs with status.status.status="InProgress" or "PartiallyDone"
    - Check spec.clusters[] for overlap with target clusters
    - Avoid creating CGUs that target same clusters as active ones

    CGU STATUS ANALYSIS:
    - "Completed": CGU finished successfully, safe to create new ones
    - "InProgress": CGU actively running, wait before creating new ones
    - "PartiallyDone": Some clusters failed, investigate before proceeding
    - "Timedout": CGU failed, may need cleanup before new CGU
    - "Blocked": CGU blocked by preconditions, check what's blocking

    RESOURCE USAGE PATTERNS:
    - Check spec.managedPolicies[] to see what policies are being applied
    - Look at spec.remediationStrategy.maxConcurrency for throughput planning
    - Review status.clusters[] for per-cluster status

    NAMING CONFLICTS:
    - Ensure proposed CGU name doesn't conflict with existing CGUs
    - Check metadata.name across all namespaces if needed

    Args:
        None

    Returns:
        JSON string with all ClusterGroupUpgrade CRs for AI conflict analysis
    """
    try:
        ctx = get_ctx_or_raise()

        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )

        all_cgus = cgu_api.get()

        return json.dumps(
            {
                "cgu_count": len(all_cgus.items),
                "cgus": [cgu.to_dict() for cgu in all_cgus.items],
            },
            indent=2,
        )

    except Exception as e:
        raise ToolError(f"Failed to get CGUs: {str(e)}") from e


@mcp.tool()
def create_cgu(cgu_spec: dict) -> str:
    """Create a ClusterGroupUpgrade CR with the provided specification.

    The AI should construct the cgu_spec dict based on its analysis of clusters and policies.

    REQUIRED CGU SPEC STRUCTURE:
    {
        "apiVersion": "ran.openshift.io/v1alpha1",
        "kind": "ClusterGroupUpgrade",
        "metadata": {
            "name": "unique-cgu-name",
            "namespace": "same-as-policies"
        },
        "spec": {
            "clusters": ["cluster1", "cluster2"],  # From cluster analysis
            "managedPolicies": ["policy1", "policy2"],  # From policy analysis
            "enable": false,  # Start disabled for safety
            "remediationStrategy": {
                "maxConcurrency": 2,  # Based on cluster count/capacity
                "timeout": 240  # Based on policy complexity
            }
        }
    }

    CGU NAMING BEST PRACTICES:
    - Include environment/label in name: "cgu-test-env-timestamp"
    - Include timestamp to avoid conflicts: int(datetime.now().timestamp())
    - Keep names under 63 characters for Kubernetes compatibility

    REMEDIATION STRATEGY GUIDELINES:
    - maxConcurrency: 1-2 for production, higher for test environments
    - timeout: 240 minutes default, increase for complex policies
    - Consider cluster capacity when setting concurrency

    SAFETY DEFAULTS:
    - Always start with enable=false for review
    - User can enable CGU after reviewing the created resource
    - Include informative annotations for tracking

    Args:
        cgu_spec: Complete CGU specification dict to create

    Returns:
        JSON string with creation status and CGU details
    """
    try:
        ctx = get_ctx_or_raise()

        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )

        # Validate required fields
        if not all(
            key in cgu_spec for key in ["apiVersion", "kind", "metadata", "spec"]
        ):
            raise ToolError(
                "CGU spec missing required fields: apiVersion, kind, metadata, spec"
            )

        if not all(key in cgu_spec["spec"] for key in ["clusters", "managedPolicies"]):
            raise ToolError(
                "CGU spec.spec missing required fields: clusters, managedPolicies"
            )

        namespace = cgu_spec["metadata"]["namespace"]

        # Create the CGU
        cgu_api.create(body=cgu_spec, namespace=namespace)

        return json.dumps(
            {
                "success": True,
                "cgu_name": cgu_spec["metadata"]["name"],
                "namespace": namespace,
                "clusters": cgu_spec["spec"]["clusters"],
                "policies": cgu_spec["spec"]["managedPolicies"],
                "enabled": cgu_spec["spec"].get("enable", False),
                "message": "CGU created successfully - review and enable when ready",
                "next_steps": [
                    f"Review CGU: kubectl get cgu {cgu_spec['metadata']['name']} -n {namespace} -o yaml",
                    f'Enable CGU: kubectl patch cgu {cgu_spec["metadata"]["name"]} -n {namespace} --type merge -p \'{{"spec":{{"enable":true}}}}\'',
                ],
            },
            indent=2,
        )

    except Exception as e:
        raise ToolError(f"Failed to create CGU: {str(e)}") from e


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


@mcp.prompt()
def create_cgu_workflow() -> str:
    """AI-driven workflow to create a CGU with full validation and analysis"""
    return """I need to create a ClusterGroupUpgrade (CGU) for my RHACM environment.

Please help me with this workflow:

1. **Ask for target criteria**: What label should I use to find clusters and policies? (e.g., environment=test)

2. **Analyze clusters**: Use get_clusters_by_label() to find target clusters and validate their health, readiness, and proper labeling.

3. **Analyze policies**: Use get_policies_by_label() to find policies targeting those clusters and validate they have proper Placements, PlacementBindings, and CGU annotations.

4. **Check conflicts**: Use get_active_cgus() to ensure no conflicting CGUs are running on the target clusters.

5. **Generate CGU spec**: Based on your analysis, create an appropriate CGU specification with smart defaults for batching, timeouts, and naming.

6. **Create CGU**: Use create_cgu() with the generated spec, starting with enable=false for safety.

7. **Provide next steps**: Give the user commands to review and enable the CGU when ready.

Please be thorough in your analysis and explain any issues you find with the clusters, policies, or existing CGUs."""


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

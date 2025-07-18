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

    CRITICAL FOR UPGRADE WORKFLOWS:
    When using this for upgrades, the AI should check BOTH the target label AND version label.
    For example: mcp-test=1 AND version=4.16 to find clusters ready for upgrade to 4.17.

    The AI should analyze the returned clusters for CGU readiness by checking:

    CLUSTER HEALTH VALIDATION:
    - status.conditions[] where type="ManagedClusterConditionAvailable" should have status="True"
    - status.conditions[] where type="HubAcceptedManagedCluster" should have status="True"
    - Look for any conditions with status="False" or reason indicating issues
    - IMPORTANT: Note the current version in status.version.kubernetes for upgrade planning

    UPGRADE READINESS:
    - Check status.clusterClaims[] for platform.open-cluster-management.io/version
    - This shows the current OCP version - crucial for determining if upgrade is needed
    - Compare with target version implied by policy placement selectors

    POLICY COMPLIANCE CHECK:
    After getting clusters, the AI should:
    1. Use get_policies_by_label() with same label to find upgrade policies
    2. Check each policy's status.status[] array to find NonCompliant clusters
    3. Only clusters with NonCompliant upgrade policies are candidates for CGU

    Args:
        label_key: Label key to match clusters (e.g., "mcp-test", "environment")
        label_value: Label value to match (e.g., "1", "test")

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
    """Get all Policies targeting clusters with specified label for upgrade analysis.

    CRITICAL UPGRADE POLICY IDENTIFICATION:
    The AI must identify upgrade policies by their NAMING PATTERN, not annotations:
    - Prep policies: contain "-prep" in the name (e.g., mcp-test-upgrade-prep)
    - OCP policies: contain "-ocp" in the name (e.g., mcp-test-upgrade-ocp)
    - OLM policies: contain "-olm" in the name (e.g., mcp-test-upgrade-olm)
    - Validate policies: contain "-validate" in the name (optional post-upgrade)

    POLICY ORDERING FOR CGU:
    The AI MUST order policies by their ran.openshift.io/ztp-deploy-wave annotation:
    1. Find the wave number in metadata.annotations["ran.openshift.io/ztp-deploy-wave"]
    2. Sort policies by wave number (lower numbers run first)
    3. Typical pattern: prep=500, ocp=501, olm=503
    4. If no wave annotation, assume wave=999

    COMPLIANCE STATUS CHECKING:
    For each policy, check status.status[] array:
    - Each entry has clustername and compliant fields
    - compliant="NonCompliant" means policy needs to be applied
    - Only include clusters with NonCompliant policies in CGU

    PLACEMENT VALIDATION:
    For each upgrade policy found:
    1. Find placement with name "placement-{policy-name}"
    2. Verify placement targets same label (in spec.predicates[].requiredClusterSelector)
    3. Check for version-specific targeting (e.g., version=4.16)
    4. All policies should target same namespace and label combination

    CGU POLICY LIST CREATION:
    The AI should create the managedPolicies list by:
    1. Filter to only upgrade policies (-prep, -ocp, -olm)
    2. Sort by wave annotation value
    3. Return ordered list of policy names for CGU spec

    Args:
        label_key: Label key that policies should target
        label_value: Label value that policies should target

    Returns:
        JSON with Policies, Placements, and PlacementBindings for analysis
    """
    try:
        ctx = get_ctx_or_raise()
        policy_api = ctx.dynamic_client.resources.get(
            api_version="policy.open-cluster-management.io/v1", kind="Policy"
        )
        all_policies = policy_api.get()
        placement_api = ctx.dynamic_client.resources.get(
            api_version="cluster.open-cluster-management.io/v1beta1", kind="Placement"
        )
        all_placements = placement_api.get()
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
def create_cgu(cgu_spec: dict) -> str:
    """Create a ClusterGroupUpgrade CR with the provided specification.

    CRITICAL CGU SPEC REQUIREMENTS FOR UPGRADES:

    The AI MUST construct the managedPolicies array in WAVE ORDER:
    1. Extract wave annotations from each policy
    2. Sort by wave number (ascending)
    3. Ensure prep runs before ocp, ocp before olm

    Example correct ordering:
    "managedPolicies": [
        "mcp-test-upgrade-prep",      # wave 500
        "mcp-test-upgrade-ocp",       # wave 501
        "mcp-test-upgrade-olm"        # wave 503
    ]

    REQUIRED CGU SPEC STRUCTURE:
    {
        "apiVersion": "ran.openshift.io/v1alpha1",
        "kind": "ClusterGroupUpgrade",
        "metadata": {
            "name": "upgrade-{env}-{timestamp}",  # e.g. upgrade-test-1704834521
            "namespace": "ztp-core-policies"      # MUST match policy namespace
        },
        "spec": {
            "clusters": ["cluster1", "cluster2"], # Only NonCompliant clusters
            "managedPolicies": ["ordered-list"],  # CRITICAL: Wave-ordered policies
            "enable": false,                      # Always start disabled
            "preCaching": false,                  # Set true for image pre-caching
            "remediationStrategy": {
                "maxConcurrency": 1,              # 1 for prod, 2+ for test
                "timeout": 240                    # Minutes, increase for slow upgrades
            }
        }
    }

    NAMESPACE REQUIREMENTS:
    - CGU MUST be in same namespace as policies (typically ztp-core-policies)
    - Check policy namespace from get_policies_by_label results

    CLUSTER SELECTION:
    - Only include clusters that have NonCompliant upgrade policies
    - Verify clusters are healthy before including
    - Check current version label to ensure upgrade is needed

    SAFETY PRACTICES:
    - Always create with enable=false
    - Let user review before enabling
    - Use descriptive names with timestamps
    - Set appropriate maxConcurrency based on environment

    Args:
        cgu_spec: Complete CGU specification dict

    Returns:
        JSON with creation status and next steps including enable command
    """

    try:
        ctx = get_ctx_or_raise()
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )
        if not all(key in cgu_spec for key in ["apiVersion", "kind", "metadata", "spec"]):
            raise ToolError("CGU spec missing required fields: apiVersion, kind, metadata, spec")
        if not all(key in cgu_spec["spec"] for key in ["clusters", "managedPolicies"]):
            raise ToolError("CGU spec.spec missing required fields: clusters, managedPolicies")
        namespace = cgu_spec["metadata"]["namespace"]
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


@mcp.tool()
def patch_cgu(cgu_name: str, namespace: str, patch_spec: dict) -> str:
    """Patch an existing ClusterGroupUpgrade CR (use for enabling CGUs).

    PRIMARY USE CASE - ENABLING CGU:
    To enable a CGU after creation, use patch_spec: {"spec": {"enable": true}}

    This tool is the programmatic way to enable CGUs instead of using kubectl.
    The AI should offer to enable the CGU after successful creation.

    OTHER PATCH OPERATIONS:
    - Update timeout: {"spec": {"remediationStrategy": {"timeout": 480}}}
    - Change concurrency: {"spec": {"remediationStrategy": {"maxConcurrency": 2}}}
    - Add clusters: {"spec": {"clusters": ["cluster1", "cluster2", "cluster3"]}}

    IMPORTANT CONSIDERATIONS:
    - Can only patch CGUs that are not yet completed
    - Enabling starts the upgrade process immediately
    - Monitor with get_cluster_status() after enabling

    Args:
        cgu_name: Name of the CGU to patch
        namespace: Namespace containing the CGU
        patch_spec: JSON patch to apply (usually {"spec": {"enable": true}})

    Returns:
        JSON with patch status and current CGU state
    """
    try:
        ctx = get_ctx_or_raise()
        cgu_api = ctx.dynamic_client.resources.get(
            api_version="ran.openshift.io/v1alpha1", kind="ClusterGroupUpgrade"
        )

        # Apply the patch
        patched_cgu = cgu_api.patch(
            name=cgu_name,
            namespace=namespace,
            body=patch_spec,
            content_type="application/merge-patch+json"
        )

        # Extract key status info
        status_info = {}
        if hasattr(patched_cgu, 'status') and patched_cgu.status:
            status_info = {
                "state": patched_cgu.status.get("status", {}).get("currentBatch", "Unknown"),
                "completedClusters": len(patched_cgu.status.get("status", {}).get("succeeded", [])),
                "failedClusters": len(patched_cgu.status.get("status", {}).get("failed", [])),
            }

        return json.dumps({
            "success": True,
            "cgu_name": cgu_name,
            "namespace": namespace,
            "enabled": patched_cgu.spec.get("enable", False),
            "patch_applied": patch_spec,
            "status": status_info,
            "monitor_command": f"kubectl get cgu {cgu_name} -n {namespace} -w"
        }, indent=2)

    except Exception as e:
        raise ToolError(f"Failed to patch CGU: {str(e)}") from e


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

@mcp.prompt()
def create_upgrade_cgu_workflow() -> str:
    return """AI-driven workflow to create and manage a cluster upgrade via CGU.

    This workflow guides you through creating a ClusterGroupUpgrade for OCP upgrades.

    COMPLETE UPGRADE WORKFLOW:

    1. **Identify target clusters**:
       - Ask user for the label selector (e.g., mcp-test=1)
       - Use get_clusters_by_label() to find clusters
       - Check cluster versions to confirm upgrade is needed

    2. **Find upgrade policies**:
       - Use get_policies_by_label() with same label
       - Identify policies with -prep, -ocp, -olm in names
       - Extract wave numbers from annotations
       - Check policy compliance status for each cluster

    3. **Validate prerequisites**:
       - Only include clusters with NonCompliant upgrade policies
       - Verify cluster health (Available=True)
       - Check no active CGUs on target clusters with get_active_cgus()
       - Ensure all policies are in same namespace

    4. **Create ordered policy list**:
       - Sort policies by wave annotation (ascending)
       - Typical order: prep (500) → ocp (501) → olm (503)
       - Only include upgrade policies, not validate policies

    5. **Generate CGU**:
       - Name: upgrade-{label}-{timestamp}
       - Namespace: same as policies (usually ztp-core-policies)
       - Clusters: only healthy clusters with NonCompliant policies
       - managedPolicies: wave-ordered list
       - enable: false (for safety)
       - maxConcurrency: 1 for prod, 2+ for test

    6. **Create and enable**:
       - Use create_cgu() with generated spec
       - Review the created CGU with user
       - Use patch_cgu() to enable when ready: {"spec": {"enable": true}}

    7. **Monitor progress**:
       - Check CGU status with get_active_cgus()
       - Monitor cluster versions with get_cluster_status()
       - Watch for version label updates on ManagedClusters

    Remember: The key to successful upgrades is proper policy ordering based on waves!
    """

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

"""AgentCore Platform v1.0"""

# Cat 2, DocGenerationAgent pattern — AgentBaseGraph direct inheritance.
# 3-node fixed pipeline (PreProcessNode -> MainNode -> PostProcessNode).
# MainNode runs 4 internal passes (A: agreement term extraction (LLM),
# B: deterministic accrual math, C: 下請法 Art.4 timeline check,
# D: dispute brief generation (LLM)) sequentially inside execute() — this
# stays a single node (no multi-node routing complexity, no GraphNode/inner
# subgraph needed). See docs/02_design.md and the source proposal §4/§10-3
# for the architecture rationale.

from framework.graph.agent_base_graph import AgentBaseGraph
from src.nodes.pre_process_node import PreProcessNode
from src.nodes.main_node import MainNode
from src.nodes.post_process_node import PostProcessNode
from src.schemas.state import State


class RetailVendorRebateTradePromoReconciliationAgent(AgentBaseGraph):
    """Cat 2 fixed-pipeline graph for vendor rebate reconciliation."""

    @property
    def name(self) -> str:
        return "RetailVendorRebateTradePromoReconciliationAgent"

    @property
    def state_schema(self) -> type:
        return State

    def register_nodes(self) -> None:
        super().register_nodes()  # injects InitializeNode + FinalizeNode

        self._nodes["pre_process"] = PreProcessNode()
        self._nodes["main"] = MainNode(llm=self.config.get("llm"))
        self._nodes["post_process"] = PostProcessNode()

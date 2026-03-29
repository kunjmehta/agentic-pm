"""Tests for graph topology: node count, edges, and routing logic."""

import sys
from pathlib import Path

project_root = Path(__file__).parent.parent.parent
sys.path.insert(0, str(project_root))

import pytest
from src.langgraph.graph import (
    build_graph,
    route_after_market_guard,
    route_after_portfolio_guard,
    route_after_portfolio_node,
    route_after_quant_node,
)


@pytest.fixture(scope="module")
def compiled_graph():
    """Build graph once for all topology tests."""
    return build_graph()


class TestGraphTopology:
    """Tests that the compiled graph has the expected structure."""

    def test_graph_compiles(self, compiled_graph):
        assert compiled_graph is not None

    def test_expected_node_count(self, compiled_graph):
        graph_repr = compiled_graph.get_graph()
        node_names = {n.name for n in graph_repr.nodes.values()}
        expected = {
            "__start__", "classify_intent", "market_hours_guard",
            "portfolio_guard", "portfolio_node", "quant_node",
            "backtester_node", "synthesizer", "__end__",
        }
        assert expected == node_names

    def test_expected_edge_count(self, compiled_graph):
        graph_repr = compiled_graph.get_graph()
        # 15 edges: 4 fixed + 11 conditional
        assert len(graph_repr.edges) == 15

    def test_start_connects_to_classifier(self, compiled_graph):
        graph_repr = compiled_graph.get_graph()
        edge_pairs = {(e.source, e.target) for e in graph_repr.edges}
        assert ("__start__", "classify_intent") in edge_pairs

    def test_synthesizer_connects_to_end(self, compiled_graph):
        graph_repr = compiled_graph.get_graph()
        edge_pairs = {(e.source, e.target) for e in graph_repr.edges}
        assert ("synthesizer", "__end__") in edge_pairs

    def test_backtester_connects_to_synthesizer(self, compiled_graph):
        graph_repr = compiled_graph.get_graph()
        edge_pairs = {(e.source, e.target) for e in graph_repr.edges}
        assert ("backtester_node", "synthesizer") in edge_pairs


class TestRoutingFunctions:
    """Unit tests for conditional edge routing functions."""

    def test_market_guard_routes_to_synthesizer_on_error(self):
        state = {"routing_error": "Market closed"}
        assert route_after_market_guard(state) == "synthesizer"

    def test_market_guard_routes_to_portfolio_guard_on_pass(self):
        state = {"routing_error": None}
        assert route_after_market_guard(state) == "portfolio_guard"

    def test_portfolio_guard_routes_to_synthesizer_on_error(self):
        state = {"routing_error": "Risk limit exceeded"}
        assert route_after_portfolio_guard(state) == "synthesizer"

    def test_portfolio_guard_routes_portfolio_intent(self):
        state = {"routing_error": None, "intent": "portfolio"}
        assert route_after_portfolio_guard(state) == "portfolio_node"

    def test_portfolio_guard_routes_quant_intent(self):
        state = {"routing_error": None, "intent": "quant"}
        assert route_after_portfolio_guard(state) == "quant_node"

    def test_portfolio_guard_routes_backtest_intent(self):
        state = {"routing_error": None, "intent": "backtest"}
        assert route_after_portfolio_guard(state) == "portfolio_node"

    def test_portfolio_guard_routes_full_analysis(self):
        state = {"routing_error": None, "intent": "full_analysis"}
        assert route_after_portfolio_guard(state) == "portfolio_node"

    def test_portfolio_node_routes_portfolio_to_synthesizer(self):
        state = {"intent": "portfolio"}
        assert route_after_portfolio_node(state) == "synthesizer"

    def test_portfolio_node_routes_backtest_to_backtester(self):
        state = {"intent": "backtest"}
        assert route_after_portfolio_node(state) == "backtester_node"

    def test_portfolio_node_routes_full_analysis_to_quant(self):
        state = {"intent": "full_analysis"}
        assert route_after_portfolio_node(state) == "quant_node"

    def test_quant_node_routes_quant_to_synthesizer(self):
        state = {"intent": "quant"}
        assert route_after_quant_node(state) == "synthesizer"

    def test_quant_node_routes_full_analysis_to_backtester(self):
        state = {"intent": "full_analysis"}
        assert route_after_quant_node(state) == "backtester_node"

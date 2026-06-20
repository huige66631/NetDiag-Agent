from netdiag_agent.graph import run_netdiag_graph
from netdiag_agent.react import ReactObservation


def _memory_init(tmp_path):
    return lambda self, path=tmp_path / "memory.jsonl": setattr(self, "path", tmp_path / "memory.jsonl")


def test_langgraph_react_loop_runs_with_mocked_tools(monkeypatch, tmp_path):
    def fake_execute(action, step, user_context, observations):
        if action.tool == "get_network_profile":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=True,
                summary="默认网关：192.168.1.1；DNS：223.5.5.5",
                data={"gateway": "192.168.1.1", "dns_servers": ["223.5.5.5"]},
            )
        if action.tool == "ping_target":
            target = action.args["target"]
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"target": target},
                success=True,
                summary=f"{target} 平均延迟 20 ms，丢包 0%",
                data={
                    "target_name": target,
                    "result": {
                        "target": "192.168.1.1" if target == "gateway" else "223.5.5.5",
                        "success": True,
                        "packets_sent": 4,
                        "packets_received": 4,
                        "packet_loss_percent": 0,
                        "min_ms": 10,
                        "avg_ms": 20,
                        "max_ms": 30,
                        "raw": "",
                        "error": None,
                    },
                },
            )
        if action.tool == "dns_lookup":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"host": "baidu"},
                success=True,
                summary="baidu DNS 成功，耗时 30 ms",
                data={
                    "target_name": "baidu",
                    "result": {
                        "host": "www.baidu.com",
                        "success": True,
                        "addresses": ["1.1.1.1"],
                        "elapsed_ms": 30,
                        "dns_server": "223.5.5.5",
                        "raw": "",
                        "error": None,
                    },
                },
            )
        if action.tool == "rag_search":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={"query": user_context},
                success=True,
                summary="检索到：DNS 故障排查",
                data={"hits": [{"title": "DNS 故障排查", "source": "dns.md", "content": "DNS 慢需要对比解析。", "distance": 0.1}]},
            )
        if action.tool == "recall_memory":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=True,
                summary="没有找到可参考的历史诊断记录，本次将按当前检测结果独立分析。",
                data={"records": []},
            )
        return ReactObservation(
            step=step,
            thought=action.thought,
            tool=action.tool,
            args=action.args,
            success=True,
            summary="结束",
            data={},
        )

    monkeypatch.setattr("netdiag_agent.graph.execute_react_tool", fake_execute)
    monkeypatch.setattr("netdiag_agent.memory.NetworkMemory.__init__", _memory_init(tmp_path))

    state = run_netdiag_graph(
        user_context="网页偶尔打不开",
        requested_mode="quick",
        use_llm_planner=False,
        use_llm_report=False,
        max_steps=7,
    )

    assert state["snapshot"].diagnosis is not None
    assert [item.tool for item in state["react_observations"]][:3] == [
        "get_network_profile",
        "ping_target",
        "ping_target",
    ]
    assert any(item.tool == "rag_search" for item in state["react_observations"])
    assert "llm.decide:get_network_profile" in state["graph_steps"]
    assert "react.synthesize" in state["graph_steps"]


def test_repeated_tool_calls_trigger_guard_stop(monkeypatch, tmp_path):
    def repeated_execute(action, step, user_context, observations):
        if action.tool == "get_network_profile":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=True,
                summary="默认网关：192.168.1.1；DNS：223.5.5.5",
                data={"gateway": "192.168.1.1", "dns_servers": ["223.5.5.5"]},
            )
        return ReactObservation(
            step=step,
            thought=action.thought,
            tool="ping_target",
            args={"target": "public_dns"},
            success=True,
            summary="public_dns 平均延迟 20 ms，丢包 0%",
            data={
                "target_name": "public_dns",
                "result": {
                    "target": "223.5.5.5",
                    "success": True,
                    "packets_sent": 4,
                    "packets_received": 4,
                    "packet_loss_percent": 0,
                    "min_ms": 10,
                    "avg_ms": 20,
                    "max_ms": 30,
                    "raw": "",
                    "error": None,
                },
            },
        )

    def repeated_fallback(user_context, observations, requested_mode="auto", max_steps=8):
        if not observations:
            from netdiag_agent.react import ReactAction

            return ReactAction("先读网络信息。", "get_network_profile", {})
        from netdiag_agent.react import ReactAction

        return ReactAction("继续测同一个目标。", "ping_target", {"target": "public_dns"})

    monkeypatch.setattr("netdiag_agent.graph.execute_react_tool", repeated_execute)
    monkeypatch.setattr("netdiag_agent.graph.fallback_react_action", repeated_fallback)
    monkeypatch.setattr("netdiag_agent.memory.NetworkMemory.__init__", _memory_init(tmp_path))

    state = run_netdiag_graph(
        user_context="一直很卡",
        requested_mode="quick",
        use_llm_planner=False,
        use_llm_report=False,
        max_steps=8,
    )

    assert "停止自动循环并转入保底诊断" in state["stop_reason"]
    assert len(state["react_observations"]) == 3


def test_consecutive_failures_trigger_guard_stop(monkeypatch, tmp_path):
    def failing_execute(action, step, user_context, observations):
        if action.tool == "get_network_profile":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=True,
                summary="默认网关：192.168.1.1；DNS：223.5.5.5",
                data={"gateway": "192.168.1.1", "dns_servers": ["223.5.5.5"]},
            )
        return ReactObservation(
            step=step,
            thought=action.thought,
            tool=action.tool,
            args=action.args,
            success=False,
            summary="Ping 检测失败：目标不可达或命令执行失败。",
            data={"error": "timeout"},
        )

    def failing_fallback(user_context, observations, requested_mode="auto", max_steps=8):
        if not observations:
            from netdiag_agent.react import ReactAction

            return ReactAction("先读网络信息。", "get_network_profile", {})
        from netdiag_agent.react import ReactAction

        return ReactAction("继续测试公网。", "ping_target", {"target": "public_dns"})

    monkeypatch.setattr("netdiag_agent.graph.execute_react_tool", failing_execute)
    monkeypatch.setattr("netdiag_agent.graph.fallback_react_action", failing_fallback)
    monkeypatch.setattr("netdiag_agent.memory.NetworkMemory.__init__", _memory_init(tmp_path))

    state = run_netdiag_graph(
        user_context="网络断断续续",
        requested_mode="quick",
        use_llm_planner=False,
        use_llm_report=False,
        max_steps=8,
    )

    assert "最近连续 2 次工具调用失败" in state["stop_reason"]
    assert len(state["react_observations"]) == 3


def test_custom_target_is_added_to_plan(monkeypatch, tmp_path):
    def fake_execute(action, step, user_context, observations):
        if action.tool == "get_network_profile":
            return ReactObservation(
                step=step,
                thought=action.thought,
                tool=action.tool,
                args={},
                success=True,
                summary="默认网关：192.168.1.1；DNS：223.5.5.5",
                data={"gateway": "192.168.1.1", "dns_servers": ["223.5.5.5"]},
            )
        return ReactObservation(
            step=step,
            thought=action.thought,
            tool="final_answer",
            args=action.args,
            success=True,
            summary="结束",
            data={},
        )

    monkeypatch.setattr("netdiag_agent.graph.execute_react_tool", fake_execute)
    monkeypatch.setattr("netdiag_agent.memory.NetworkMemory.__init__", _memory_init(tmp_path))

    state = run_netdiag_graph(
        user_context="只想测自定义目标",
        requested_mode="quick",
        use_llm_planner=False,
        use_llm_report=False,
        custom_target="example.com",
        max_steps=2,
    )

    assert state["plan"].targets["custom"] == "example.com"

from core.contracts import AgentRequest, ToolSpec
from modules.discovery.service import DiscoveryService


def test_retrieval_returns_only_allowlisted_tools_and_adds_safe_lookup_closure() -> None:
    catalog = [
        ToolSpec(name="sms.send", description="send message"),
        ToolSpec(name="contacts.search", description="search contacts"),
        ToolSpec(name="phone.call", description="call a contact"),
        ToolSpec(name="sys.ask_missing_info", description="report missing inputs", kind="meta"),
        ToolSpec(name="bank.transfer", description="transfer money"),
    ]
    request = AgentRequest(sample_id="s1", transcript="Nhắn cho Lan", context={})

    candidates = DiscoveryService(top_k=1).retrieve(request, catalog)

    names = {tool.name for tool in candidates}
    assert names == {"sms.send", "contacts.search"}
    assert "sys.ask_missing_info" not in names
    assert "bank.transfer" not in names

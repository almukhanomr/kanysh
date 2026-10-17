import sys

import pytest
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client


@pytest.mark.asyncio
async def test_real_mcp_sdk_stdio_roundtrip(tmp_path):
    params = StdioServerParameters(
        command=sys.executable, args=["-m", "opensubsurface.cli", "--home", str(tmp_path / "mcp"), "mcp"]
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            listing = await session.list_tools()
            assert "volumetrics_calculate" in {t.name for t in listing.tools}
            assert not any(t.name.startswith("cloud_") for t in listing.tools)
            assert "install_policy" not in {t.name for t in listing.tools}
            result = await session.call_tool(
                "project_create", arguments={"request": {"name": "MCP", "vertical_datum": "TEST"}}
            )
            assert not result.isError
            import json

            value = json.loads(result.content[0].text)
            assert value["result"]["name"] == "MCP"
            listed = await session.call_tool("project_list", arguments={"request": {}})
            assert not listed.isError

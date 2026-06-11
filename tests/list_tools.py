"""列出 FastMCP 服务器已注册的所有工具及其参数定义（等价于 Inspector 的工具列表）。"""
import asyncio
import json
import sys
sys.path.insert(0, "D:/automan/coding/projects/cnki-mcp")

from server import mcp


async def main():
    tools = await mcp.list_tools()
    print("=" * 60)
    print("已注册工具数: {}".format(len(tools)))
    print("=" * 60)
    for t in tools:
        print("\n● {}".format(t.name))
        desc = (t.description or "").strip().splitlines()
        if desc:
            print("  说明: {}".format(desc[0]))
        props = (t.inputSchema or {}).get("properties", {})
        required = set((t.inputSchema or {}).get("required", []))
        for pname, pinfo in props.items():
            mark = "*" if pname in required else " "
            ptype = pinfo.get("type", "?")
            print("    {}{} : {}".format(mark, pname, ptype))


if __name__ == "__main__":
    asyncio.run(main())

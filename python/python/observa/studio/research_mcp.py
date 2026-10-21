"""Conversation-scoped Studio tools, separate from Observa's read-only MCP."""
from __future__ import annotations

import asyncio
import json
import os
import urllib.error
import urllib.request


def call(action: str, payload: dict):
    request = urllib.request.Request(
        os.environ["OBSERVA_STUDIO_URL"] + "/research/" + action,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json",
                 "Authorization": "Bearer " + os.environ["OBSERVA_STUDIO_TOKEN"]},
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:
        raise ValueError(exc.read().decode()) from exc


def get_project_context() -> dict:
    """Read the canonical strategy contract, example, project and available data."""
    return call("context", {})


async def prepare_backtest(
    strategy_file: str,
    dataset_file: str = "@sample",
    config: dict | None = None,
    class_name: str | None = None,
    support_files: list[str] | None = None,
    title: str = "",
) -> dict:
    """Snapshot project-relative Python and CSV, ask for human approval in Studio,
    then validate and run the canonical engine. This waits for the user's decision
    and actual execution. @sample/@demo select bundled data. No financial
    computations happen in this tool. Include every local imported support file.
    Config accepts observa.Config fields except source paths.
    """
    job = await asyncio.to_thread(call, "prepare", dict(
        strategy_file=strategy_file, dataset_file=dataset_file, config=config or {},
        class_name=class_name, support_files=support_files or [], title=title))
    while job["status"] not in {"completed", "failed", "cancelled", "declined", "interrupted"}:
        await asyncio.sleep(1)
        job = await asyncio.to_thread(call, "experiment", {"id": job["id"]})
    return job


def get_experiment(experiment_id: str, position_id: str | None = None) -> dict:
    """Read canonical metrics, trades and rejections. Supply an exact position_id
    to inspect its orders, fills, reasons, costs and annotations."""
    return call("experiment", {"id": experiment_id, "position_id": position_id})


def publish_artifact(artifact: dict) -> dict:
    """Publish an agent-generated research interpretation in this conversation.
    Supply title, description, experiment_ids and one format:
    {kind:'plot', mark:'line'|'scatter'|'bar'|'heatmap', x_label, y_label,
      data:[{x:number,y:number,value?:number}]};
    {kind:'table',columns:[string],rows:[[string|number|null]]};
    {kind:'markdown',text:string}.
    Never use this interface to invent canonical financial metrics.
    """
    return call("artifact", artifact)


def main():
    from mcp.server import MCPServer
    server = MCPServer("observa_studio")
    for tool in (get_project_context, prepare_backtest, get_experiment, publish_artifact):
        server.add_tool(tool)
    server.run(transport="stdio")


if __name__ == "__main__":
    main()

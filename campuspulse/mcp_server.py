"""Real MCP stdio server. Each query gets an isolated server process."""
from mcp.server.fastmcp import FastMCP
from campuspulse import tools

mcp = FastMCP("CampusPulse tools")
_documents: list[dict] = []


@mcp.tool()
def load_materials(documents: list[dict]) -> dict:
    """Internal initialization of user-uploaded excerpts. Not exposed to Gemini."""
    if len(documents) > 5 or sum(len(str(d.get("text", ""))) for d in documents) > 60000:
        raise ValueError("Максимум 5 документов и 60000 символов.")
    _documents[:] = [{"name": str(d["name"])[:200], "text": str(d["text"])} for d in documents]
    return {"loaded": len(_documents)}


@mcp.tool()
def get_current_time(timezone: str = "Asia/Almaty") -> dict:
    """Get the real current time and date. Use before resolving relative dates."""
    return tools.current_time(timezone)


@mcp.tool()
def get_github_issues(repository: str, limit: int = 10) -> dict:
    """Fetch live open GitHub issues. repository is owner/repo. Unknown deadlines remain null."""
    return tools.github_issues(repository, limit)


@mcp.tool()
def read_github_readme(repository: str) -> dict:
    """Read the live README of a GitHub repository to inspect course instructions."""
    return tools.github_readme(repository)


@mcp.tool()
def calculate_deadline(due_at: str, timezone: str = "Asia/Almaty") -> dict:
    """Calculate remaining minutes to an ISO date or datetime using the real clock."""
    return tools.deadline_status(due_at, timezone)


@mcp.tool()
def search_study_materials(query: str) -> dict:
    """Find relevant excerpts in the current user's uploaded study materials. Cite the source."""
    return tools.search_materials(query, _documents)


@mcp.tool()
def plan_study_week(tasks: list[dict], daily_minutes: int = 120, days: int = 7,
                    timezone: str = "Asia/Almaty", start_hour: int = 18) -> dict:
    """Build a deterministic study schedule. Each task needs title, optional due_at (ISO),
    estimated_minutes (integer, null defaults to 60), source_url. Never invent deadlines.
    Respects daily capacity and reports work that cannot fit before deadlines.
    """
    return tools.build_plan(tasks, daily_minutes, days, timezone, start_hour)


if __name__ == "__main__":
    mcp.run(transport="stdio")

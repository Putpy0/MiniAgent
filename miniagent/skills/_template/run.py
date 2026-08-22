"""Skill template entry point - replace with your skill implementation."""

from typing import Any, Optional


async def execute(query: str, context: Optional[dict] = None) -> Any:
    """
    Execute the skill with the given query.

    This is a template function - replace with your actual skill logic.

    Args:
        query: The user's query or request
        context: Optional context dictionary with additional information

    Returns:
        Skill execution result (type depends on skill purpose)

    Example:
        >>> result = await execute("example query")
        >>> print(result)
    """
    # TODO: Implement your skill logic here
    return {
        "status": "success",
        "message": "Skill template executed successfully",
        "query": query,
        "context": context or {},
    }


def get_info() -> dict:
    """
    Get information about this skill.

    Returns:
        Dictionary with skill metadata
    """
    return {
        "name": "skill_template",
        "version": "1.0.0",
        "description": "Template for creating new MiniAgent skills",
    }


if __name__ == "__main__":
    # Test the skill when run directly
    import asyncio

    async def test():
        result = await execute("test query", {"test": True})
        print(f"Test result: {result}")

    asyncio.run(test())

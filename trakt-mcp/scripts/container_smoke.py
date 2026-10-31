"""Run on a Linux CI host after starting the container on localhost:18765."""
import asyncio
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client


async def main():
    async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + 'x' * 48}) as http:
        async with Client(streamable_http_client('http://127.0.0.1:18765/mcp', http_client=http)) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert 'trakt_auth_start' not in tools
            assert 'trakt_get_movie_ratings_summary' in tools
            assert 'trakt_get_user_preferences' in tools
            assert not any(name in tools for name in ('trakt_get_streaming_shortlist', 'trakt_get_streaming_providers', 'trakt_get_movie_streaming'))
            for _ in range(2):
                result = await client.call_tool('trakt_get_status', {})
                assert not result.is_error
                assert result.structured_content['trakt_tokens_stored'] is True
    print('Container MCP handshake, default tool permissions, and repeated status calls passed.')


asyncio.run(main())

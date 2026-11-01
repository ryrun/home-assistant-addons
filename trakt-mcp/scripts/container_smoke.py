"""Run locally after starting the test server or container on localhost:18765."""
import asyncio
from pathlib import Path
import sys
import httpx2
from mcp import Client
from mcp.client.streamable_http import streamable_http_client

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from version import VERSION


async def main():
    async with httpx2.AsyncClient(headers={'Authorization': 'Bearer ' + 'x' * 48}) as http:
        async with Client(streamable_http_client('http://127.0.0.1:18765/mcp', http_client=http)) as client:
            tools = {tool.name for tool in (await client.list_tools()).tools}
            assert 'trakt_auth_start' not in tools
            assert 'trakt_get_movie_ratings_summary' in tools
            assert 'trakt_get_user_preferences' in tools
            assert {'trakt_get_show_progress', 'trakt_get_history', 'trakt_get_collection',
                    'trakt_get_playback', 'trakt_get_user_stats', 'trakt_get_lists'} <= tools
            assert len(tools) == 41
            assert not any(name in tools for name in ('trakt_get_streaming_shortlist', 'trakt_get_streaming_providers', 'trakt_get_movie_streaming'))
            results = await asyncio.gather(*(client.call_tool('trakt_get_status', {}) for _ in range(4)))
            for result in results:
                assert not result.is_error
                assert result.structured_content['trakt_tokens_stored'] is True
                assert result.structured_content['server_version'] == VERSION
    print('Container MCP handshake, default tool permissions, and concurrent status calls passed.')


asyncio.run(main())

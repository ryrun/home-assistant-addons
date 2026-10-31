from unittest.mock import AsyncMock

import httpx
import pytest

from errors import TraktError
from streaming import StreamingClient


MOVIE = {'title': 'Example', 'year': 2024, 'ids': {'trakt': 1, 'tmdb': 123}}


def provider(identifier, name):
    return {'provider_id': identifier, 'provider_name': name}


@pytest.mark.asyncio
async def test_country_offers_and_subscriptions_are_separate_and_fresh():
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == 'GET'
        assert request.url.host == 'api.themoviedb.org'
        assert request.headers['Authorization'] == 'Bearer private-tmdb'
        assert 'trakt-api-key' not in request.headers
        assert 'private-tmdb' not in str(request.url)
        if request.url.path.endswith('/watch/providers/movie'):
            return httpx.Response(200, json={'results': [provider(8, 'Netflix'), provider(9, 'Amazon Video'), provider(11, 'Freevee'), provider(12, 'Other Service')]})
        return httpx.Response(200, json={'results': {
            'DE': {'link': 'https://www.themoviedb.org/movie/123/watch?locale=DE',
                   'flatrate': [provider(8, 'Netflix'), provider(99, 'Amazon Prime Video with Ads')],
                   'rent': [provider(9, 'Amazon Video')],
                   'buy': [provider(10, 'Apple TV')], 'ads': [provider(11, 'Freevee')]},
            'US': {'flatrate': [provider(12, 'Other Service')]}}})
    trakt = AsyncMock()
    trakt.details.return_value = MOVIE
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = StreamingClient(http, trakt, 'private-tmdb', services=['netflix', 'Amazon Video', 'Freevee'])
        for _ in range(2):
            result = await client.availability('1')
            assert result['country'] == 'DE'
            assert result['available_with_configured_subscription'] is True
            assert [p['provider_name'] for p in result['subscription_matches']] == ['Netflix']
            assert result['offers']['rent'][0]['provider_name'] == 'Amazon Video'
            assert 'JustWatch' in result['attribution']
            assert result['checked_at']
            assert result['listing_url'].startswith('https://www.themoviedb.org/')
            assert 'private-tmdb' not in str(result)
        assert sum(r.url.path.endswith('/123/watch/providers') for r in requests) == 2  # Offers remain fresh.
        other = await client.availability('1', 'us', services=['Other Service'])
        assert other['country'] == 'US'
        assert other['available_with_configured_subscription'] is True


@pytest.mark.asyncio
async def test_no_country_data_means_unknown_not_unavailable():
    trakt = AsyncMock()
    trakt.details.return_value = MOVIE
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'results': [provider(8, 'Netflix')]} if r.url.path.endswith('/watch/providers/movie') else {'results': {}}))) as http:
        result = await StreamingClient(http, trakt, 'token', services=['Netflix']).availability('1')
        assert result['status'] == 'no_data'
        assert result['available_with_configured_subscription'] is None
        assert result['subscription_matches'] == []


@pytest.mark.asyncio
async def test_no_subscription_match_does_not_count_rental_or_channels():
    trakt = AsyncMock()
    trakt.details.return_value = MOVIE
    payload = {'results': {'DE': {'rent': [provider(1, 'Amazon Prime Video')],
                                 'flatrate': [provider(2, 'Paramount+ Amazon Channel')],
                                 'ads': [provider(3, 'Freevee')]}}}
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'results': [provider(1, 'Amazon Prime Video'), provider(3, 'Freevee')]} if r.url.path.endswith('/watch/providers/movie') else payload))) as http:
        client = StreamingClient(http, trakt, 'token', services=['Amazon Prime Video', 'Freevee'])
        result = await client.availability('1')
        assert result['available_with_configured_subscription'] is False
        assert result['subscription_matches'] == []
        assert (await client.availability('1', services=[]))['available_with_configured_subscription'] is None


@pytest.mark.asyncio
async def test_missing_setup_or_tmdb_id_is_clear():
    trakt = AsyncMock()
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: pytest.fail('No TMDb request expected'))) as http:
        client = StreamingClient(http, trakt)
        with pytest.raises(TraktError, match='tmdb_read_access_token'):
            await client.availability('1')
        trakt.details.assert_not_called()
        client.token = 'token'
        trakt.details.return_value = {'ids': {'tmdb': None}}
        with pytest.raises(TraktError, match='TMDb-ID'):
            await client.availability('1')
        with pytest.raises(TraktError, match='ISO-Code'):
            await client.availability('1', '../DE')


@pytest.mark.asyncio
async def test_provider_discovery():
    def handler(request):
        assert request.url.path == '/3/watch/providers/movie'
        assert request.url.params['watch_region'] == 'AT'
        return httpx.Response(200, json={'results': [provider(8, 'Netflix')]})
    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        result = await StreamingClient(http, None, 'token').providers('at')
        assert result['items'] == [provider(8, 'Netflix')]


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [302, 401, 403, 404, 429, 500])
async def test_tmdb_errors_are_sanitized(status):
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(status, text='private-response'))) as http:
        with pytest.raises(TraktError) as error:
            await StreamingClient(http, None, 'private-token').providers()
        assert 'private-' not in str(error.value)


@pytest.mark.asyncio
async def test_malformed_response_cannot_claim_availability():
    trakt = AsyncMock()
    trakt.details.return_value = MOVIE
    async with httpx.AsyncClient(transport=httpx.MockTransport(lambda r: httpx.Response(200, json={'results': {'DE': {'flatrate': [{}]}}}))) as http:
        with pytest.raises(TraktError, match='Anbieterinformationen'):
            await StreamingClient(http, trakt, 'token').availability('1')

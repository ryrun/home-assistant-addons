"""Only controlled messages may cross the MCP boundary."""
class TraktError(Exception):
    pass


def check_response(response):
    status = response.status_code
    if 200 <= status < 300:
        return
    messages = {
        400: 'Trakt rejected the request.',
        401: 'Trakt authorization is invalid. Reauthorize through the add-on configuration or the optional trakt_auth_start tool.',
        403: 'Trakt denied access. Check the API app and permissions.',
        404: 'Movie or Trakt resource not found.',
        429: 'Trakt rate limit reached. Please retry later.',
    }
    raise TraktError(messages.get(status, 'Trakt is temporarily unavailable.'))


def json_data(response):
    try:
        return response.json()
    except ValueError:
        raise TraktError('Trakt returned an invalid response.') from None

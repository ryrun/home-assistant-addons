"""Only controlled messages may cross the MCP boundary."""
class TraktError(Exception):
    pass


def check_response(response):
    status = response.status_code
    if 200 <= status < 300:
        return
    messages = {
        400: 'Trakt hat die Anfrage abgelehnt.',
        401: 'Trakt-Anmeldung ungültig. Bitte trakt_auth_start erneut aufrufen.',
        403: 'Trakt verweigert den Zugriff. API-App und Berechtigungen prüfen.',
        404: 'Film oder Trakt-Ressource nicht gefunden.',
        429: 'Trakt-Rate-Limit erreicht. Bitte später erneut versuchen.',
    }
    raise TraktError(messages.get(status, 'Trakt ist vorübergehend nicht verfügbar.'))


def json_data(response):
    try:
        return response.json()
    except ValueError:
        raise TraktError('Trakt lieferte eine ungültige Antwort.') from None

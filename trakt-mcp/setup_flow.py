"""Home Assistant configuration + log based device setup, without an extra UI."""
import asyncio
import logging
import re

from errors import TraktError

LOGGER = logging.getLogger('trakt_mcp')


async def authorize_from_home_assistant(auth):
    try:
        codes = await auth.start()
        code = codes['user_code']
        if not isinstance(code, str) or not re.fullmatch(r'[A-Za-z0-9-]{1,32}', code):
            raise TraktError('Ungültiger Aktivierungscode von Trakt.')
        # Only the short-lived, user-facing activation code may be logged.
        # Private device codes and OAuth tokens are never logged.
        LOGGER.warning('Trakt-Anmeldung: https://auth.trakt.tv/activate öffnen und Code %s eingeben. '
                       'Gültig für %s Sekunden.', code, int(codes['expires_in']))
        while True:
            result = await auth.poll()
            if result['status'] == 'authorized':
                LOGGER.warning('Trakt erfolgreich verbunden. authorize_trakt in der Add-on-Konfiguration wieder ausschalten.')
                return
            await asyncio.sleep(result['retry_after_seconds'])
    except TraktError as error:
        LOGGER.error('Trakt-Einrichtung: %s', error)
    except Exception:
        LOGGER.error('Trakt-Einrichtung fehlgeschlagen. Konfiguration und persistenten Speicher prüfen.')

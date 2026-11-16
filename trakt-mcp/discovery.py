"""Bounded, read-only Smart Lists and documented discovery query filters."""
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from errors import TraktError, json_data
from library import LibraryReader, identifier, choice, compact, local_page, object_data
from trakt_client import consistent_account

Values = Annotated[list[Annotated[str, Field(pattern=r"^-?[a-zA-Z0-9][a-zA-Z0-9 ._'-]{0,99}$")]], Field(min_length=1, max_length=20)]
Range = Annotated[str, Field(min_length=2, max_length=32, pattern=r'^\d*(?:\.\d+)?-\d*(?:\.\d+)?$')]


class MediaFilters(BaseModel):
    """Ranges use min-max, e.g. years='2020-', ratings='70-100', runtimes='-120'."""
    model_config = ConfigDict(extra='forbid', strict=True)

    genres: Values | None = None
    subgenres: Values | None = None
    years: Range | None = None
    ratings: Range | None = Field(default=None, description='Trakt percentage range, 0–100; 70-100 means at least 7/10.')
    runtimes: Range | None = Field(default=None, description='Runtime range in minutes.')
    countries: Values | None = None
    statuses: Values | None = None
    certifications: Values | None = None
    parental_nudity: Range | None = None
    parental_violence: Range | None = None
    parental_profanity: Range | None = None
    parental_alcohol: Range | None = None
    parental_frightening: Range | None = None
    parental_include_unrated: bool | None = None

    @field_validator('years', 'ratings', 'runtimes', 'parental_nudity', 'parental_violence',
                     'parental_profanity', 'parental_alcohol', 'parental_frightening',
                     'imdb_ratings', 'tmdb_ratings', 'metascores', 'votes', 'imdb_votes',
                     'award_years', check_fields=False)
    @classmethod
    def validate_range(cls, value, info):
        if value is None:
            return value
        parts = value.split('-')
        numbers = [float(p) for p in parts if p]
        ceiling = (3 if info.field_name.startswith('parental_') else
                   10 if info.field_name in ('imdb_ratings', 'tmdb_ratings') else
                   100 if info.field_name in ('ratings', 'metascores') else
                   9999 if info.field_name in ('years', 'award_years') else 1000000000)
        if (not numbers or any(n > ceiling for n in numbers)
                or (len(numbers) == 2 and numbers[0] > numbers[1])
                or (info.field_name not in ('imdb_ratings', 'tmdb_ratings')
                    and any(not n.is_integer() for n in numbers))):
            raise ValueError('Invalid, reversed or out-of-bounds filter range.')
        return value

    def query(self):
        return {key: ','.join(value) if isinstance(value, list) else
                str(value).lower() if isinstance(value, bool) else value
                for key, value in self.model_dump(exclude_none=True).items()}


class RecommendationFilters(MediaFilters):
    theme: Annotated[str, Field(pattern=r'^[a-z][a-z-]{0,49}$')] | None = Field(
        default=None, description='Seasonal theme, e.g. christmas or halloween; Trakt ignores unknown themes.')
    watch_window: Annotated[int, Field(ge=1, le=36500)] | None = Field(
        default=None, description='Trakt recommendation watch window in days, not streaming availability.')


class SmartListFilters(MediaFilters):
    watchnow: Values | None = Field(default=None, description='favorites, any, free, subscriptions or service slugs; prefix - to exclude. Uses the LIST OWNER, not necessarily you.')
    watchnow_country: Annotated[str, Field(pattern=r'^[a-z]{2}$')] | None = None
    released_within_days: Annotated[int, Field(ge=1, le=3650)] | None = None
    imdb_ratings: Range | None = Field(default=None, description='IMDb rating range, 0–10.')
    tmdb_ratings: Range | None = Field(default=None, description='Rating range supplied by Trakt, 0–10; no direct TMDb request.')
    metascores: Range | None = None
    votes: Range | None = None
    imdb_votes: Range | None = None
    studios: Values | None = None
    people: Values | None = None
    people_operator: Literal['and', 'or'] | None = None
    people_role: Literal['any', 'cast', 'directing', 'writing', 'producing'] | None = None
    awards: Values | None = None
    award_years: Range | None = None
    award_won: bool | None = None
    ignore_watched: bool | None = None
    ignore_watchlisted: bool | None = None

    def query(self):
        if (self.award_years is not None or self.award_won is not None) and not self.awards:
            raise TraktError('awards is required when filtering award years or wins.')
        return super().query()


def recipe(data):
    """Keep documented filter values, never account settings or arbitrary objects."""
    if not isinstance(data, dict):
        raise TraktError('Trakt returned invalid smart list filters.')
    fields = set(SmartListFilters.model_fields) | {
        'genres_operator', 'languages', 'networks', 'keywords', 'keywords_operator',
        'rt_meters', 'rt_user_meters', 'letterboxd_ratings', 'mal_ratings',
        'ignore_watching', 'ignore_unreleased', 'ignore_released', 'ignore_ended',
        'ignore_airing', 'ignore_no_release_date',
    }
    def scalar(value):
        return value is None or type(value) in (bool, int, float) or isinstance(value, str) and len(value) <= 256
    return {key: value for key, value in data.items() if key in fields and
            (scalar(value) or isinstance(value, list) and len(value) <= 100 and all(scalar(v) for v in value))}


class SmartLists:
    def __init__(self, client):
        self.client, self.auth = client, client.auth

    @consistent_account
    async def definition(self, list_id):
        path = '/smart-lists/' + identifier(list_id)
        data = object_data(await self.client.get(path, personal=True))
        result = {key: data[key] for key in ('name', 'privacy', 'created_at', 'updated_at', 'source', 'media_type') if key in data}
        ids = data.get('ids')
        if isinstance(ids, dict):
            result['ids'] = {key: ids[key] for key in ('trakt', 'slug') if key in ids}
        return {**result, 'filters': recipe(data.get('filters', {})), 'source_endpoint': 'trakt:' + path}

    @consistent_account
    async def items(self, list_id, media_type='all', sort_by='rank', sort_how='asc', page=1, limit=50, filters=None):
        choice(media_type, ('all', 'movies', 'shows'))
        choice(sort_by, ('rank', 'title', 'released', 'runtime', 'percentage', 'votes', 'imdb_rating',
                         'imdb_votes', 'tmdb_rating', 'tmdb_votes', 'rt_tomatometer', 'rt_audience', 'metascore', 'added'))
        choice(sort_how, ('asc', 'desc'))
        path = f'/smart-lists/{identifier(list_id)}/items/{media_type}/{sort_by}/{sort_how}'
        result = await LibraryReader(self.client)._page(path, page, limit,
            filters.query() if filters else None, personal=True, projector=compact, require_pagination=True)
        return {**result, 'requested_filters': filters.model_dump(exclude_none=True) if filters else {},
                'note': 'Query filters narrow the saved recipe; they do not replace it. The saved source and streaming region remain authoritative. '
                        'Streaming favorites belong to the list owner, not necessarily you; results are not verified subscriptions or live offer guarantees. '
                        'Recommendation lists may retain rank order regardless of requested sort. Read-only; no list is created or edited.'}

    async def templates(self, page=1, limit=50):
        path = '/smart-lists/templates'
        data = json_data(await self.client.get(path, {'extended': 'full'}))
        if not isinstance(data, list):
            raise TraktError('Trakt returned invalid smart list templates.')
        result = local_page(data, page, limit)
        selected = []
        for item in result['items']:
            if not isinstance(item, dict) or type(item.get('personal')) is not bool:
                raise TraktError('Trakt returned an invalid smart list template.')
            output = {key: item[key] for key in ('id', 'source', 'media_type', 'personal') if key in item}
            preview = item.get('items') or []
            if not isinstance(preview, list):
                raise TraktError('Trakt returned invalid template preview items.')
            selected.append({**output, 'filters': recipe(item.get('filters', {})),
                             'total': None if item['personal'] else item.get('total'),
                             'items': [] if item['personal'] else [compact(v) for v in preview[:3]],
                             'preview_truncated': not item['personal'] and len(preview) > 3})
        return {**result, 'items': selected, 'source': 'trakt:' + path,
                'note': 'Read-only template definitions with at most three preview items each. Personal templates have no results here; null totals are unknown. No lists are created.'}

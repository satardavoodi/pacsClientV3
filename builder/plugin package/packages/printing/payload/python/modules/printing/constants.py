"""Constants for printing/filming module."""

from modules.printing.core.models import FilmLayout, FilmSize

DEFAULT_FILM_SIZES = [
    FilmSize(name="14x17", width_in=14.0, height_in=17.0),
    FilmSize(name="11x14", width_in=11.0, height_in=14.0),
    FilmSize(name="8x10", width_in=8.0, height_in=10.0),
    FilmSize(name="A3", width_in=11.69, height_in=16.54),
    FilmSize(name="A4", width_in=8.27, height_in=11.69),
]

DEFAULT_LAYOUTS = [
    FilmLayout(rows=4, cols=5),
    FilmLayout(rows=4, cols=4),
    FilmLayout(rows=3, cols=4),
    FilmLayout(rows=2, cols=2),
]

from collections import OrderedDict
from pathlib import Path

import numpy as np

from pygfx import Texture, Color

# some funcs adapted from mesmerize


QUALITATIVE_CMAPS = [
    "Pastel1",
    "Pastel2",
    "Paired",
    "Accent",
    "Dark2",
    "Set1",
    "Set2",
    "Set3",
    "tab10",
    "tab20",
    "tab20b",
    "tab20c",
]


def get_cmap(name: str, alpha: float = 1.0) -> np.ndarray:
    """
    Get a colormap as numpy array

    Parameters
    ----------
    name: str
        name of colormap
    alpha: float
        alpha, 0.0 - 1.0

    Returns
    -------
    np.ndarray
        [n_colors, 4], i.e. [n_colors, RGBA]

    """

    cmap_path = Path(__file__).absolute().parent.joinpath("colormaps", name)
    if cmap_path.is_file():
        cmap = np.loadtxt(cmap_path)

    else:
        try:
            from .generate_colormaps import make_cmap

            cmap = make_cmap(name, alpha)
        except (ImportError, ModuleNotFoundError):
            raise ModuleNotFoundError(
                "Couldn't find colormap files, matplotlib is required to generate them "
                "if they aren't found. Please install `matplotlib`"
            )

    cmap[:, -1] = alpha

    return cmap.astype(np.float32)


def make_colors(n_colors: int, cmap: str, alpha: float = 1.0) -> np.ndarray:
    """
    Get colors from a colormap. The returned colors are uniformly spaced, except
    for qualitative colormaps where they are returned subsequently.

    Parameters
    ----------
    n_colors: int
        number of colors to get

    cmap: str
        name of colormap

    alpha: float, default 1.0
        alpha value

    Returns
    -------
    np.ndarray
        shape is [n_colors, 4], where the last dimension is RGBA

    """
    name = cmap
    cmap = get_cmap(name, alpha)

    if name in QUALITATIVE_CMAPS:
        max_colors = cmap.shape[0]
        if n_colors > cmap.shape[0]:
            raise ValueError(
                f"You have requested <{n_colors}> colors but only <{max_colors}> exist for the "
                f"chosen cmap: <{name}>"
            )
        return cmap[:n_colors]

    cm_ixs = np.linspace(0, 255, n_colors, dtype=int)
    return np.take(cmap, cm_ixs, axis=0).astype(np.float32)


def get_cmap_texture(name: str, alpha: float = 1.0) -> Texture:
    cmap = get_cmap(name)
    return Texture(cmap, dim=1)


def make_colors_dict(labels: iter, cmap: str, **kwargs) -> OrderedDict:
    """
    Get a dict for mapping labels onto colors.

    Parameters
    ----------
    labels: Iterable[Any]
        labels for creating a colormap. Order is maintained if it is a list of unique elements.

    cmap: str
        name of colormap

    **kwargs
        passed to make_colors()

    Returns
    -------
    OrderedDict
        keys are labels, values are colors

    Examples
    --------

    .. code-block:: python

        from fastplotlib.utils import get_colors_dict

        labels = ["l1", "l2", "l3"]
        labels_cmap = get_colors_dict(labels, cmap="tab10")

        # illustration of what the `labels_cmap` dict would look like:
        # keep in mind that the tab10 cmap was chosen here

        {
            "l1": <RGBA array for the blue 'tab10' color>,
            "l2": <RGBA array for the orange 'tab10' color>,
            "l3": <RGBA array for the green 'tab10' color>,
        }

        # another example with a non-qualitative cmap
        labels_cmap_seismic = get_colors_dict(labels, cmap="bwr")

        {
            "l1": <RGBA array for the blue 'bwr' color>,
            "l2": <RGBA array for the white 'bwr' color>,
            "l3": <RGBA array for the red 'bwr' color>,
        }

    """
    if not len(set(labels)) == len(labels):
        labels = list(set(labels))
    else:
        labels = list(labels)

    colors = make_colors(len(labels), cmap, **kwargs)

    return OrderedDict(zip(labels, colors))


def quick_min_max(data: np.ndarray) -> tuple[float, float]:
    """
    Adapted from pyqtgraph.ImageView.
    Estimate the min/max values of *data* by subsampling.

    Parameters
    ----------
    data: np.ndarray or array-like with `min` and `max` attributes

    Returns
    -------
    (float, float)
        (min, max)
    """

    if hasattr(data, "min") and hasattr(data, "max"):
        # if value is pre-computed
        if isinstance(data.min, (float, int, np.number)) and isinstance(
            data.max, (float, int, np.number)
        ):
            return data.min, data.max

    while data.size > 1e6:
        ax = np.argmax(data.shape)
        sl = [slice(None)] * data.ndim
        sl[ax] = slice(None, None, 2)
        data = data[tuple(sl)]

    return float(np.nanmin(data)), float(np.nanmax(data))


def make_pygfx_colors(colors, n_colors):
    """
    Parse and make colors array using pyfx.Color

    Parameters
    ----------
    colors: str, list, tuple, or np.ndarray
        pygfx parseable color

    n_colors: int
        number of repeats of the color

    Returns
    -------
    np.ndarray
        shape is [n_colors, 4], i.e. [n_colors, RGBA]
    """

    c = Color(colors)
    colors_array = np.repeat(np.array([c]), n_colors, axis=0)

    return colors_array


def calculate_figure_shape(n_subplots: int) -> tuple[int, int]:
    """
    Returns ``(n_rows, n_cols)`` from given number of subplots ``n_subplots``
    """
    sr = np.sqrt(n_subplots)

    return (int(np.round(sr)), int(np.ceil(sr)))


def normalize_min_max(a):
    """normalize an array between 0 - 1"""
    if np.unique(a).size == 1:
        return np.zeros(a.size)

    return (a - np.min(a)) / (np.max(a - np.min(a)))


def parse_cmap_values(
    n_colors: int,
    cmap_name: str,
    transform: np.ndarray | list[int | float] = None,
) -> np.ndarray:
    """

    Parameters
    ----------
    n_colors: int
        number of graphics in collection

    cmap_name: str
        colormap name

    transform: np.ndarray | List[int | float], optional
        cmap transform
    Returns
    -------

    """
    if transform is None:
        colors = make_colors(n_colors, cmap_name)
        return colors

    else:
        if not isinstance(transform, np.ndarray):
            transform = np.array(transform)

        # use the of the cmap_transform to set the color of the corresponding data
        # each individual data[i] has its color based on the transform values
        if len(transform) != n_colors:
            raise ValueError(
                f"len(cmap_values) != len(data): {len(transform)} != {n_colors}"
            )

        colormap = get_cmap(cmap_name)

        n_colors = colormap.shape[0] - 1

        if cmap_name in QUALITATIVE_CMAPS:
            # check that cmap_transform are <int> and within the number of colors `n_colors`
            # do not scale, use directly
            if not np.issubdtype(transform.dtype, np.integer):
                raise TypeError(
                    f"<int> `cmap_transform` values should be used with qualitative colormaps, "
                    f"the dtype you have passed is {transform.dtype}"
                )
            if max(transform) > n_colors:
                raise IndexError(
                    f"You have chosen the qualitative colormap <'{cmap_name}'> which only has "
                    f"<{n_colors}> colors, which is lower than the max value of your `cmap_transform`."
                    f"Choose a cmap with more colors, or a non-quantitative colormap."
                )
            norm_cmap_values = transform
        else:
            # scale between 0 - n_colors so we can just index the colormap as a LUT
            norm_cmap_values = (normalize_min_max(transform) * n_colors).astype(int)

        # use colormap as LUT to map the cmap_values to the colormap index
        colors = np.vstack([colormap[val] for val in norm_cmap_values])

        return colors

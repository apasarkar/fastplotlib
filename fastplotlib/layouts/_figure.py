import os
from itertools import product, chain
from multiprocessing import Queue
from pathlib import Path
from time import time

import numpy as np
from typing import Literal, Iterable
from inspect import getfullargspec
from warnings import warn

import pygfx

from rendercanvas import BaseRenderCanvas

from ._video_writer import VideoWriterAV
from ._utils import make_canvas_and_renderer, create_controller, create_camera
from ._utils import controller_types as valid_controller_types
from ._subplot import Subplot
from .. import ImageGraphic


class Figure:
    def __init__(
        self,
        shape: tuple[int, int] = (1, 1),
        cameras: (
            Literal["2d", "3d"]
            | Iterable[Iterable[Literal["2d", "3d"]]]
            | pygfx.PerspectiveCamera
            | Iterable[Iterable[pygfx.PerspectiveCamera]]
        ) = "2d",
        controller_types: (
            Iterable[Iterable[Literal["panzoom", "fly", "trackball", "orbit"]]]
            | Iterable[Literal["panzoom", "fly", "trackball", "orbit"]]
        ) = None,
        controller_ids: (
            Literal["sync"]
            | Iterable[int]
            | Iterable[Iterable[int]]
            | Iterable[Iterable[str]]
        ) = None,
        controllers: pygfx.Controller | Iterable[Iterable[pygfx.Controller]] = None,
        canvas: str | BaseRenderCanvas | pygfx.Texture = None,
        renderer: pygfx.WgpuRenderer = None,
        size: tuple[int, int] = (500, 300),
        names: list | np.ndarray = None,
    ):
        """
        A grid of subplots.

        Parameters
        ----------
        shape: (int, int), default (1, 1)
            (n_rows, n_cols)

        cameras: "2d", "3", list of "2d" | "3d", Iterable of camera instances, or Iterable of "2d" | "3d", optional
            | if str, one of ``"2d"`` or ``"3d"`` indicating 2D or 3D cameras for all subplots
            | Iterable/list/array of ``2d`` and/or ``3d`` that specifies the camera type for each subplot
            | Iterable/list/array of pygfx.PerspectiveCamera instances

        controller_types: str, Iterable, optional
            list/array that specifies the controller type for each subplot.
            Valid controller types: "panzoom", "fly", "trackball", "orbit".
            If not specified a default controller is chosen based on the camera type.
            Orthographic projections, i.e. "2d" cameras, use a "panzoom" controller by default.
            Perspective projections with a FOV > 0, i.e. "3d" cameras, use a "fly" controller by default.

        controller_ids: str, list of int, np.ndarray of int, or list with sublists of subplot str names, optional
            | If `None` a unique controller is created for each subplot
            | If "sync" all the subplots use the same controller
            | If array/list it must be reshapeable to ``grid_shape``.

            This allows custom assignment of controllers

            | Example with integers:
            | sync first 2 plots, and sync last 2 plots: [[0, 0, 1], [2, 3, 3]]
            | Example with str subplot names:
            | list of lists of subplot names, each sublist is synced: [[subplot_a, subplot_b, subplot_e], [subplot_c, subplot_d]]
            | this syncs subplot_a, subplot_b and subplot_e together; syncs subplot_c and subplot_d together

        controllers: pygfx.Controller | list[pygfx.Controller] | np.ndarray[pygfx.Controller], optional
            directly provide pygfx.Controller instances(s). Useful if you want to use a controller from an existing
            plot/subplot. Other controller kwargs, i.e. ``controller_types`` and ``controller_ids`` are ignored if
            ``controllers`` are provided.

        canvas: str, BaseRenderCanvas, pygfx.Texture
            Canvas to draw the figure onto, usually auto-selected based on running environment.

        renderer: pygfx.Renderer, optional
            pygfx renderer instance

        size: (int, int), optional
            starting size of canvas, default (500, 300)

        names: list or array of str, optional
            subplot names
        """

        self._shape = shape

        if names is not None:
            if len(list(chain(*names))) != len(self):
                raise ValueError(
                    "must provide same number of subplot `names` as specified by Figure `shape`"
                )

            subplot_names = np.asarray(names).reshape(self.shape)
        else:
            subplot_names = None

        canvas, renderer = make_canvas_and_renderer(
            canvas, renderer, canvas_kwargs={"size": size}
        )

        if isinstance(cameras, str):
            # create the array representing the views for each subplot in the grid
            cameras = np.array([cameras] * len(self)).reshape(self.shape)

        # list -> array if necessary
        cameras = np.asarray(cameras).reshape(self.shape)

        if cameras.shape != self.shape:
            raise ValueError("Number of cameras does not match the number of subplots")

        # create the cameras
        subplot_cameras = np.empty(self.shape, dtype=object)
        for i, j in product(range(self.shape[0]), range(self.shape[1])):
            subplot_cameras[i, j] = create_camera(camera_type=cameras[i, j])

        # if controller instances have been specified for each subplot
        if controllers is not None:

            # one controller for all subplots
            if isinstance(controllers, pygfx.Controller):
                controllers = [controllers] * len(self)
                # subplot_controllers[:] = controllers
                # # subplot_controllers = np.asarray([controllers] * len(self), dtype=object)

            # individual controller instance specified for each subplot
            else:
                # I found that this is better than list(*chain(<list/array>)) because chain doesn't give the right
                # result we want for arrays
                for item in controllers:
                    if isinstance(item, pygfx.Controller):
                        pass
                    elif all(isinstance(c, pygfx.Controller) for c in item):
                        pass
                    else:
                        raise TypeError(
                            "controllers argument must be a single pygfx.Controller instance, or a Iterable of "
                            "pygfx.Controller instances"
                        )

            try:
                controllers = np.asarray(controllers).reshape(shape)
            except ValueError:
                raise ValueError(
                    f"number of controllers passed must be the same as the number of subplots specified "
                    f"by shape: {self.shape}. You have passed: <{controllers.size}> controllers"
                ) from None

            subplot_controllers: np.ndarray[pygfx.Controller] = np.empty(
                self.shape, dtype=object
            )

            for i, j in product(range(self.shape[0]), range(self.shape[1])):
                subplot_controllers[i, j] = controllers[i, j]
                subplot_controllers[i, j].add_camera(subplot_cameras[i, j])

        # parse controller_ids and controller_types to make desired controller for each supblot
        else:
            if controller_ids is None:
                # individual controller for each subplot
                controller_ids = np.arange(len(self)).reshape(self.shape)

            elif isinstance(controller_ids, str):
                if controller_ids == "sync":
                    # this will eventually make one controller for all subplots
                    controller_ids = np.zeros(self.shape, dtype=int)
                else:
                    raise ValueError(
                        f"`controller_ids` must be one of 'sync', an array/list of subplot names, or an array/list of "
                        f"integer ids. See the docstring for more details."
                    )

            # list controller_ids
            elif isinstance(controller_ids, (list, np.ndarray)):
                ids_flat = list(chain(*controller_ids))

                # list of str of subplot names, convert this to integer ids
                if all([isinstance(item, str) for item in ids_flat]):
                    if subplot_names is None:
                        raise ValueError(
                            "must specify subplot `names` to use list of str for `controller_ids`"
                        )

                    # make sure each controller_id str is a subplot name
                    if not all([n in subplot_names for n in ids_flat]):
                        raise KeyError(
                            f"all `controller_ids` strings must be one of the subplot names"
                        )

                    if len(ids_flat) > len(set(ids_flat)):
                        raise ValueError(
                            "id strings must not appear twice in `controller_ids`"
                        )

                    # initialize controller_ids array
                    ids_init = np.arange(len(self)).reshape(self.shape)

                    # set id based on subplot position for each synced sublist
                    for i, sublist in enumerate(controller_ids):
                        for name in sublist:
                            ids_init[subplot_names == name] = -(
                                i + 1
                            )  # use negative numbers because why not

                    controller_ids = ids_init

                # integer ids
                elif all([isinstance(item, (int, np.integer)) for item in ids_flat]):
                    controller_ids = np.asarray(controller_ids).reshape(self.shape)

                else:
                    raise TypeError(
                        f"list argument to `controller_ids` must be a list of `str` or `int`, "
                        f"you have passed: {controller_ids}"
                    )

            if controller_ids.shape != self.shape:
                raise ValueError(
                    "Number of controller_ids does not match the number of subplots"
                )

            if controller_types is None:
                # `create_controller()` will auto-determine controller for each subplot based on defaults
                controller_types = np.array(["default"] * len(self)).reshape(self.shape)

            # valid controller types
            if isinstance(controller_types, str):
                controller_types = [[controller_types]]

            types_flat = list(chain(*controller_types))
            # str controller_type or pygfx instances
            valid_str = list(valid_controller_types.keys()) + ["default"]

            # make sure each controller type is valid
            for controller_type in types_flat:
                if controller_type is None:
                    continue

                if controller_type not in valid_str:
                    raise ValueError(
                        f"You have passed the invalid `controller_type`: {controller_type}. "
                        f"Valid `controller_types` arguments are:\n {valid_str}"
                    )

            controller_types: np.ndarray[pygfx.Controller] = np.asarray(
                controller_types
            ).reshape(self.shape)

            # make the real controllers for each subplot
            subplot_controllers = np.empty(shape=self.shape, dtype=object)
            for cid in np.unique(controller_ids):
                cont_type = controller_types[controller_ids == cid]
                if np.unique(cont_type).size > 1:
                    raise ValueError(
                        "Multiple controller types have been assigned to the same controller id. "
                        "All controllers with the same id must use the same type of controller."
                    )

                cont_type = cont_type[0]

                # get all the cameras that use this controller
                cams = subplot_cameras[controller_ids == cid].ravel()

                if cont_type == "default":
                    # hacky fix for now because of how `create_controller()` works
                    cont_type = None
                _controller = create_controller(
                    controller_type=cont_type, camera=cams[0]
                )

                subplot_controllers[controller_ids == cid] = _controller

                # add the other cameras that go with this controller
                if cams.size > 1:
                    for cam in cams[1:]:
                        _controller.add_camera(cam)

        self._canvas = canvas
        self._renderer = renderer

        nrows, ncols = self.shape

        self._subplots: np.ndarray[Subplot] = np.ndarray(
            shape=(nrows, ncols), dtype=object
        )

        for i, j in self._get_iterator():
            position = (i, j)
            camera = subplot_cameras[i, j]
            controller = subplot_controllers[i, j]

            if subplot_names is not None:
                name = subplot_names[i, j]
            else:
                name = None

            self._subplots[i, j] = Subplot(
                parent=self,
                position=position,
                parent_dims=(nrows, ncols),
                camera=camera,
                controller=controller,
                canvas=canvas,
                renderer=renderer,
                name=name,
            )

        self._animate_funcs_pre: list[callable] = list()
        self._animate_funcs_post: list[callable] = list()

        self._current_iter = None

        self._sidecar = None

        self._output = None

    @property
    def shape(self) -> tuple[int, int]:
        """[n_rows, n_cols]"""
        return self._shape

    @property
    def canvas(self) -> BaseRenderCanvas:
        """The canvas this Figure is drawn onto"""
        return self._canvas

    @property
    def renderer(self) -> pygfx.WgpuRenderer:
        """The renderer that renders this Figure"""
        return self._renderer

    @property
    def controllers(self) -> np.ndarray[pygfx.Controller]:
        """controllers, read-only array, access individual subplots to change a controller"""
        controllers = np.asarray(
            [subplot.controller for subplot in self], dtype=object
        ).reshape(self.shape)
        controllers.flags.writeable = False
        return controllers

    @property
    def cameras(self) -> np.ndarray[pygfx.Camera]:
        """cameras, read-only array, access individual subplots to change a camera"""
        cameras = np.asarray(
            [subplot.camera for subplot in self], dtype=object
        ).reshape(self.shape)
        cameras.flags.writeable = False
        return cameras

    @property
    def names(self) -> np.ndarray[str]:
        """subplot names, read-only array, access individual subplots to change a name"""
        names = np.asarray([subplot.name for subplot in self]).reshape(self.shape)
        names.flags.writeable = False
        return names

    def __getitem__(self, index: tuple[int, int] | str) -> Subplot:
        if isinstance(index, str):
            for subplot in self._subplots.ravel():
                if subplot.name == index:
                    return subplot
            raise IndexError(f"no subplot with given name: {index}")
        else:
            return self._subplots[index[0], index[1]]

    def render(self, draw=True):
        # call the animation functions before render
        self._call_animate_functions(self._animate_funcs_pre)

        for subplot in self:
            subplot.render()

        self.renderer.flush()
        if draw:
            self.canvas.request_draw()

        # call post-render animate functions
        self._call_animate_functions(self._animate_funcs_post)

    def start_render(self):
        """start render cycle"""
        self.canvas.request_draw(self.render)

    def show(
        self,
        autoscale: bool = True,
        maintain_aspect: bool = None,
        sidecar: bool = False,
        sidecar_kwargs: dict = None,
    ):
        """
        Begins the rendering event loop and shows the Figure, returns the canvas

        Parameters
        ----------
        autoscale: bool, default ``True``
            autoscale the Scene

        maintain_aspect: bool, default ``True``
            maintain aspect ratio

        sidecar: bool, default ``True``
            display plot in a ``jupyterlab-sidecar``, only in jupyter

        sidecar_kwargs: dict, default ``None``
            kwargs for sidecar instance to display plot
            i.e. title, layout

        Returns
        -------
        BaseRenderCanvas
            In Qt or GLFW, the canvas window containing the Figure will be shown.
            In jupyter, it will display the plot in the output cell or sidecar.
        """

        # show was already called, return canvas
        if self._output:
            return self._output

        self.start_render()

        if sidecar_kwargs is None:
            sidecar_kwargs = dict()

        # flip y-axis if ImageGraphics are present
        for subplot in self:
            for g in subplot.graphics:
                if isinstance(g, ImageGraphic):
                    subplot.camera.local.scale_y *= -1
                    break

        if autoscale:
            for subplot in self:
                if maintain_aspect is None:
                    _maintain_aspect = subplot.camera.maintain_aspect
                else:
                    _maintain_aspect = maintain_aspect
                subplot.auto_scale(maintain_aspect=maintain_aspect)

        # parse based on canvas type
        if self.canvas.__class__.__name__ == "JupyterRenderCanvas":
            if sidecar:
                from sidecar import Sidecar
                from IPython.display import display

                self._sidecar = Sidecar(**sidecar_kwargs)
                self._output = self.canvas
                with self._sidecar:
                    return display(self.canvas)
            self._output = self.canvas
            return self._output

        elif self.canvas.__class__.__name__ == "QRenderCanvas":
            self._output = self.canvas
            self._output.show()
            return self.canvas

        elif self.canvas.__class__.__name__ == "OffscreenRenderCanvas":
            # for test and docs gallery screenshots
            for subplot in self:
                subplot.set_viewport_rect()
                subplot.axes.update_using_camera()

                # render call is blocking only on github actions for some reason,
                # but not for rtd build, this is a workaround
                # for CI tests, the render call works if it's in test_examples
                # but it is necessary for the gallery images too so that's why this check is here
                if "RTD_BUILD" in os.environ.keys():
                    if os.environ["RTD_BUILD"] == "1":
                        self.render()

        else:  # assume GLFW
            self._output = self.canvas

        # return the canvas
        return self._output

    def close(self):
        self._output.close()
        if self._sidecar:
            self._sidecar.close()

    def _call_animate_functions(self, funcs: list[callable]):
        for fn in funcs:
            try:
                if len(getfullargspec(fn).args) > 0:
                    fn(self)
                else:
                    fn()
            except (ValueError, TypeError):
                warn(
                    f"Could not resolve argspec of {self.__class__.__name__} animation function: {fn}, "
                    f"calling it without arguments."
                )
                fn()

    def add_animations(
        self,
        *funcs: callable,
        pre_render: bool = True,
        post_render: bool = False,
    ):
        """
        Add function(s) that are called on every render cycle.
        These are called at the Figure level.

        Parameters
        ----------
        *funcs: callable(s)
            function(s) that are called on each render cycle

        pre_render: bool, default ``True``, optional keyword-only argument
            if true, these function(s) are called before a render cycle

        post_render: bool, default ``False``, optional keyword-only argument
            if true, these function(s) are called after a render cycle

        """
        for f in funcs:
            if not callable(f):
                raise TypeError(
                    f"all positional arguments to add_animations() must be callable types, you have passed a: {type(f)}"
                )
            if pre_render:
                self._animate_funcs_pre += funcs
            if post_render:
                self._animate_funcs_post += funcs

    def remove_animation(self, func):
        """
        Removes the passed animation function from both pre and post render.

        Parameters
        ----------
        func: callable
            The function to remove, raises a error if it's not registered as a pre or post animation function.

        """
        if func not in self._animate_funcs_pre and func not in self._animate_funcs_post:
            raise KeyError(
                f"The passed function: {func} is not registered as an animation function. These are the animation "
                f" functions that are currently registered:\n"
                f"pre: {self._animate_funcs_pre}\n\npost: {self._animate_funcs_post}"
            )

        if func in self._animate_funcs_pre:
            self._animate_funcs_pre.remove(func)

        if func in self._animate_funcs_post:
            self._animate_funcs_post.remove(func)

    def clear(self):
        """Clear all Subplots"""
        for subplot in self:
            subplot.clear()

    def export_numpy(self, rgb: bool = False) -> np.ndarray:
        """
        Export a snapshot of the Figure as numpy array.

        Parameters
        ----------
        rgb: bool, default ``False``
            if True, use alpha blending to return an RGB image.
            if False, returns an RGBA array

        Returns
        -------
        np.ndarray
            [n_rows, n_cols, 3] for RGB or [n_rows, n_cols, 4] for RGBA
        """
        snapshot = self.renderer.snapshot()

        if rgb:
            bg = np.zeros(snapshot.shape).astype(np.uint8)
            bg[:, :, -1] = 255

            img_alpha = snapshot[..., -1] / 255

            rgb = snapshot[..., :-1] * img_alpha[..., None] + bg[..., :-1] * np.ones(
                img_alpha.shape
            )[..., None] * (1 - img_alpha[..., None])

            return rgb.astype(np.uint8)

        return snapshot

    def export(self, uri: str | Path | bytes, **kwargs):
        """
        Use ``imageio`` for writing the current Figure to a file, or return a byte string.
        Must have ``imageio`` installed.

        Parameters
        ----------
        uri: str | Path | bytes

        kwargs: passed to imageio.v3.imwrite, see: https://imageio.readthedocs.io/en/stable/_autosummary/imageio.v3.imwrite.html

        Returns
        -------
        None | bytes
            see https://imageio.readthedocs.io/en/stable/_autosummary/imageio.v3.imwrite.html
        """
        try:
            import imageio.v3 as iio
        except ModuleNotFoundError:
            raise ImportError(
                "imageio is required to use Figure.export(). Install it using pip or conda:\n"
                "pip install imageio\n"
                "conda install -c conda-forge imageio\n"
            )
        else:
            # image formats that support alpha channel:
            # https://en.wikipedia.org/wiki/Alpha_compositing#Image_formats_supporting_alpha_channels
            alpha_support = [".png", ".exr", ".tiff", ".tif", ".gif", ".jxl", ".svg"]

            uri = Path(uri)

            if uri.suffix in alpha_support:
                rgb = False
            else:
                rgb = True

            snapshot = self.export_numpy(rgb=rgb)

            return iio.imwrite(uri, snapshot, **kwargs)

    def open_popup(self, *args, **kwargs):
        warn("popups only supported by ImguiFigure")

    def get_pygfx_render_area(self, *args) -> tuple[int, int, int, int]:
        """
        Fet rect for the portion of the canvas that the pygfx renderer draws to,
        i.e. non-imgui, part of canvas

        Returns
        -------
        tuple[int, int, int, int]
            x_pos, y_pos, width, height

        """

        width, height = self.canvas.get_logical_size()

        return 0, 0, width, height

    def _get_iterator(self):
        return product(range(self.shape[0]), range(self.shape[1]))

    def __iter__(self):
        self._current_iter = self._get_iterator()
        return self

    def __next__(self) -> Subplot:
        pos = self._current_iter.__next__()
        return self._subplots[pos]

    def __len__(self):
        """number of subplots"""
        return self.shape[0] * self.shape[1]

    def __str__(self):
        return f"{self.__class__.__name__} @ {hex(id(self))}"

    def __repr__(self):
        newline = "\n\t"

        return (
            f"fastplotlib.{self.__class__.__name__} @ {hex(id(self))}\n"
            f"  Subplots:\n"
            f"\t{newline.join(subplot.__str__() for subplot in self)}"
            f"\n"
        )

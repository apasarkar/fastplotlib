import importlib

import pygfx
from pygfx import WgpuRenderer, Texture, Renderer

from ..utils.gui import BaseRenderCanvas, RenderCanvas


def make_canvas_and_renderer(
    canvas: str | BaseRenderCanvas | Texture | None,
    renderer: Renderer | None,
    canvas_kwargs: dict,
):
    """
    Parses arguments and returns the appropriate canvas and renderer instances
    as a tuple (canvas, renderer)
    """

    if canvas is None:
        canvas = RenderCanvas(max_fps=60, **canvas_kwargs)
    elif isinstance(canvas, str):
        import rendercanvas

        m = importlib.import_module("rendercanvas." + canvas)
        canvas = m.RenderCanvas(max_fps=60, **canvas_kwargs)
    elif not isinstance(canvas, (BaseRenderCanvas, Texture)):
        raise TypeError(
            f"canvas option must either be a valid BaseRenderCanvas implementation, a pygfx Texture"
            f" or a str with the gui backend name, valid str are: 'qt', 'glfw', 'jupyter', 'wx', and 'offscreen'"
        )

    if renderer is None:
        renderer = WgpuRenderer(canvas)
    elif not isinstance(renderer, Renderer):
        raise TypeError(
            f"renderer option must be a pygfx.Renderer instance such as pygfx.WgpuRenderer"
        )

    return canvas, renderer


def create_camera(
    camera_type: pygfx.PerspectiveCamera | str,
) -> pygfx.PerspectiveCamera:
    if isinstance(camera_type, pygfx.PerspectiveCamera):
        return camera_type

    elif camera_type == "2d":
        # use perspective for orthographic, makes it easier to then switch to controllers that make sense with fov > 0
        return pygfx.PerspectiveCamera(fov=0)

    elif camera_type == "3d":
        return pygfx.PerspectiveCamera()

    else:
        raise ValueError(
            "camera must be one of: '2d', '3d' or an instance of pygfx.PerspectiveCamera"
        )


controller_types = {
    "fly": pygfx.FlyController,
    "panzoom": pygfx.PanZoomController,
    "trackball": pygfx.TrackballController,
    "orbit": pygfx.OrbitController,
}


def create_controller(
    controller_type: pygfx.Controller | None | str,
    camera: pygfx.PerspectiveCamera,
) -> pygfx.Controller:
    """
    Creates the controllers and adds the camera to it.
    """
    if isinstance(controller_type, pygfx.Controller):
        controller_type.add_camera(camera)
        return controller_type

    if controller_type is None:
        # default controllers
        if camera.fov == 0:
            # default for orthographic
            return pygfx.PanZoomController(camera)
        else:
            return pygfx.FlyController(camera)

    if controller_type not in controller_types.keys():
        raise KeyError(
            f"controller must be a valid pygfx.Controller or one of: "
            f"{list(controller_types.keys())}, you have passed: {controller_type}"
        )

    return controller_types[controller_type](camera)

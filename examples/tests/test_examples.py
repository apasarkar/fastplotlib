"""
Test that examples run without error.
"""

import sys
import importlib
import runpy
import pytest
import os
import numpy as np
import imageio.v3 as iio
import pygfx
import fastplotlib as fpl

MAX_TEXTURE_SIZE = 2048
pygfx.renderers.wgpu.set_wgpu_limits(**{"max-texture-dimension-2d": MAX_TEXTURE_SIZE})

from .testutils import (
    ROOT,
    examples_dir,
    screenshots_dir,
    find_examples,
    wgpu_backend,
    is_lavapipe,
    diffs_dir,
    generate_diff,
    image_similarity,
    normalize_image,
    prep_for_write,
)

# run all tests unless they opt-out
examples_to_run = find_examples(negative_query="# run_example = false")

# only test output of examples that opt-in
examples_to_test = find_examples(query="# test_example = true")


def check_skip_imgui(module):
    # skip any imgui or ImageWidget tests
    with open(module, "r") as f:
        contents = f.read()
        if "ImageWidget" in contents:
            pytest.skip("skipping ImageWidget tests since they require imgui")
        elif "imgui" in contents or "imgui_bundle" in contents:
            pytest.skip("skipping tests that require imgui")


@pytest.mark.parametrize("module", examples_to_run, ids=lambda x: x.stem)
def test_examples_run(module, force_offscreen):
    """Run every example marked to see if they run without error."""
    if not fpl.IMGUI:
        check_skip_imgui(module)

    runpy.run_path(module, run_name="__main__")


@pytest.fixture
def force_offscreen():
    """Force the offscreen canvas to be selected by the auto gui module."""
    os.environ["RENDERCANVAS_FORCE_OFFSCREEN"] = "true"
    try:
        yield
    finally:
        del os.environ["RENDERCANVAS_FORCE_OFFSCREEN"]


def test_that_we_are_on_lavapipe():
    print(wgpu_backend)
    if os.getenv("PYGFX_EXPECT_LAVAPIPE"):
        assert is_lavapipe


def import_from_path(module_name, filename):
    spec = importlib.util.spec_from_file_location(module_name, filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    # With this approach the module is not added to sys.modules, which
    # is great, because that way the gc can simply clean up when we lose
    # the reference to the module
    assert module.__name__ == module_name
    assert module_name not in sys.modules

    return module


@pytest.mark.parametrize("module", examples_to_test, ids=lambda x: x.stem)
def test_example_screenshots(module, force_offscreen):
    """Make sure that every example marked outputs the expected."""

    if not fpl.IMGUI:
        # skip any imgui or ImageWidget tests
        check_skip_imgui(module)

    # import the example module
    example = import_from_path(module.stem, module)

    if fpl.IMGUI:
        # there doesn't seem to be a resize event for the manual offscreen canvas
        example.figure.imgui_renderer._backend.io.display_size = example.figure.canvas.get_logical_size()
        # run this once so any edge widgets set their sizes and therefore the subplots get the correct rect
        # hacky but it works for now
        example.figure.imgui_renderer.render()

    example.figure._fpl_reset_layout()
    # render each subplot
    for subplot in example.figure:
        subplot.viewport.render(subplot.scene, subplot.camera)

    # flush pygfx renderer
    example.figure.renderer.flush()

    if fpl.IMGUI:
        # render imgui
        example.figure.imgui_renderer.render()

    # render a frame
    img = np.asarray(example.figure.renderer.target.draw())

    # check if _something_ was rendered
    assert img is not None and img.size > 0

    # if screenshots dir does not exist, will create
    if not os.path.exists(screenshots_dir):
        os.mkdir(screenshots_dir)

    # test screenshots for both imgui and non-gui installs
    if not fpl.IMGUI:
        prefix = "no-imgui-"
    else:
        prefix = ""

    screenshot_path = screenshots_dir / f"{prefix}{module.stem}.png"

    black = np.zeros(img.shape).astype(np.uint8)
    black[:, :, -1] = 255

    img_alpha = img[..., -1] / 255

    rgb = img[..., :-1] * img_alpha[..., None] + black[..., :-1] * np.ones(
        img_alpha.shape
    )[..., None] * (1 - img_alpha[..., None])

    rgb = rgb.round().astype(np.uint8)

    if "REGENERATE_SCREENSHOTS" in os.environ.keys():
        if os.environ["REGENERATE_SCREENSHOTS"] == "1":
            iio.imwrite(screenshot_path, rgb)

    assert (
        screenshot_path.exists()
    ), "found # test_example = true but no reference screenshot available"

    ref_img = iio.imread(screenshot_path)

    rgb = normalize_image(rgb)
    ref_img = normalize_image(ref_img)

    similar, rmse = image_similarity(rgb, ref_img, threshold=0.05)

    update_diffs(module.stem, similar, rgb, ref_img)
    assert similar, (
        f"diff {rmse} above threshold for {module.stem}, see "
        f"the {diffs_dir.relative_to(ROOT).as_posix()} folder"
        " for visual diffs (you can download this folder from"
        " CI build artifacts as well)"
    )


def update_diffs(module, is_similar, img, stored_img):
    diffs_dir.mkdir(exist_ok=True)

    diffs_rgba = None

    def get_diffs_rgba(slicer):
        # lazily get and cache the diff computation
        nonlocal diffs_rgba
        if diffs_rgba is None:
            # cast to float32 to avoid overflow
            # compute absolute per-pixel difference
            diffs_rgba = np.abs(stored_img.astype("f4") - img)
            # magnify small values, making it easier to spot small errors
            diffs_rgba = ((diffs_rgba / 255) ** 0.25) * 255
            # cast back to uint8
            diffs_rgba = diffs_rgba.astype("u1")
        return diffs_rgba[..., slicer]

    # split into an rgb and an alpha diff
    diffs = {
        diffs_dir / f"diff-{module}-rgb.png": slice(0, 3),
    }

    for path, slicer in diffs.items():
        if not is_similar:
            diff = get_diffs_rgba(slicer)
            iio.imwrite(path, diff)
        elif path.exists():
            path.unlink()


if __name__ == "__main__":
    test_examples_run("simple")
    test_example_screenshots("simple")

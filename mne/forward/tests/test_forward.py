# License: BSD-3-Clause
# Copyright the MNE-Python contributors.
import gc
from pathlib import Path

import numpy as np
import pytest
from numpy.testing import (
    assert_allclose,
    assert_array_almost_equal,
    assert_array_equal,
    assert_equal,
)

from mne import (
    SourceEstimate,
    VectorSourceEstimate,
    apply_forward,
    apply_forward_raw,
    average_forward_solutions,
    convert_forward_solution,
    pick_types_forward,
    read_evokeds,
    read_forward_solution,
    write_forward_solution,
)
from mne._fiff.pick import pick_channels_forward
from mne.channels import equalize_channels
from mne.datasets import testing
from mne.forward import (
    Forward,
    compute_depth_prior,
    compute_orient_prior,
    is_fixed_orient,
    restrict_forward_to_label,
    restrict_forward_to_stc,
)
from mne.io import read_info
from mne.label import read_label
from mne.utils import requires_mne, run_subprocess

data_path = testing.data_path(download=False)
fname_meeg = data_path / "MEG" / "sample" / "sample_audvis_trunc-meg-eeg-oct-4-fwd.fif"
fname_meeg_grad = (
    data_path / "MEG" / "sample" / "sample_audvis_trunc-meg-eeg-oct-2-grad-fwd.fif"
)
fname_evoked = Path(__file__).parents[2] / "io" / "tests" / "data" / "test-ave.fif"
label_path = data_path / "MEG" / "sample" / "labels"


def assert_forward_allclose(f1, f2, rtol=1e-7):
    """Compare two potentially converted forward solutions."""
    assert_allclose(f1["sol"]["data"], f2["sol"]["data"], rtol=rtol)
    assert f1["sol"]["ncol"] == f2["sol"]["ncol"]
    assert f1["sol"]["ncol"] == f1["sol"]["data"].shape[1]
    assert_allclose(f1["source_nn"], f2["source_nn"], rtol=rtol)
    if f1["sol_grad"] is not None:
        assert f2["sol_grad"] is not None
        assert_allclose(f1["sol_grad"]["data"], f2["sol_grad"]["data"])
        assert f1["sol_grad"]["ncol"] == f2["sol_grad"]["ncol"]
        assert f1["sol_grad"]["ncol"] == f1["sol_grad"]["data"].shape[1]
    else:
        assert f2["sol_grad"] is None
    assert f1["source_ori"] == f2["source_ori"]
    assert f1["surf_ori"] == f2["surf_ori"]
    assert f1["src"][0]["coord_frame"] == f1["src"][0]["coord_frame"]


@testing.requires_testing_data
def test_convert_forward():
    """Test converting forward solution between different representations."""
    fwd = read_forward_solution(fname_meeg_grad)
    fwd_repr = repr(fwd)
    assert "306" in fwd_repr
    assert "60" in fwd_repr
    assert fwd_repr
    assert isinstance(fwd, Forward)
    # look at surface orientation
    fwd_surf = convert_forward_solution(fwd, surf_ori=True)
    # go back
    fwd_new = convert_forward_solution(fwd_surf, surf_ori=False)
    assert repr(fwd_new)
    assert isinstance(fwd_new, Forward)
    assert_forward_allclose(fwd, fwd_new)
    del fwd_new
    gc.collect()

    # now go to fixed
    fwd_fixed = convert_forward_solution(
        fwd_surf, surf_ori=True, force_fixed=True, use_cps=False
    )
    del fwd_surf
    gc.collect()
    assert repr(fwd_fixed)
    assert isinstance(fwd_fixed, Forward)
    assert is_fixed_orient(fwd_fixed)
    # now go back to cartesian (original condition)
    fwd_new = convert_forward_solution(fwd_fixed, surf_ori=False, force_fixed=False)
    assert repr(fwd_new)
    assert isinstance(fwd_new, Forward)
    assert_forward_allclose(fwd, fwd_new)
    del fwd, fwd_new, fwd_fixed
    gc.collect()


@pytest.mark.slowtest
@testing.requires_testing_data
def test_io_forward(tmp_path):
    """Test IO for forward solutions."""
    # do extensive tests with MEEG + grad
    n_channels, n_src = 366, 108
    fwd = read_forward_solution(fname_meeg_grad)
    assert isinstance(fwd, Forward)
    fwd = read_forward_solution(fname_meeg_grad)
    fwd = convert_forward_solution(fwd, surf_ori=True)
    leadfield = fwd["sol"]["data"]
    assert_equal(leadfield.shape, (n_channels, n_src))
    assert_equal(len(fwd["sol"]["row_names"]), n_channels)
    fname_temp = tmp_path / "test-fwd.fif"
    with pytest.warns(RuntimeWarning, match="stored on disk"):
        write_forward_solution(fname_temp, fwd, overwrite=True)

    fwd = read_forward_solution(fname_meeg_grad)
    fwd = convert_forward_solution(fwd, surf_ori=True)
    fwd_read = read_forward_solution(fname_temp)
    fwd_read = convert_forward_solution(fwd_read, surf_ori=True)
    leadfield = fwd_read["sol"]["data"]
    assert_equal(leadfield.shape, (n_channels, n_src))
    assert_equal(len(fwd_read["sol"]["row_names"]), n_channels)
    assert_equal(len(fwd_read["info"]["chs"]), n_channels)
    assert "dev_head_t" in fwd_read["info"]
    assert "mri_head_t" in fwd_read
    assert_array_almost_equal(fwd["sol"]["data"], fwd_read["sol"]["data"])

    fwd = read_forward_solution(fname_meeg)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=False)
    with pytest.warns(RuntimeWarning, match="stored on disk"):
        write_forward_solution(fname_temp, fwd, overwrite=True)
    fwd_read = read_forward_solution(fname_temp)
    fwd_read = convert_forward_solution(
        fwd_read, surf_ori=True, force_fixed=True, use_cps=False
    )
    assert repr(fwd_read)
    assert isinstance(fwd_read, Forward)
    assert is_fixed_orient(fwd_read)
    assert_forward_allclose(fwd, fwd_read)

    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=True)
    leadfield = fwd["sol"]["data"]
    assert_equal(leadfield.shape, (n_channels, 1494 / 3))
    assert_equal(len(fwd["sol"]["row_names"]), n_channels)
    assert_equal(len(fwd["info"]["chs"]), n_channels)
    assert "dev_head_t" in fwd["info"]
    assert "mri_head_t" in fwd
    assert fwd["surf_ori"]
    with pytest.warns(RuntimeWarning, match="stored on disk"):
        write_forward_solution(fname_temp, fwd, overwrite=True)
    fwd_read = read_forward_solution(fname_temp)
    fwd_read = convert_forward_solution(
        fwd_read, surf_ori=True, force_fixed=True, use_cps=True
    )
    assert repr(fwd_read)
    assert isinstance(fwd_read, Forward)
    assert is_fixed_orient(fwd_read)
    assert_forward_allclose(fwd, fwd_read)

    fwd = read_forward_solution(fname_meeg_grad)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=True)
    leadfield = fwd["sol"]["data"]
    assert_equal(leadfield.shape, (n_channels, n_src / 3))
    assert_equal(len(fwd["sol"]["row_names"]), n_channels)
    assert_equal(len(fwd["info"]["chs"]), n_channels)
    assert "dev_head_t" in fwd["info"]
    assert "mri_head_t" in fwd
    assert fwd["surf_ori"]
    with pytest.warns(RuntimeWarning, match="stored on disk"):
        write_forward_solution(fname_temp, fwd, overwrite=True)
    fwd_read = read_forward_solution(fname_temp)
    fwd_read = convert_forward_solution(
        fwd_read, surf_ori=True, force_fixed=True, use_cps=True
    )
    assert repr(fwd_read)
    assert isinstance(fwd_read, Forward)
    assert is_fixed_orient(fwd_read)
    assert_forward_allclose(fwd, fwd_read)

    # test warnings on bad filenames
    fwd = read_forward_solution(fname_meeg_grad)
    fwd_badname = tmp_path / "test-bad-name.fif.gz"
    with pytest.warns(RuntimeWarning, match="end with"):
        write_forward_solution(fwd_badname, fwd)
    with pytest.warns(RuntimeWarning, match="end with"):
        read_forward_solution(fwd_badname)

    fwd = read_forward_solution(fname_meeg)
    write_forward_solution(fname_temp, fwd, overwrite=True)
    fwd_read = read_forward_solution(fname_temp)
    assert_forward_allclose(fwd, fwd_read)

    h5py = pytest.importorskip("h5py")
    pytest.importorskip("h5io")
    fname_h5 = fname_temp.with_suffix(".h5")
    fwd.save(fname_h5)
    with h5py.File(fname_h5, "r"):
        pass  # just checks for hdf5-ness
    fwd_read = read_forward_solution(fname_h5)
    assert_forward_allclose(fwd, fwd_read)


@testing.requires_testing_data
def test_apply_forward():
    """Test projection of source space data to sensor space."""
    start = 0
    stop = 5
    n_times = stop - start - 1
    sfreq = 10.0
    t_start = 0.123

    fwd = read_forward_solution(fname_meeg)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=True)
    fwd = pick_types_forward(fwd, meg=True)
    assert isinstance(fwd, Forward)

    vertno = [fwd["src"][0]["vertno"], fwd["src"][1]["vertno"]]
    stc_data = np.ones((len(vertno[0]) + len(vertno[1]), n_times))
    stc = SourceEstimate(stc_data, vertno, tmin=t_start, tstep=1.0 / sfreq)

    gain_sum = np.sum(fwd["sol"]["data"], axis=1)

    # Evoked
    evoked = read_evokeds(fname_evoked, condition=0)
    evoked.pick(picks="meg")
    with pytest.warns(RuntimeWarning, match="only .* positive values"):
        evoked = apply_forward(fwd, stc, evoked.info, start=start, stop=stop)
    data = evoked.data
    times = evoked.times

    # do some tests
    assert_array_almost_equal(evoked.info["sfreq"], sfreq)
    assert_array_almost_equal(np.sum(data, axis=1), n_times * gain_sum)
    assert_array_almost_equal(times[0], t_start)
    assert_array_almost_equal(times[-1], t_start + (n_times - 1) / sfreq)

    # vector
    stc_vec = VectorSourceEstimate(
        fwd["source_nn"][:, :, np.newaxis] * stc.data[:, np.newaxis],
        stc.vertices,
        stc.tmin,
        stc.tstep,
    )
    with pytest.warns(RuntimeWarning, match="very large"):
        evoked_2 = apply_forward(fwd, stc_vec, evoked.info)
    assert np.abs(evoked_2.data).mean() > 1e-5
    assert_allclose(evoked.data, evoked_2.data, atol=1e-10)

    # Raw
    with pytest.warns(RuntimeWarning, match="only .* positive values"):
        raw_proj = apply_forward_raw(fwd, stc, evoked.info, start=start, stop=stop)
    data, times = raw_proj[:, :]

    # do some tests
    assert_array_almost_equal(raw_proj.info["sfreq"], sfreq)
    assert_array_almost_equal(np.sum(data, axis=1), n_times * gain_sum)
    atol = 1.0 / sfreq
    assert_allclose(raw_proj.first_samp / sfreq, t_start, atol=atol)
    assert_allclose(
        raw_proj.last_samp / sfreq, t_start + (n_times - 1) / sfreq, atol=atol
    )


@testing.requires_testing_data
def test_restrict_forward_to_stc(tmp_path):
    """Test restriction of source space to source SourceEstimate."""
    start = 0
    stop = 5
    n_times = stop - start - 1
    sfreq = 10.0
    t_start = 0.123

    fwd = read_forward_solution(fname_meeg)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=True)
    fwd = pick_types_forward(fwd, meg=True)

    vertno = [fwd["src"][0]["vertno"][0:15], fwd["src"][1]["vertno"][0:5]]
    stc_data = np.ones((len(vertno[0]) + len(vertno[1]), n_times))
    stc = SourceEstimate(stc_data, vertno, tmin=t_start, tstep=1.0 / sfreq)

    fwd_out = restrict_forward_to_stc(fwd, stc)
    assert isinstance(fwd_out, Forward)

    assert_equal(fwd_out["sol"]["ncol"], 20)
    assert_equal(fwd_out["src"][0]["nuse"], 15)
    assert_equal(fwd_out["src"][1]["nuse"], 5)
    assert_equal(fwd_out["src"][0]["vertno"], fwd["src"][0]["vertno"][0:15])
    assert_equal(fwd_out["src"][1]["vertno"], fwd["src"][1]["vertno"][0:5])

    fwd = read_forward_solution(fname_meeg)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=False)
    fwd = pick_types_forward(fwd, meg=True)

    vertno = [fwd["src"][0]["vertno"][0:15], fwd["src"][1]["vertno"][0:5]]
    stc_data = np.ones((len(vertno[0]) + len(vertno[1]), n_times))
    stc = SourceEstimate(stc_data, vertno, tmin=t_start, tstep=1.0 / sfreq)

    fwd_out = restrict_forward_to_stc(fwd, stc)

    assert_equal(fwd_out["sol"]["ncol"], 60)
    assert_equal(fwd_out["src"][0]["nuse"], 15)
    assert_equal(fwd_out["src"][1]["nuse"], 5)
    assert_equal(fwd_out["src"][0]["vertno"], fwd["src"][0]["vertno"][0:15])
    assert_equal(fwd_out["src"][1]["vertno"], fwd["src"][1]["vertno"][0:5])

    # Test saving the restricted forward object. This only works if all fields
    # are properly accounted for.
    fname_copy = tmp_path / "copy-fwd.fif"
    with pytest.warns(RuntimeWarning, match="stored on disk"):
        write_forward_solution(fname_copy, fwd_out, overwrite=True)
    fwd_out_read = read_forward_solution(fname_copy)
    fwd_out_read = convert_forward_solution(
        fwd_out_read, surf_ori=True, force_fixed=False
    )
    assert_forward_allclose(fwd_out, fwd_out_read)


@testing.requires_testing_data
def test_restrict_forward_to_label(tmp_path):
    """Test restriction of source space to label."""
    fwd = read_forward_solution(fname_meeg)
    fwd = convert_forward_solution(fwd, surf_ori=True, force_fixed=True, use_cps=True)
    fwd = pick_types_forward(fwd, meg=True)

    labels = ["Aud-lh", "Vis-rh"]
    label_lh = read_label(label_path / (labels[0] + ".label"))
    label_rh = read_label(label_path / (labels[1] + ".label"))

    fwd_out = restrict_forward_to_label(fwd, [label_lh, label_rh])

    src_sel_lh = np.intersect1d(fwd["src"][0]["vertno"], label_lh.vertices)
    src_sel_lh = np.searchsorted(fwd["src"][0]["vertno"], src_sel_lh)
    vertno_lh = fwd["src"][0]["vertno"][src_sel_lh]

    nuse_lh = fwd["src"][0]["nuse"]
    src_sel_rh = np.intersect1d(fwd["src"][1]["vertno"], label_rh.vertices)
    src_sel_rh = np.searchsorted(fwd["src"][1]["vertno"], src_sel_rh)
    vertno_rh = fwd["src"][1]["vertno"][src_sel_rh]
    src_sel_rh += nuse_lh

    assert_equal(fwd_out["sol"]["ncol"], len(src_sel_lh) + len(src_sel_rh))
    assert_equal(fwd_out["src"][0]["nuse"], len(src_sel_lh))
    assert_equal(fwd_out["src"][1]["nuse"], len(src_sel_rh))
    assert_equal(fwd_out["src"][0]["vertno"], vertno_lh)
    assert_equal(fwd_out["src"][1]["vertno"], vertno_rh)

    fwd = read_forward_solution(fname_meeg)
    fwd = pick_types_forward(fwd, meg=True)

    labels = ["Aud-lh", "Vis-rh"]
    label_lh = read_label(label_path / (labels[0] + ".label"))
    label_rh = read_label(label_path / (labels[1] + ".label"))

    fwd_out = restrict_forward_to_label(fwd, [label_lh, label_rh])

    src_sel_lh = np.intersect1d(fwd["src"][0]["vertno"], label_lh.vertices)
    src_sel_lh = np.searchsorted(fwd["src"][0]["vertno"], src_sel_lh)
    vertno_lh = fwd["src"][0]["vertno"][src_sel_lh]

    nuse_lh = fwd["src"][0]["nuse"]
    src_sel_rh = np.intersect1d(fwd["src"][1]["vertno"], label_rh.vertices)
    src_sel_rh = np.searchsorted(fwd["src"][1]["vertno"], src_sel_rh)
    vertno_rh = fwd["src"][1]["vertno"][src_sel_rh]
    src_sel_rh += nuse_lh

    assert_equal(fwd_out["sol"]["ncol"], 3 * (len(src_sel_lh) + len(src_sel_rh)))
    assert_equal(fwd_out["src"][0]["nuse"], len(src_sel_lh))
    assert_equal(fwd_out["src"][1]["nuse"], len(src_sel_rh))
    assert_equal(fwd_out["src"][0]["vertno"], vertno_lh)
    assert_equal(fwd_out["src"][1]["vertno"], vertno_rh)

    # Test saving the restricted forward object. This only works if all fields
    # are properly accounted for.
    fname_copy = tmp_path / "copy-fwd.fif"
    write_forward_solution(fname_copy, fwd_out, overwrite=True)
    fwd_out_read = read_forward_solution(fname_copy)
    assert_forward_allclose(fwd_out, fwd_out_read)


@pytest.mark.parametrize("use_cps", [True, False])
@testing.requires_testing_data
def test_restrict_forward_to_label_cps(tmp_path, use_cps):
    """Test for gh-11689."""
    label_lh = read_label(label_path / "Aud-lh.label")
    fwd = read_forward_solution(fname_meeg)
    convert_forward_solution(
        fwd, surf_ori=True, force_fixed=False, copy=False, use_cps=use_cps
    )
    fwd = pick_types_forward(fwd, meg="mag")
    fwd_out = restrict_forward_to_label(fwd, label_lh)
    vert = fwd_out["src"][0]["vertno"][0]

    assert fwd["surf_ori"]
    assert not is_fixed_orient(fwd)
    idx = list(fwd["src"][0]["vertno"]).index(vert)
    assert idx == 126
    go1 = fwd["_orig_sol"][:, idx * 3 : idx * 3 + 3].copy()
    gs1 = fwd["sol"]["data"][:, idx * 3 : idx * 3 + 3].copy()

    assert fwd_out["surf_ori"]
    assert not is_fixed_orient(fwd_out)
    idx = list(fwd_out["src"][0]["vertno"]).index(vert)
    assert idx == 0
    go2 = fwd_out["_orig_sol"][:, idx * 3 : idx * 3 + 3].copy()
    gs2 = fwd_out["sol"]["data"][:, idx * 3 : idx * 3 + 3].copy()
    assert_allclose(go2, go1)
    assert_allclose(gs2, gs1)

    # should be a no-op
    convert_forward_solution(
        fwd_out, surf_ori=True, force_fixed=False, copy=False, use_cps=use_cps
    )
    assert fwd_out["surf_ori"]
    assert not is_fixed_orient(fwd_out)
    assert list(fwd_out["src"][0]["vertno"]).index(vert) == 0
    go3 = fwd_out["_orig_sol"][:, idx * 3 : idx * 3 + 3].copy()
    gs3 = fwd_out["sol"]["data"][:, idx * 3 : idx * 3 + 3].copy()
    assert_allclose(go3, go1)
    assert_allclose(gs3, gs1)


@testing.requires_testing_data
@requires_mne
def test_average_forward_solution(tmp_path):
    """Test averaging forward solutions."""
    fwd = read_forward_solution(fname_meeg)
    # input not a list
    pytest.raises(TypeError, average_forward_solutions, 1)
    # list is too short
    pytest.raises(ValueError, average_forward_solutions, [])
    # negative weights
    pytest.raises(ValueError, average_forward_solutions, [fwd, fwd], [-1, 0])
    # all zero weights
    pytest.raises(ValueError, average_forward_solutions, [fwd, fwd], [0, 0])
    # weights not same length
    pytest.raises(ValueError, average_forward_solutions, [fwd, fwd], [0, 0, 0])
    # list does not only have all dict()
    pytest.raises(TypeError, average_forward_solutions, [1, fwd])

    # try an easy case
    fwd_copy = average_forward_solutions([fwd])
    assert isinstance(fwd_copy, Forward)
    assert_array_equal(fwd["sol"]["data"], fwd_copy["sol"]["data"])

    # modify a fwd solution, save it, use MNE to average with old one
    fwd_copy["sol"]["data"] *= 0.5
    fname_copy = str(tmp_path / "copy-fwd.fif")
    write_forward_solution(fname_copy, fwd_copy, overwrite=True)
    cmd = (
        "mne_average_forward_solutions",
        "--fwd",
        fname_meeg,
        "--fwd",
        fname_copy,
        "--out",
        fname_copy,
    )
    run_subprocess(cmd)

    # now let's actually do it, with one filename and one fwd
    fwd_ave = average_forward_solutions([fwd, fwd_copy])
    assert_array_equal(0.75 * fwd["sol"]["data"], fwd_ave["sol"]["data"])
    # fwd_ave_mne = read_forward_solution(fname_copy)
    # assert_array_equal(fwd_ave_mne['sol']['data'], fwd_ave['sol']['data'])

    # with gradient
    fwd = read_forward_solution(fname_meeg_grad)
    fwd_ave = average_forward_solutions([fwd, fwd])
    assert_forward_allclose(fwd, fwd_ave)


@testing.requires_testing_data
def test_priors():
    """Test prior computations."""
    # Depth prior
    fwd = read_forward_solution(fname_meeg)
    assert not is_fixed_orient(fwd)
    n_sources = fwd["nsource"]
    info = read_info(fname_evoked)
    depth_prior = compute_depth_prior(fwd, info, exp=0.8)
    assert depth_prior.shape == (3 * n_sources,)
    depth_prior = compute_depth_prior(fwd, info, exp=0.0)
    assert_array_equal(depth_prior, 1.0)
    with pytest.raises(ValueError, match='must be "whiten"'):
        compute_depth_prior(fwd, info, limit_depth_chs="foo")
    with pytest.raises(ValueError, match="noise_cov must be a Covariance"):
        compute_depth_prior(fwd, info, limit_depth_chs="whiten")
    fwd_fixed = convert_forward_solution(fwd, force_fixed=True)
    depth_prior = compute_depth_prior(fwd_fixed, info=info)
    assert depth_prior.shape == (n_sources,)
    # Orientation prior
    orient_prior = compute_orient_prior(fwd, 1.0)
    assert_array_equal(orient_prior, 1.0)
    orient_prior = compute_orient_prior(fwd_fixed, 0.0)
    assert_array_equal(orient_prior, 1.0)
    with pytest.raises(ValueError, match="oriented in surface coordinates"):
        compute_orient_prior(fwd, 0.5)
    fwd_surf_ori = convert_forward_solution(fwd, surf_ori=True)
    orient_prior = compute_orient_prior(fwd_surf_ori, 0.5)
    assert all(np.isin(orient_prior, (0.5, 1.0)))
    with pytest.raises(ValueError, match="between 0 and 1"):
        compute_orient_prior(fwd_surf_ori, -0.5)
    with pytest.raises(ValueError, match="with fixed orientation"):
        compute_orient_prior(fwd_fixed, 0.5)


@testing.requires_testing_data
def test_equalize_channels():
    """Test equalization of channels for instances of Forward."""
    fwd1 = read_forward_solution(fname_meeg)
    pick_channels_forward(fwd1, include=["EEG 001", "EEG 002", "EEG 003"], copy=False)
    fwd2 = pick_channels_forward(fwd1, include=["EEG 002", "EEG 001"], ordered=True)
    fwd1, fwd2 = equalize_channels([fwd1, fwd2])
    assert fwd1.ch_names == ["EEG 001", "EEG 002"]
    assert fwd2.ch_names == ["EEG 001", "EEG 002"]

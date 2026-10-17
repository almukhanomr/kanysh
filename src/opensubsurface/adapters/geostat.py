import numpy as np
from scipy.special import expit, logit

from opensubsurface.domain.numerics import grid_arrays
from opensubsurface.errors import require


def transforms(field):
    return (logit, expit) if field == "phi" else (np.log, np.exp)


def conditioned(p, arrays, grid, mode):
    import gstools as gs

    transform, inverse = transforms(p["field"])
    pos = np.asarray(p["conditioning"]["positions"], float).T
    vals = np.asarray(p["conditioning"]["values"], float)
    zvals = transform(vals)
    centers, _ = grid_arrays(grid)
    mask = arrays["active"].astype(bool) & (arrays["zones"] == p["zone_id"])
    require(mask.any(), "QC_FAILED", "Зона не найдена")
    e, shape = grid["extent"], grid["shape"]
    # Conditioning must be inside the selected zone, preventing cross-boundary leakage.
    ijk = np.floor(
        (pos.T - np.array(e)[[0, 2, 4]]) / ((np.array(e)[[1, 3, 5]] - np.array(e)[[0, 2, 4]]) / shape)
    ).astype(int)
    require(((ijk >= 0) & (ijk < shape)).all(), "QC_FAILED", "Conditioning вне сетки")
    require(mask[tuple(ijk.T)].all(), "QC_FAILED", "Conditioning принадлежит другой зоне")
    model = gs.Exponential(
        dim=3, var=p["variance"], len_scale=p["length_scale_m"], anis=p["anisotropy"], nugget=0
    )
    bins = np.linspace(0, p["length_scale_m"] * 2, 9)
    bin_center, gamma, counts = gs.vario_estimate(pos, zvals, bin_edges=bins, return_counts=True)
    fit_status = "specified_model"
    if mode == "variogram_fit":
        good = np.isfinite(gamma) & (counts > 0)
        require(good.sum() >= 3, "QC_FAILED", "Недостаточно непустых lag bins для fit")
        model.fit_variogram(bin_center[good], gamma[good], nugget=False, anis=False)
        fit_status = "fitted_exponential"
    krige = gs.krige.Ordinary(model, cond_pos=pos, cond_val=zvals, exact=True, cond_err="nugget")
    targets = centers[mask].T
    if mode == "properties_simulate":
        generator = gs.CondSRF(krige)
        field = generator(targets, mesh_type="unstructured", seed=p["seed"])
    else:
        field, _ = krige(targets, mesh_type="unstructured")
    at_observations, _ = krige(pos, mesh_type="unstructured")
    residual = inverse(at_observations) - vals
    out = {k: v.copy() for k, v in arrays.items()}
    out[p["field"]][mask] = inverse(field)
    require(np.isfinite(out[p["field"]][mask]).all(), "QC_FAILED", "Обратный transform переполнен")
    errors = []
    for well in sorted(set(p["conditioning"]["well_ids"])):
        training = np.array([w != well for w in p["conditioning"]["well_ids"]])
        if training.sum() < 2:
            continue
        holdout = gs.krige.Ordinary(model, cond_pos=pos[:, training], cond_val=zvals[training], exact=True)
        predicted, _ = holdout(pos[:, ~training], mesh_type="unstructured")
        errors.extend((inverse(predicted) - vals[~training]).tolist())
    summary = dict(
        field=p["field"],
        zone_id=p["zone_id"],
        seed=p["seed"],
        backend="gstools-cpu",
        transform="logit" if p["field"] == "phi" else "log",
        no_clipping=True,
        variogram=dict(
            model="Exponential",
            variance=float(model.var),
            length_scale_m=float(model.len_scale),
            anisotropy=list(p["anisotropy"]),
            nugget=0,
            status=fit_status,
        ),
        experimental=dict(lag_m=bin_center.tolist(), gamma=gamma.tolist(), counts=counts.tolist()),
        conditioning_max_abs_error=float(np.abs(residual).max()),
        holdout=dict(
            method="leave-one-well-out",
            samples=len(errors),
            rmse=float(np.sqrt(np.mean(np.square(errors)))) if errors else None,
            bias=float(np.mean(errors)) if errors else None,
        ),
        assumption="phi и K независимы; моделирование только внутри выбранной зоны",
    )
    return out, summary

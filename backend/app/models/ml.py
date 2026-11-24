"""Tabular machine-learning models: LightGBM, XGBoost, random forest, regularised logistic regression.

All of them forecast the same thing as the statistical models (probabilities of up / flat / down plus return quantiles) so
they can be judged by the same walk-forward test against the same baselines.

How a model is built inside `fit(train)` (everything uses ONLY the training data it is given):
  1. Build features and labels. Rows whose label window runs past the end of the data are purged.
  2. Split the rows in time: an early part to fit, a later part to validate, with a gap of `horizon` rows between them
     (PURGE) so no validation label overlaps a training label.
  3. Optionally tune a few hyper-parameters with Optuna, scored by purged K-fold cross-validation on the fitting part only.
  4. Fit on the fitting part, stopping early on the validation part; learn a TEMPERATURE that makes the probabilities honest
     (tree models are usually over-confident); measure interval widths from validation residuals.
  5. Refit on all labelled rows with the chosen settings.
Interpretation (SHAP, permutation importance, partial dependence) is computed from the validation rows with the model that
never saw them, so it explains behaviour on unseen data rather than memorised data.
"""
from __future__ import annotations

import math
import warnings
from typing import Any

import numpy as np
import pandas as pd

from app.eval.purged_cv import PurgedKFold
from app.models.base import Model, ModelError, ModelView, flat_band, window_info
from app.models.ml_features import CLASSES, MIN_ROWS, build_dataset, latest_row

QS = (0.05, 0.25, 0.5, 0.75, 0.95)
LAMBDAS = np.linspace(0.0, 1.0, 11)


def logloss(y: np.ndarray, p: np.ndarray) -> float:
    p = np.clip(p, 1e-9, 1.0)
    return float(-np.mean(np.log(p[np.arange(len(y)), y])))


def shrink_to_prior(p: np.ndarray, prior: np.ndarray, lam: float) -> np.ndarray:
    """Blend model probabilities with the training base rates: (1 - lam) * model + lam * base_rate. lam = 0 trusts the model fully;
    lam = 1 is the base-rate baseline. A model with no real skill ends up at lam near 1, i.e. it collapses onto the baseline
    instead of drifting below it (plain temperature scaling would pull it toward uniform thirds, which is worse than the base rate)."""
    return (1.0 - lam) * p + lam * prior[None, :]


class ClassWrapper:
    """Makes any scikit-learn style classifier tolerate a missing class (LightGBM silently shrinks, XGBoost raises) and always
    returns an (n, 3) matrix ordered up / flat / down."""

    def __init__(self, model: Any) -> None:
        self.model = model
        self.present = np.array([], dtype=int)

    def fit(self, X: Any, y: np.ndarray, **kw: Any) -> ClassWrapper:
        self.present = np.unique(y)
        mapped = np.searchsorted(self.present, y)
        ev = kw.pop("eval_set", None)
        if ev is not None:
            kw["eval_set"] = [(Xv, np.searchsorted(self.present, np.clip(yv, self.present.min(), self.present.max()))) for Xv, yv in ev]
        self.model.fit(X, mapped, **kw)
        return self

    def proba(self, X: Any) -> np.ndarray:
        raw = np.asarray(self.model.predict_proba(X))
        out = np.zeros((len(raw), 3))
        out[:, self.present] = raw
        if len(self.present) < 3:
            out = out + 1e-6                              # an unseen class is "very unlikely", not impossible
        return out / out.sum(axis=1, keepdims=True)


class Tabular(Model):
    kind = "ml"
    feature_set = "price"
    needs: str | None = None
    uses_gbm = False
    horizon_default = 5

    def __init__(self, fast: bool = False, seed: int = 0, horizon: int = 5, aux: dict | None = None, **kw: Any) -> None:
        super().__init__(fast, seed)
        self.horizon, self.aux = horizon, aux or {}
        self.trials = 0 if fast else 6
        self.shrink = 0.0
        self.prior = np.array([1 / 3, 1 / 3, 1 / 3])
        self.best_n = 0
        self.params_used: dict[str, Any] = {}
        self._info: dict[str, Any] = {}
        self.features: list[str] = []

    # ---- hooks for subclasses ----
    def make_clf(self, params: dict[str, Any], n_estimators: int | None = None) -> Any:
        raise NotImplementedError

    def default_params(self) -> dict[str, Any]:
        return {}

    def suggest(self, trial: Any) -> dict[str, Any]:
        return {}

    def fit_stage(self, clf: ClassWrapper, X: pd.DataFrame, y: np.ndarray, Xv: pd.DataFrame | None, yv: np.ndarray | None) -> int:
        clf.fit(X, y)
        return 0

    def make_quantiles(self, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
        """Return an object with .predict(X) -> (n, 5) log-return quantiles. Default: point regressor + validation residuals."""
        raise NotImplementedError

    # ---- training ----
    def fit(self, train: pd.DataFrame) -> Tabular:
        self._check(train)
        warnings.filterwarnings("ignore")
        ds = build_dataset(train, self.horizon, self.feature_set, self.aux)
        n = len(ds.y)
        if n < MIN_ROWS:
            raise ModelError(f"{self.name} needs at least {MIN_ROWS} labelled rows, has {n}")
        if self.feature_set in ("sentiment", "combined"):
            cov = float(ds.X[[c for c in ds.X.columns if c in ("mean_sent", "recency_weighted")]].notna().any(axis=1).mean())
            if cov < 0.25:
                raise ModelError(f"{self.name} needs news history: only {cov:.0%} of training days have sentiment (need at least 25%)")
        n_val = max(50, int(0.2 * n))
        gap = self.horizon
        cut = n - n_val - gap                                        # fit rows [0, cut), purge gap, validation rows [n - n_val, n)
        if cut < 100:
            raise ModelError(f"{self.name}: not enough rows left after the validation split")
        X, y, r = ds.X, ds.y, ds.ret
        Xf, yf, rf = X.iloc[:cut], y[:cut], r[:cut]
        Xv, yv, rv = X.iloc[n - n_val:], y[n - n_val:], r[n - n_val:]
        self.features = list(X.columns)
        params = {**self.default_params(), **(self.tune(Xf, yf) if self.trials and self.uses_gbm else {})}
        self.params_used = params
        clf1 = ClassWrapper(self.make_clf(params))
        self.best_n = self.fit_stage(clf1, Xf, yf, Xv, yv)
        pv = clf1.proba(Xv)
        prior_fit = np.bincount(yf, minlength=3) / len(yf)
        losses = [logloss(yv, shrink_to_prior(pv, prior_fit, lam)) for lam in LAMBDAS]
        self.shrink = float(LAMBDAS[int(np.argmin(losses))])            # chosen on held-out days only
        self.prior = np.bincount(y, minlength=3) / len(y)
        clf = ClassWrapper(self.make_clf(params, self.best_n or None))
        clf.fit(X, y)                                                # final model: all labelled rows
        self.clf, self.clf1 = clf, clf1
        self.Xv, self.yv, self.rv = Xv, yv, rv
        self.quant = self.make_quantiles(X, r, Xv, rv, Xf, rf)
        self.val_loss = {"raw": logloss(yv, pv), "calibrated": min(losses), "trust_in_model": 1.0 - self.shrink,
                         "base_rate_loss": logloss(yv, np.tile(prior_fit, (len(yv), 1)))}
        self._info = {**window_info(train), "labelled_rows": n, "validation_rows": int(n_val), "features": len(self.features)}
        self._fitted = True
        return self

    def tune(self, X: pd.DataFrame, y: np.ndarray) -> dict[str, Any]:
        """Optuna search scored by purged K-fold CV on the fitting rows only. Small by design (a few trials)."""
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
        cv = PurgedKFold(3, horizon=self.horizon, embargo=self.horizon)

        def objective(trial: Any) -> float:
            p = {**self.default_params(), **self.suggest(trial)}
            scores = []
            for tr, te in cv.split(len(y)):
                if len(np.unique(y[tr])) < 2 or len(te) < 10:
                    continue
                c = ClassWrapper(self.make_clf(p, 120))
                c.fit(X.iloc[tr], y[tr])
                scores.append(logloss(y[te], c.proba(X.iloc[te])))
            return float(np.mean(scores)) if scores else 9.0
        study = optuna.create_study(direction="minimize", sampler=optuna.samplers.TPESampler(seed=self.seed))
        study.optimize(objective, n_trials=self.trials)
        return {**self.suggest_fixed(study.best_params)}

    def suggest_fixed(self, best: dict[str, Any]) -> dict[str, Any]:
        return best

    # ---- prediction ----
    def probs(self, X: pd.DataFrame, model: ClassWrapper | None = None) -> np.ndarray:
        return shrink_to_prior((model or self.clf).proba(X), self.prior, self.shrink)

    def predict(self, history: pd.DataFrame, horizon: int, detail: bool = True, **kw: Any) -> ModelView:
        if horizon != self.horizon:
            raise ModelError(f"{self.name} was trained for a {self.horizon}-day horizon, not {horizon}")
        row = latest_row(history, self.feature_set, self.aux)
        p = self.probs(row)[0]
        q = np.sort(np.asarray(self.quant.predict(row)).reshape(-1)[:5])
        quantiles = {str(int(k * 100)): float(np.expm1(v)) for k, v in zip(QS, q, strict=True)}
        band = flat_band(history["close"], horizon)
        drivers, extras = self.explain_row(row, detail)
        view = self._view(history, horizon, (float(p[0]), float(p[1]), float(p[2])), quantiles, band, self._info, drivers=drivers,
                          notes=self.notes())
        view.extras.update(extras)
        view.extras["calibration"] = self.val_loss
        return view

    def notes(self) -> list[str]:
        return [f"Learns from {len(self.features)} {self.feature_set} features. On held-out days it earned {1 - self.shrink:.0%} trust: its probabilities "
                f"are blended {self.shrink:.0%} toward the base rate.", "Tree models can memorise noise: trust the walk-forward verdict, not the fit."]

    def explain_row(self, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return [], {}

    def params(self) -> dict[str, Any]:
        return {"shrink_to_base_rate": self.shrink, "best_n_estimators": self.best_n, **{k: (float(v) if isinstance(v, int | float) else v) for k, v in self.params_used.items()}}

    # ---- interpretation helpers (model-agnostic) ----
    def permutation_importance(self, repeats: int | None = None, top: int = 12) -> list[dict[str, Any]]:
        """How much held-out log-loss gets WORSE when one feature's values are shuffled. Uses the stage-1 model (never saw
        the validation rows), so this is about generalisation, not memorisation."""
        rng = np.random.default_rng(self.seed)
        repeats = repeats or (3 if self.fast else 5)
        Xv, yv = self.Xv.iloc[-150:], self.yv[-150:]                  # cap the cost: forests are slow to score repeatedly
        base = logloss(yv, self.probs(Xv, self.clf1))
        out = []
        for f in self.features:
            if Xv[f].notna().sum() < 10 or Xv[f].nunique() < 2:
                continue
            deltas = []
            for _ in range(repeats):
                Xp = Xv.copy()
                Xp[f] = rng.permutation(Xp[f].to_numpy())
                deltas.append(logloss(yv, self.probs(Xp, self.clf1)) - base)
            out.append({"feature": f, "importance": float(np.mean(deltas)), "std": float(np.std(deltas))})
        out.sort(key=lambda d: -d["importance"])
        return out[:top]

    def partial_dependence(self, features: list[str], points: int = 12) -> list[dict[str, Any]]:
        """Average P(up) as one feature is swept across its typical range with everything else held at observed values."""
        res = []
        for f in features:
            col = self.Xv[f].dropna()
            if col.nunique() < 3:
                continue
            grid = np.unique(np.quantile(col, np.linspace(0.05, 0.95, points)))
            ys = []
            for g in grid:
                Xp = self.Xv.copy()
                Xp[f] = g
                ys.append(float(self.probs(Xp, self.clf1)[:, 0].mean()))
            res.append({"feature": f, "grid": [float(x) for x in grid], "p_up": ys})
        return res


def _regressor_quantiles(point: Any, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
    """Point regressor + empirical quantiles of validation residuals (a split-conformal style interval)."""
    import copy
    first = copy.deepcopy(point).fit(X1, r1)
    resid = rv - first.predict(Xv)
    off = np.quantile(resid, QS)
    final = point.fit(X, r)

    class _Q:
        @staticmethod
        def predict(Z: pd.DataFrame) -> np.ndarray:
            return final.predict(Z)[:, None] + off[None, :]
    return _Q()


# ---------------- LightGBM ----------------

class _LgbmBase(Tabular):
    uses_gbm = True
    description = "LightGBM gradient-boosted trees on technical features; quantile regression for the return range."

    def default_params(self) -> dict[str, Any]:
        return {"num_leaves": 8, "learning_rate": 0.04, "min_child_samples": 30, "reg_lambda": 5.0, "colsample_bytree": 0.7}

    def suggest(self, trial: Any) -> dict[str, Any]:
        return {"num_leaves": trial.suggest_int("num_leaves", 4, 16), "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.08, log=True),
                "min_child_samples": trial.suggest_int("min_child_samples", 20, 60), "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 20.0, log=True),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 0.9)}

    def make_clf(self, params: dict[str, Any], n_estimators: int | None = None) -> Any:
        import lightgbm as lgb
        return lgb.LGBMClassifier(n_estimators=n_estimators or (150 if self.fast else 400), subsample=0.8, subsample_freq=1, verbose=-1,
                                  n_jobs=2, random_state=self.seed, **params)

    def fit_stage(self, clf: ClassWrapper, X: pd.DataFrame, y: np.ndarray, Xv: pd.DataFrame | None, yv: np.ndarray | None) -> int:
        import lightgbm as lgb
        clf.fit(X, y, eval_set=[(Xv, yv)], callbacks=[lgb.early_stopping(25, verbose=False)])
        return max(20, int(getattr(clf.model, "best_iteration_", 0) or 0))

    def make_quantiles(self, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
        import lightgbm as lgb
        models = [lgb.LGBMRegressor(objective="quantile", alpha=q, n_estimators=60 if self.fast else 120, learning_rate=0.04, num_leaves=6,
                                    min_child_samples=30, reg_lambda=5.0, subsample=0.8, subsample_freq=1, verbose=-1, n_jobs=2,
                                    random_state=self.seed).fit(X, r) for q in QS]

        class _Q:
            @staticmethod
            def predict(Z: pd.DataFrame) -> np.ndarray:
                return np.column_stack([m.predict(Z) for m in models])
        return _Q()

    def explain_row(self, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return shap_explain(self, row, detail)


class Lgbm(_LgbmBase):
    name = "lgbm"
    feature_set = "price"
    description = "LightGBM on technical (price/volume) features, with quantile regression for the return range. Price-only: the ablation reference."


class LgbmSentiment(_LgbmBase):
    name = "lgbm_sentiment"
    feature_set = "sentiment"
    needs = "sentiment"
    description = "LightGBM using ONLY news-sentiment features (ablation: how much can news alone say?)."


class LgbmCombined(_LgbmBase):
    name = "lgbm_combined"
    feature_set = "combined"
    needs = "sentiment"
    description = "LightGBM on technical AND news-sentiment features (ablation: does news add anything to price?)."


# ---------------- XGBoost ----------------

class Xgb(Tabular):
    name = "xgb"
    uses_gbm = True
    description = "XGBoost gradient-boosted trees on technical features; multi-quantile regression for the return range."

    def default_params(self) -> dict[str, Any]:
        return {"max_depth": 3, "learning_rate": 0.04, "min_child_weight": 5, "reg_lambda": 5.0, "colsample_bytree": 0.7}

    def suggest(self, trial: Any) -> dict[str, Any]:
        return {"max_depth": trial.suggest_int("max_depth", 2, 5), "learning_rate": trial.suggest_float("learning_rate", 0.02, 0.08, log=True),
                "min_child_weight": trial.suggest_int("min_child_weight", 3, 20), "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 20.0, log=True),
                "colsample_bytree": trial.suggest_float("colsample_bytree", 0.5, 0.9)}

    def make_clf(self, params: dict[str, Any], n_estimators: int | None = None) -> Any:
        import xgboost as xgb
        kw: dict[str, Any] = dict(n_estimators=n_estimators or (120 if self.fast else 300), subsample=0.8, tree_method="hist", n_jobs=2,
                                  random_state=self.seed, eval_metric="mlogloss", **params)
        if n_estimators is None:
            kw["early_stopping_rounds"] = 25
        return xgb.XGBClassifier(**kw)

    def fit_stage(self, clf: ClassWrapper, X: pd.DataFrame, y: np.ndarray, Xv: pd.DataFrame | None, yv: np.ndarray | None) -> int:
        clf.fit(X, y, eval_set=[(Xv, yv)], verbose=False)
        return max(20, int(getattr(clf.model, "best_iteration", 0) or 0) + 1)

    def make_quantiles(self, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
        import xgboost as xgb
        m = xgb.XGBRegressor(objective="reg:quantileerror", quantile_alpha=np.array(QS), n_estimators=60 if self.fast else 120, max_depth=3,
                             learning_rate=0.04, subsample=0.8, tree_method="hist", n_jobs=2, random_state=self.seed).fit(X, r)
        return m

    def explain_row(self, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        return shap_explain(self, row, detail)


# ---------------- random forest and logistic regression ----------------

class RandomForest(Tabular):
    name = "rf"
    description = "Random forest (many shallow decorrelated trees, averaged). A strong, hard-to-overfit tabular baseline."

    def make_clf(self, params: dict[str, Any], n_estimators: int | None = None) -> Any:
        from sklearn.ensemble import RandomForestClassifier
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
        return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                             RandomForestClassifier(n_estimators=100 if self.fast else 300, min_samples_leaf=20, max_features="sqrt",
                                                    n_jobs=2, random_state=self.seed))

    def make_quantiles(self, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
        from sklearn.ensemble import RandomForestRegressor
        from sklearn.impute import SimpleImputer
        from sklearn.pipeline import make_pipeline
        point = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True),
                              RandomForestRegressor(n_estimators=80 if self.fast else 200, min_samples_leaf=20, max_features=0.4, n_jobs=2, random_state=self.seed))
        return _regressor_quantiles(point, X, r, Xv, rv, X1, r1)

    def explain_row(self, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        extras: dict[str, Any] = {}
        if detail:
            pi = self.permutation_importance()
            extras = {"permutation_importance": pi, "partial_dependence": self.partial_dependence([d["feature"] for d in pi[:3]])}
        rf = self.clf.model.steps[-1][1]
        imp = sorted(zip(self.features, rf.feature_importances_, strict=True), key=lambda t: -t[1])[:5]
        return [{"name": f"top feature: {f}", "value": f"{v:.3f} importance"} for f, v in imp], extras


class Logit(Tabular):
    name = "logit"
    description = "Regularised multinomial logistic regression on standardised features. Simple, interpretable, hard to overfit."

    def make_clf(self, params: dict[str, Any], n_estimators: int | None = None) -> Any:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import LogisticRegression
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        return make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(),
                             LogisticRegression(C=0.05, max_iter=500, random_state=self.seed))

    def make_quantiles(self, X: pd.DataFrame, r: np.ndarray, Xv: pd.DataFrame, rv: np.ndarray, X1: pd.DataFrame, r1: np.ndarray) -> Any:
        from sklearn.impute import SimpleImputer
        from sklearn.linear_model import Ridge
        from sklearn.pipeline import make_pipeline
        from sklearn.preprocessing import StandardScaler
        point = make_pipeline(SimpleImputer(strategy="median", keep_empty_features=True), StandardScaler(), Ridge(alpha=300.0))
        return _regressor_quantiles(point, X, r, Xv, rv, X1, r1)

    def explain_row(self, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
        lr = self.clf.model.steps[-1][1]
        pos = list(self.clf.present).index(0) if 0 in self.clf.present else None
        drivers: list[dict[str, Any]] = []
        if pos is not None:
            z = self.clf.model.steps[1][1].transform(self.clf.model.steps[0][1].transform(row))[0]
            contrib = lr.coef_[pos] * z
            for i in np.argsort(-np.abs(contrib))[:5]:
                drivers.append({"name": f"{self.features[i]} pushes P(up)", "value": f"{contrib[i]:+.3f}"})
        extras: dict[str, Any] = {}
        if detail:
            pi = self.permutation_importance()
            extras = {"permutation_importance": pi, "partial_dependence": self.partial_dependence([d["feature"] for d in pi[:3]])}
        return drivers, extras


# ---------------- SHAP for the boosted-tree models ----------------

def shap_values(model: Tabular, clf: ClassWrapper, X: pd.DataFrame) -> np.ndarray:
    """SHAP values shaped (rows, features, classes) in the order up / flat / down, even if a class was missing in training."""
    import shap
    sv = shap.TreeExplainer(clf.model).shap_values(X)
    sv = np.asarray(sv) if not isinstance(sv, list) else np.stack(sv, axis=-1)
    out = np.zeros((sv.shape[0], sv.shape[1], 3))
    out[:, :, clf.present] = sv
    return out


def shap_explain(model: Tabular, row: pd.DataFrame, detail: bool) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    sv = shap_values(model, model.clf, row)[0]                       # (features, 3)
    up = sv[:, 0]
    order = np.argsort(-np.abs(up))[:5]
    drivers = [{"name": f"{model.features[i]} = {row.iloc[0, i]:.3g}" if pd.notna(row.iloc[0, i]) else f"{model.features[i]} = n/a",
                "value": f"{up[i]:+.3f} toward up"} for i in order]
    extras: dict[str, Any] = {}
    if detail:
        sample = model.Xv.iloc[-200:]
        g = shap_values(model, model.clf1, sample)
        glob = np.abs(g).mean(axis=(0, 2))                            # mean |SHAP| across rows and the three outcomes
        top = np.argsort(-glob)[:15]
        pi = model.permutation_importance()
        extras = {
            "shap_global": [{"feature": model.features[i], "mean_abs_shap": float(glob[i])} for i in top],
            "shap_now": [{"feature": model.features[i], "value": None if pd.isna(row.iloc[0, i]) else float(row.iloc[0, i]),
                          "toward_up": float(up[i]), "toward_down": float(sv[i, 2])} for i in np.argsort(-np.abs(up))[:10]],
            "permutation_importance": pi, "partial_dependence": model.partial_dependence([d["feature"] for d in pi[:3]]),
            "shap_note": "SHAP splits a single prediction into per-feature pushes toward 'up'. Global = average size of those pushes on held-out days.",
        }
    return drivers, extras


__all__ = ["Lgbm", "LgbmSentiment", "LgbmCombined", "Xgb", "RandomForest", "Logit", "Tabular", "ClassWrapper", "shrink_to_prior", "logloss", "CLASSES", "math"]

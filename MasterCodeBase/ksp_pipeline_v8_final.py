#!/usr/bin/env python3
"""
KSP Crime Intelligence Pipeline v8
==================================
A corrected, leakage-aware pipeline for synthetic-data engineering tests.

Important
---------
This program demonstrates forecasting mechanics. Synthetic-data performance
must not be presented as evidence of real-world policing effectiveness.
"""

from __future__ import annotations

import argparse
import json
import math
import warnings
from pathlib import Path
from typing import Any

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import ConvexHull, QhullError, Voronoi
from scipy.stats import gamma as gamma_dist
from scipy.stats import poisson
from sklearn.cluster import DBSCAN
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import (
    average_precision_score,
    brier_score_loss,
    f1_score,
    mean_absolute_error,
    mean_poisson_deviance,
    precision_recall_curve,
    precision_score,
    recall_score,
    roc_auc_score,
)
from sklearn.neighbors import BallTree, NearestNeighbors

warnings.filterwarnings("ignore")

EARTH_RADIUS_KM = 6371.0088
KA_LAT = (11.0, 18.5)
KA_LON = (73.5, 78.5)
DEFAULT_OUT_DIR = Path("pipeline_outputs_v8")

# Defensive synthetic-coordinate coast guard. It is applied only to the three
# west-coast districts and only when a station lies west of the coarse inland
# coastline. Real deployments should replace this with authoritative station
# coordinates and administrative boundary validation.
COASTAL_DISTRICTS = {"Dakshina Kannada", "Udupi", "Uttara Kannada"}
COAST_GUARD_POINTS = [
    (12.55, 74.91), (12.80, 74.89), (13.00, 74.85), (13.25, 74.80),
    (13.50, 74.75), (13.80, 74.65), (14.10, 74.57), (14.50, 74.50),
    (14.80, 74.31), (15.05, 74.23),
]

def coastal_land_floor(latitude: float, inland_margin: float = 0.03) -> float:
    lats = np.asarray([p[0] for p in COAST_GUARD_POINTS], dtype=float)
    lons = np.asarray([p[1] for p in COAST_GUARD_POINTS], dtype=float)
    return float(np.interp(latitude, lats, lons) + inland_margin)

def correct_synthetic_coastal_stations(station_meta: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    out = station_meta.copy()
    corrections: list[dict[str, Any]] = []
    for idx, row in out.iterrows():
        dname = str(row.get("DistrictName", ""))
        if dname not in COASTAL_DISTRICTS:
            continue
        lat = float(row["station_lat"]); lon = float(row["station_lon"])
        floor = coastal_land_floor(lat, inland_margin=0.03)
        if lon < floor:
            out.at[idx, "station_lon"] = floor
            corrections.append({
                "station_id": int(row["PoliceStationID"]), "station_name": str(row.get("PoliceStationName", "")),
                "district_name": dname, "old_lat": round(lat, 6), "old_lon": round(lon, 6),
                "new_lat": round(lat, 6), "new_lon": round(floor, 6),
                "reason": "synthetic coastal coordinate shifted inland",
            })
    return out, corrections


def log(phase: str | int, message: str) -> None:
    print(f"[Phase {phase}] {message}")


def json_safe(value: Any) -> Any:
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return None if not np.isfinite(value) else float(value)
    if isinstance(value, (pd.Timestamp, pd.Period)):
        return str(value)
    if isinstance(value, np.ndarray):
        return value.tolist()
    raise TypeError(f"Not JSON serialisable: {type(value)}")


def save_json(out_dir: Path, data: Any, filename: str) -> Path:
    path = out_dir / filename
    path.write_text(json.dumps(data, indent=2, default=json_safe), encoding="utf-8")
    log("OUT", f"Saved {filename} ({path.stat().st_size // 1024}KB)")
    return path


def robust_date(series: pd.Series) -> pd.Series:
    return pd.to_datetime(series, errors="coerce", dayfirst=True)


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    p1 = math.radians(lat1)
    p2 = math.radians(lat2)
    dp = math.radians(lat2 - lat1)
    dl = math.radians(lon2 - lon1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * EARTH_RADIUS_KM * math.asin(math.sqrt(a))


def latlon_to_km(points: np.ndarray) -> np.ndarray:
    points = np.asarray(points, dtype=float)
    lat0 = float(np.nanmean(points[:, 0]))
    y = points[:, 0] * 111.32
    x = points[:, 1] * 111.32 * max(math.cos(math.radians(lat0)), 0.2)
    return np.column_stack([x, y])


def station_area_lookup(df: pd.DataFrame, min_area_km2: float = 5.0, buffer_km: float = 10.0) -> dict[int, float]:
    """Approximate station service areas with district-clipped Voronoi cells."""
    station_meta = (
        df[df["has_valid_geo"]]
        .groupby(["DistrictID", "PoliceStationID"], as_index=False)
        .agg(lat=("station_lat", "first"), lon=("station_lon", "first"))
    )
    areas: dict[int, float] = {}
    for did, group in station_meta.groupby("DistrictID"):
        ids = group["PoliceStationID"].astype(int).tolist()
        pts = latlon_to_km(group[["lat", "lon"]].to_numpy())
        n = len(ids)
        if n == 0:
            continue
        if n == 1:
            areas[ids[0]] = 300.0
            continue
        try:
            from shapely.geometry import MultiPoint, Point, Polygon
        except Exception:
            equal = max(min_area_km2, 300.0 / n)
            for sid in ids:
                areas[sid] = equal
            continue
        hull = MultiPoint(pts).convex_hull.buffer(buffer_km)
        if n == 2:
            equal = max(min_area_km2, float(hull.area) / 2)
            for sid in ids:
                areas[sid] = equal
            continue
        try:
            vor = Voronoi(pts)
        except Exception:
            equal = max(min_area_km2, float(hull.area) / n)
            for sid in ids:
                areas[sid] = equal
            continue

        center = vor.points.mean(axis=0)
        radius = (np.ptp(vor.points, axis=0).max() + 1) * 20
        ridges: dict[int, list[tuple[int, int, int]]] = {}
        for (p1, p2), (v1, v2) in zip(vor.ridge_points, vor.ridge_vertices):
            ridges.setdefault(p1, []).append((p2, v1, v2))
            ridges.setdefault(p2, []).append((p1, v1, v2))

        for i, sid in enumerate(ids):
            region = vor.regions[vor.point_region[i]]
            if region and all(v >= 0 for v in region):
                poly_pts = vor.vertices[region]
            else:
                new_pts = [vor.vertices[v] for v in region if v >= 0]
                for p2, v1, v2 in ridges.get(i, []):
                    if v1 >= 0 and v2 >= 0:
                        continue
                    finite_v = v2 if v1 < 0 else v1
                    tangent = vor.points[p2] - vor.points[i]
                    norm = np.linalg.norm(tangent)
                    if norm < 1e-9:
                        continue
                    tangent /= norm
                    normal = np.array([-tangent[1], tangent[0]])
                    midpoint = (vor.points[i] + vor.points[p2]) / 2
                    direction = np.sign(np.dot(midpoint - center, normal)) * normal
                    new_pts.append(vor.vertices[finite_v] + direction * radius)
                if len(new_pts) < 3:
                    areas[sid] = max(min_area_km2, float(hull.area) / n)
                    continue
                arr = np.asarray(new_pts)
                c = arr.mean(axis=0)
                angles = np.arctan2(arr[:, 1] - c[1], arr[:, 0] - c[0])
                poly_pts = arr[np.argsort(angles)]
            try:
                poly = Polygon(poly_pts).buffer(0).intersection(hull)
                areas[sid] = max(min_area_km2, float(poly.area))
            except Exception:
                areas[sid] = max(min_area_km2, float(hull.area) / n)
    return areas


# ---------------------------------------------------------------------
# Phase 0: cleaning and schema validation
# ---------------------------------------------------------------------
def phase0_clean(raw_path: str, out_dir: Path) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    log(0, "=" * 60)
    log(0, "CLEANING AND SCHEMA VALIDATION")
    log(0, "=" * 60)
    df = pd.read_csv(raw_path, low_memory=False)
    n_raw = len(df)
    required = [
        "CaseMasterID", "IncidentFromDate", "Latitude", "Longitude",
        "DistrictID", "PoliceStationID", "CrimeMajorHead", "GravityOffence",
    ]
    missing = [c for c in required if c not in df.columns]
    if missing:
        raise ValueError(f"Missing required columns: {missing}")

    df["IncidentFromDate_dt"] = robust_date(df["IncidentFromDate"])
    if "IncidentToDate" in df.columns:
        df["IncidentToDate_dt"] = robust_date(df["IncidentToDate"])
        bad_chrono = df["IncidentToDate_dt"] < df["IncidentFromDate_dt"]
        df.loc[bad_chrono, "IncidentToDate_dt"] = pd.NaT
    else:
        bad_chrono = pd.Series(False, index=df.index)

    if "CrimeRegisteredDate" in df.columns:
        df["CrimeRegisteredDate_dt"] = robust_date(df["CrimeRegisteredDate"])
        df["reporting_delay_days"] = (
            df["CrimeRegisteredDate_dt"].dt.normalize() - df["IncidentFromDate_dt"].dt.normalize()
        ).dt.days.clip(lower=0)
    else:
        df["reporting_delay_days"] = np.nan

    before_date = len(df)
    df = df[df["IncidentFromDate_dt"].notna()].copy()
    dropped_no_date = before_date - len(df)

    duplicate_cases = int(df["CaseMasterID"].duplicated().sum())
    if duplicate_cases:
        df = df.drop_duplicates("CaseMasterID", keep="first").copy()

    for col in ["DistrictID", "PoliceStationID"]:
        df[col] = pd.to_numeric(df[col], errors="coerce")
    invalid_ids = df["DistrictID"].isna() | df["PoliceStationID"].isna() | (df["DistrictID"] <= 0) | (df["PoliceStationID"] <= 0)
    invalid_id_count = int(invalid_ids.sum())
    df = df[~invalid_ids].copy()
    df["DistrictID"] = df["DistrictID"].astype(int)
    df["PoliceStationID"] = df["PoliceStationID"].astype(int)

    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")
    df["has_valid_geo"] = (
        df["Latitude"].between(*KA_LAT) & df["Longitude"].between(*KA_LON)
    )

    station_meta = (
        df.groupby("PoliceStationID", as_index=False)
        .agg(
            DistrictID=("DistrictID", "first"),
            DistrictName=("DistrictName", "first") if "DistrictName" in df.columns else ("DistrictID", lambda x: str(x.iloc[0])),
            PoliceStationName=("PoliceStationName", "first") if "PoliceStationName" in df.columns else ("PoliceStationID", lambda x: f"PS {x.iloc[0]}"),
            incident_lat=("Latitude", "mean"),
            incident_lon=("Longitude", "mean"),
            StationLatitude=("StationLatitude", "first") if "StationLatitude" in df.columns else ("Latitude", "mean"),
            StationLongitude=("StationLongitude", "first") if "StationLongitude" in df.columns else ("Longitude", "mean"),
            StationPopulation=("StationPopulation", "first") if "StationPopulation" in df.columns else ("PoliceStationID", lambda _: np.nan),
        )
    )
    station_meta["station_lat"] = pd.to_numeric(station_meta["StationLatitude"], errors="coerce").fillna(station_meta["incident_lat"])
    station_meta["station_lon"] = pd.to_numeric(station_meta["StationLongitude"], errors="coerce").fillna(station_meta["incident_lon"])
    station_meta = station_meta.drop(columns=["incident_lat", "incident_lon"])
    if station_meta[["DistrictID", "station_lat", "station_lon"]].isna().any().any():
        raise ValueError("Station metadata contains unresolved missing district or coordinates")
    station_meta, coordinate_corrections = correct_synthetic_coastal_stations(station_meta)
    save_json(out_dir, {"corrections": coordinate_corrections, "n_corrected": len(coordinate_corrections)}, "coordinate_corrections.json")

    df = df.merge(
        station_meta[["PoliceStationID", "station_lat", "station_lon"]],
        on="PoliceStationID", how="left", validate="many_to_one",
    )
    df["incident_date"] = df["IncidentFromDate_dt"].dt.normalize()
    df["week_start"] = df["incident_date"] - pd.to_timedelta(df["incident_date"].dt.dayofweek, unit="D")

    for col in ["PropertyValue_INR", "PropertyValue"]:
        if col in df.columns:
            df["PropertyValue"] = pd.to_numeric(df[col], errors="coerce").fillna(0.0)
            break
    else:
        df["PropertyValue"] = 0.0
    if "PropertyInvolved" not in df.columns:
        df["PropertyInvolved"] = (df["PropertyValue"] > 0).astype(int)

    numeric_defaults = {
        "ArrestMade": 0, "ChargeSheeted": 0, "InjuryPresent": 0,
        "PriorOffences": 0, "PropertyInvolved": 0,
    }
    for col, default in numeric_defaults.items():
        if col not in df.columns:
            df[col] = default
        df[col] = pd.to_numeric(df[col], errors="coerce").fillna(default)

    complainants = pd.DataFrame()
    if "ComplainantCaste" in df.columns:
        complainants = df[["CaseMasterID", "ComplainantCaste", "PoliceStationID", "week_start"]].copy()
    accused = pd.DataFrame()
    if "AccusedMasterID" in df.columns:
        keep = [c for c in ["CaseMasterID", "AccusedMasterID", "AccusedName", "AccusedCaste", "PoliceStationID", "DistrictID", "CrimeMajorHead", "IncidentFromDate_dt"] if c in df.columns]
        accused = df[keep].copy()

    report = {
        "raw_rows": n_raw,
        "remaining_rows": len(df),
        "dropped_no_date": dropped_no_date,
        "bad_chronology_fixed": int(bad_chrono.sum()),
        "duplicate_case_ids_removed": duplicate_cases,
        "invalid_station_or_district_ids_removed": invalid_id_count,
        "valid_geo_count": int(df["has_valid_geo"].sum()),
        "valid_geo_pct": round(float(df["has_valid_geo"].mean() * 100), 2),
        "stations": int(df["PoliceStationID"].nunique()),
        "districts": int(df["DistrictID"].nunique()),
        "coastal_station_coordinates_corrected": len(coordinate_corrections),
    }
    save_json(out_dir, report, "cleaning_report.json")
    for k, v in report.items():
        log(0, f"{k}: {v}")
    return df.reset_index(drop=True), station_meta, complainants, accused


# ---------------------------------------------------------------------
# Phase 1: recent spatial clusters, descriptive only
# ---------------------------------------------------------------------
def phase1_dbscan(df: pd.DataFrame, out_dir: Path, lookback_days: int = 180) -> list[dict[str, Any]]:
    log(1, "=" * 60)
    log(1, "RECENT DISTRICT-LEVEL DBSCAN HOTSPOTS")
    log(1, "=" * 60)
    max_date = df["incident_date"].max()
    recent = df[(df["incident_date"] > max_date - pd.Timedelta(days=lookback_days)) & df["has_valid_geo"]].copy()
    clusters: list[dict[str, Any]] = []
    total_noise = 0
    total_points = 0
    cluster_id = 0

    for did, group in recent.groupby("DistrictID"):
        coords = group[["Latitude", "Longitude"]].to_numpy()
        n = len(coords)
        if n < 12:
            continue
        rad = np.radians(coords)
        min_samples = max(8, min(25, int(round(2.5 * math.log(max(n, 10))))))
        k = min(min_samples, n)
        nn = NearestNeighbors(n_neighbors=k, metric="haversine", algorithm="ball_tree").fit(rad)
        distances, _ = nn.kneighbors(rad)
        eps = float(np.quantile(distances[:, -1], 0.70))
        eps = float(np.clip(eps, 0.25 / EARTH_RADIUS_KM, 3.0 / EARTH_RADIUS_KM))
        labels = DBSCAN(eps=eps, min_samples=min_samples, metric="haversine", algorithm="ball_tree").fit_predict(rad)
        total_points += n
        total_noise += int((labels == -1).sum())
        for local in sorted(set(labels)):
            if local == -1:
                continue
            mask = labels == local
            pts = coords[mask]
            clusters.append({
                "cluster_id": cluster_id,
                "district_id": int(did),
                "size": int(mask.sum()),
                "center_lat": float(pts[:, 0].mean()),
                "center_lon": float(pts[:, 1].mean()),
                "eps_km": round(eps * EARTH_RADIUS_KM, 3),
                "min_samples": min_samples,
                "lookback_days": lookback_days,
            })
            cluster_id += 1

    output = {
        "method": "DBSCAN by district on recent incidents",
        "descriptive_only": True,
        "lookback_days": lookback_days,
        "n_clusters": len(clusters),
        "noise_pct": round(100 * total_noise / max(total_points, 1), 2),
        "clusters": clusters,
    }
    save_json(out_dir, output, "dbscan_results.json")
    log(1, f"Clusters: {len(clusters)}, noise: {output['noise_pct']}%")
    return clusters


# ---------------------------------------------------------------------
# Shared weekly panel and features
# ---------------------------------------------------------------------
def build_weekly_panel(df: pd.DataFrame, station_meta: pd.DataFrame) -> pd.DataFrame:
    raw = (
        df.groupby(["PoliceStationID", "week_start"])
        .agg(
            crime_count=("CaseMasterID", "count"),
            serious_count=("GravityOffence", lambda s: s.astype(str).str.lower().isin(["serious", "heinous"]).sum()),
            arrest_count=("ArrestMade", "sum"),
            chargesheet_count=("ChargeSheeted", "sum"),
            injury_count=("InjuryPresent", "sum"),
            prior_offences_sum=("PriorOffences", "sum"),
            property_count=("PropertyInvolved", "sum"),
        )
        .reset_index()
    )
    weeks = pd.date_range(df["week_start"].min(), df["week_start"].max(), freq="W-MON")
    stations = station_meta["PoliceStationID"].astype(int).sort_values().unique()
    index = pd.MultiIndex.from_product([stations, weeks], names=["PoliceStationID", "week_start"])
    panel = raw.set_index(["PoliceStationID", "week_start"]).reindex(index, fill_value=0).reset_index()
    panel = panel.merge(
        station_meta[["PoliceStationID", "DistrictID", "DistrictName", "PoliceStationName", "station_lat", "station_lon", "StationPopulation"]],
        on="PoliceStationID", how="left", validate="many_to_one",
    )
    if panel[["DistrictID", "station_lat", "station_lon"]].isna().any().any():
        raise ValueError("Static station metadata was lost while creating weekly panel")
    panel = panel.sort_values(["PoliceStationID", "week_start"]).reset_index(drop=True)
    panel["DistrictID"] = panel["DistrictID"].astype(int)
    return panel


def add_model_features(panel: pd.DataFrame) -> tuple[pd.DataFrame, list[str]]:
    p = panel.copy()
    g = p.groupby("PoliceStationID", sort=False)
    for lag in [1, 2, 4, 13, 26, 52]:
        p[f"count_lag_{lag}"] = g["crime_count"].shift(lag)
    for window in [4, 13, 26, 52]:
        p[f"count_roll_{window}"] = g["crime_count"].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean())
        p[f"serious_roll_{window}"] = g["serious_count"].transform(lambda s, w=window: s.shift(1).rolling(w, min_periods=1).mean())
    for source, name in [
        ("arrest_count", "arrest_rate_hist"),
        ("chargesheet_count", "chargesheet_rate_hist"),
        ("injury_count", "injury_rate_hist"),
        ("property_count", "property_rate_hist"),
    ]:
        numerator = g[source].transform(lambda s: s.shift(1).expanding(min_periods=1).sum())
        denominator = g["crime_count"].transform(lambda s: s.shift(1).expanding(min_periods=1).sum()).clip(lower=1)
        p[name] = numerator / denominator
    p["prior_mean_hist"] = (
        g["prior_offences_sum"].transform(lambda s: s.shift(1).expanding(min_periods=1).sum()) /
        g["crime_count"].transform(lambda s: s.shift(1).expanding(min_periods=1).sum()).clip(lower=1)
    )
    p["station_mean_hist"] = g["crime_count"].transform(lambda s: s.shift(1).expanding(min_periods=4).mean())
    week_of_year = p["week_start"].dt.isocalendar().week.astype(int).clip(upper=52)
    p["sin_year"] = np.sin(2 * np.pi * week_of_year / 52.18)
    p["cos_year"] = np.cos(2 * np.pi * week_of_year / 52.18)
    p["sin_halfyear"] = np.sin(4 * np.pi * week_of_year / 52.18)
    p["cos_halfyear"] = np.cos(4 * np.pi * week_of_year / 52.18)
    min_week = p["week_start"].min()
    p["time_index"] = ((p["week_start"] - min_week).dt.days / 7).astype(float)
    p["log_population"] = np.log1p(pd.to_numeric(p["StationPopulation"], errors="coerce").fillna(0))

    # A transparent seasonal-naive benchmark using only information known at origin.
    p["seasonal_benchmark"] = (
        0.55 * p["count_roll_4"].fillna(0) +
        0.30 * p["count_lag_52"].fillna(p["station_mean_hist"]) +
        0.15 * p["station_mean_hist"].fillna(0)
    ).clip(lower=0)

    p["target_count_next_week"] = g["crime_count"].shift(-1)
    p["target_serious_next_week"] = (g["serious_count"].shift(-1) > 0).astype(float)
    # The final origin has no observed target and must never be used for evaluation.
    final_origin = p.groupby("PoliceStationID")["week_start"].transform("max") == p["week_start"]
    p.loc[final_origin, ["target_count_next_week", "target_serious_next_week"]] = np.nan

    features = [
        "count_lag_1", "count_lag_2", "count_lag_4", "count_lag_13", "count_lag_26", "count_lag_52",
        "count_roll_4", "count_roll_13", "count_roll_26", "count_roll_52",
        "serious_roll_4", "serious_roll_13", "serious_roll_26", "serious_roll_52",
        "arrest_rate_hist", "chargesheet_rate_hist", "injury_rate_hist", "property_rate_hist",
        "prior_mean_hist", "station_mean_hist", "seasonal_benchmark",
        "sin_year", "cos_year", "sin_halfyear", "cos_halfyear", "time_index", "log_population",
    ]
    p[features] = p[features].replace([np.inf, -np.inf], np.nan).fillna(0.0).astype(np.float32)
    return p, features


# ---------------------------------------------------------------------
# Phase 2: seasonal benchmark
# ---------------------------------------------------------------------
def phase2_seasonal(panel_features: pd.DataFrame, out_dir: Path) -> dict[int, dict[str, Any]]:
    log(2, "=" * 60)
    log(2, "SEASONAL TIME-SERIES BENCHMARK")
    log(2, "=" * 60)
    labelled = panel_features.dropna(subset=["target_count_next_week"]).copy()
    weeks = sorted(labelled["week_start"].unique())
    test_weeks = set(weeks[-13:])
    test = labelled[labelled["week_start"].isin(test_weeks)]
    mae = mean_absolute_error(test["target_count_next_week"], test["seasonal_benchmark"]) if len(test) else 0.0
    zero_mae = mean_absolute_error(test["target_count_next_week"], np.zeros(len(test))) if len(test) else 0.0

    latest = panel_features.sort_values("week_start").groupby("PoliceStationID").tail(1)
    forecasts: dict[int, dict[str, Any]] = {}
    for _, row in latest.iterrows():
        forecasts[int(row["PoliceStationID"])] = {
            "forecast_next_week": round(float(row["seasonal_benchmark"]), 4),
            "method": "weighted recent mean + annual seasonal naive",
            "forecast_origin": str(row["week_start"].date()),
        }
    output = {
        "method": "seasonal benchmark",
        "test_weeks": 13,
        "test_mae": round(float(mae), 4),
        "zero_baseline_mae": round(float(zero_mae), 4),
        "forecasts": forecasts,
    }
    save_json(out_dir, output, "seasonal_forecasts.json")
    # Compatibility filename for existing dashboard code.
    save_json(out_dir, output, "sarima_forecasts.json")
    log(2, f"Seasonal benchmark MAE: {mae:.3f}; zero baseline MAE: {zero_mae:.3f}")
    return forecasts


def choose_probability_threshold(y_true: np.ndarray, probabilities: np.ndarray) -> float:
    if len(np.unique(y_true)) < 2:
        return 0.5
    precision, recall, thresholds = precision_recall_curve(y_true, probabilities)
    if len(thresholds) == 0:
        return 0.5
    f1_values = 2 * precision[:-1] * recall[:-1] / np.maximum(precision[:-1] + recall[:-1], 1e-12)
    return float(thresholds[int(np.nanargmax(f1_values))])


def fit_probability_calibrator(raw_probs: np.ndarray, y_true: np.ndarray) -> LogisticRegression | None:
    if len(np.unique(y_true)) < 2 or len(raw_probs) < 50:
        return None
    clipped = np.clip(raw_probs, 1e-5, 1 - 1e-5)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    model = LogisticRegression(C=1.0, solver="lbfgs")
    model.fit(logits, y_true)
    return model


def apply_calibrator(calibrator: LogisticRegression | None, raw_probs: np.ndarray) -> np.ndarray:
    if calibrator is None:
        return np.clip(raw_probs, 0, 1)
    clipped = np.clip(raw_probs, 1e-5, 1 - 1e-5)
    logits = np.log(clipped / (1 - clipped)).reshape(-1, 1)
    return calibrator.predict_proba(logits)[:, 1]


# ---------------------------------------------------------------------
# Phase 3: two-headed future model
# ---------------------------------------------------------------------
def phase3_models(
    panel_features: pd.DataFrame,
    features: list[str],
    out_dir: Path,
) -> tuple[dict[int, dict[str, Any]], pd.DataFrame, dict[str, Any]]:
    log(3, "=" * 60)
    log(3, "TWO-HEADED NEXT-WEEK MODEL")
    log(3, "=" * 60)
    labelled = panel_features.dropna(subset=["target_count_next_week", "target_serious_next_week"]).copy()
    unique_weeks = np.array(sorted(labelled["week_start"].unique()))
    if len(unique_weeks) < 52:
        raise ValueError("At least 52 weeks are required for chronological validation")
    test_weeks = set(unique_weeks[-13:])
    val_weeks = set(unique_weeks[-26:-13])
    train_weeks = set(unique_weeks[:-26])

    train = labelled[labelled["week_start"].isin(train_weeks)].copy()
    val = labelled[labelled["week_start"].isin(val_weeks)].copy()
    test = labelled[labelled["week_start"].isin(test_weeks)].copy()

    X_train = train[features]
    X_val = val[features]
    X_test = test[features]
    y_train_count = train["target_count_next_week"].astype(float)
    y_val_count = val["target_count_next_week"].astype(float)
    y_test_count = test["target_count_next_week"].astype(float)
    y_train_serious = train["target_serious_next_week"].astype(int)
    y_val_serious = val["target_serious_next_week"].astype(int)
    y_test_serious = test["target_serious_next_week"].astype(int)

    count_model = HistGradientBoostingRegressor(
        loss="poisson", learning_rate=0.06, max_iter=240, max_leaf_nodes=31,
        min_samples_leaf=30, l2_regularization=0.4, random_state=42,
    )
    count_model.fit(X_train, y_train_count)
    val_count_pred = np.clip(count_model.predict(X_val), 0, None)
    test_count_pred = np.clip(count_model.predict(X_test), 0, None)

    serious_model = HistGradientBoostingClassifier(
        learning_rate=0.06, max_iter=220, max_leaf_nodes=31,
        min_samples_leaf=35, l2_regularization=0.6, random_state=43,
    )
    serious_model.fit(X_train, y_train_serious)
    val_raw_prob = serious_model.predict_proba(X_val)[:, 1]
    calibrator = fit_probability_calibrator(val_raw_prob, y_val_serious.to_numpy())
    val_prob = apply_calibrator(calibrator, val_raw_prob)
    threshold = choose_probability_threshold(y_val_serious.to_numpy(), val_prob)
    test_raw_prob = serious_model.predict_proba(X_test)[:, 1]
    test_prob = apply_calibrator(calibrator, test_raw_prob)
    test_pred = (test_prob >= threshold).astype(int)

    zero_pred = np.zeros(len(test))
    seasonal_pred = test["seasonal_benchmark"].to_numpy(float)
    test_mae = mean_absolute_error(y_test_count, test_count_pred)
    zero_mae = mean_absolute_error(y_test_count, zero_pred)
    seasonal_mae = mean_absolute_error(y_test_count, seasonal_pred)
    test_poisson_dev = mean_poisson_deviance(y_test_count, np.clip(test_count_pred, 1e-6, None))
    prevalence = float(y_test_serious.mean())
    ap = average_precision_score(y_test_serious, test_prob) if y_test_serious.nunique() > 1 else prevalence
    roc_auc = roc_auc_score(y_test_serious, test_prob) if y_test_serious.nunique() > 1 else 0.5
    metrics = {
        "train_rows": len(train), "validation_rows": len(val), "test_rows": len(test),
        "feature_count": len(features),
        "count_mae": round(float(test_mae), 4),
        "zero_baseline_mae": round(float(zero_mae), 4),
        "seasonal_baseline_mae": round(float(seasonal_mae), 4),
        "skill_vs_zero": round(float(1 - test_mae / max(zero_mae, 1e-9)), 4),
        "skill_vs_seasonal": round(float(1 - test_mae / max(seasonal_mae, 1e-9)), 4),
        "mean_poisson_deviance": round(float(test_poisson_dev), 4),
        "serious_prevalence": round(prevalence, 4),
        "serious_average_precision": round(float(ap), 4),
        "serious_roc_auc": round(float(roc_auc), 4),
        "serious_brier": round(float(brier_score_loss(y_test_serious, test_prob)), 4),
        "serious_threshold": round(float(threshold), 4),
        "serious_f1": round(float(f1_score(y_test_serious, test_pred, zero_division=0)), 4),
        "serious_precision": round(float(precision_score(y_test_serious, test_pred, zero_division=0)), 4),
        "serious_recall": round(float(recall_score(y_test_serious, test_pred, zero_division=0)), 4),
    }
    log(3, f"Count MAE {test_mae:.3f}; zero {zero_mae:.3f}; seasonal {seasonal_mae:.3f}")
    log(3, f"Serious AP {ap:.3f}; F1 {metrics['serious_f1']:.3f}; Brier {metrics['serious_brier']:.3f}")

    pred_val = val[["PoliceStationID", "DistrictID", "week_start", "target_count_next_week", "target_serious_next_week"]].copy()
    pred_val["split"] = "validation"
    pred_val["count_prediction"] = val_count_pred
    pred_val["serious_probability"] = val_prob
    pred_test = test[["PoliceStationID", "DistrictID", "week_start", "target_count_next_week", "target_serious_next_week"]].copy()
    pred_test["split"] = "test"
    pred_test["count_prediction"] = test_count_pred
    pred_test["serious_probability"] = test_prob
    prediction_frame = pd.concat([pred_val, pred_test], ignore_index=True)

    # Operational models: use all labelled rows for the count model. For the
    # classifier, retain the last 13 weeks as probability calibration data.
    final_count_model = HistGradientBoostingRegressor(
        loss="poisson", learning_rate=0.06, max_iter=260, max_leaf_nodes=31,
        min_samples_leaf=30, l2_regularization=0.4, random_state=42,
    )
    final_count_model.fit(labelled[features], labelled["target_count_next_week"].astype(float))
    final_clf_train = labelled[~labelled["week_start"].isin(test_weeks)]
    final_calib = labelled[labelled["week_start"].isin(test_weeks)]
    final_serious_model = HistGradientBoostingClassifier(
        learning_rate=0.06, max_iter=240, max_leaf_nodes=31,
        min_samples_leaf=35, l2_regularization=0.6, random_state=43,
    )
    final_serious_model.fit(final_clf_train[features], final_clf_train["target_serious_next_week"].astype(int))
    final_calib_raw = final_serious_model.predict_proba(final_calib[features])[:, 1]
    final_calibrator = fit_probability_calibrator(final_calib_raw, final_calib["target_serious_next_week"].astype(int).to_numpy())

    latest = panel_features.sort_values("week_start").groupby("PoliceStationID").tail(1).copy().reset_index(drop=True)
    latest_count_pred = np.clip(final_count_model.predict(latest[features]), 0, None)
    latest_raw_prob = final_serious_model.predict_proba(latest[features])[:, 1]
    latest_prob = apply_calibrator(final_calibrator, latest_raw_prob)
    max_count = max(float(latest_count_pred.max()), 1e-9)
    zone_scores: dict[int, dict[str, Any]] = {}
    for i, row in latest.iterrows():
        sid = int(row["PoliceStationID"])
        zone_scores[sid] = {
            "forecast_count_next_week": round(float(latest_count_pred[i]), 4),
            "raw_risk": round(float(latest_count_pred[i] / max_count), 4),
            "seasonal_benchmark": round(float(row["seasonal_benchmark"]), 4),
            "serious_risk_prob": round(float(latest_prob[i]), 4),
            "serious_threshold": round(float(threshold), 4),
            "district": int(row["DistrictID"]),
            "district_name": str(row["DistrictName"]),
            "station_name": str(row["PoliceStationName"]),
            "lat": float(row["station_lat"]),
            "lon": float(row["station_lon"]),
            "forecast_origin": str(row["week_start"].date()),
            "forecast_target_week": str((row["week_start"] + pd.Timedelta(days=7)).date()),
        }

    save_json(out_dir, {
        "metrics": metrics,
        "features": features,
        "zone_scores": zone_scores,
        "note": "All reported metrics use chronological validation and a later untouched test period.",
    }, "model_results.json")
    # Compatibility filename.
    save_json(out_dir, {"metrics": metrics, "zone_scores": zone_scores}, "rf_results.json")
    return zone_scores, prediction_frame, metrics


# ---------------------------------------------------------------------
# Phase 4: near-repeat context using date permutation and station kernel
# ---------------------------------------------------------------------
def estimate_near_repeat(df: pd.DataFrame, sample_size: int = 8000) -> tuple[float, int, float]:
    geo = df[df["has_valid_geo"]][["Latitude", "Longitude", "incident_date"]].dropna().copy()
    if len(geo) > sample_size:
        geo = geo.sample(sample_size, random_state=42)
    if len(geo) < 200:
        return 0.4, 7, 1.0
    coords = np.radians(geo[["Latitude", "Longitude"]].to_numpy())
    dates = geo["incident_date"].to_numpy(dtype="datetime64[D]")
    tree = BallTree(coords, metric="haversine")
    radii = [0.2, 0.4, 0.8, 1.2]
    day_windows = [3, 7, 14]
    rng = np.random.default_rng(42)
    best = (1.0, 0.4, 7)
    for radius in radii:
        neighbors = tree.query_radius(coords, r=radius / EARTH_RADIUS_KM)
        pairs = [(i, int(j)) for i, js in enumerate(neighbors) for j in js if j > i]
        if len(pairs) > 30_000:
            selected = rng.choice(len(pairs), 30_000, replace=False)
            pairs = [pairs[k] for k in selected]
        if len(pairs) < 30:
            continue
        gaps = np.array([abs(int((dates[i] - dates[j]).astype(int))) for i, j in pairs])
        perm_dates = rng.permutation(dates)
        perm_gaps = np.array([abs(int((perm_dates[i] - perm_dates[j]).astype(int))) for i, j in pairs])
        for days in day_windows:
            observed = float(np.mean(gaps <= days))
            expected = float(np.mean(perm_gaps <= days))
            ratio = observed / max(expected, 1e-9)
            if ratio > best[0]:
                best = (ratio, radius, days)
    return float(best[1]), int(best[2]), float(best[0])


def phase4_near_repeat(df: pd.DataFrame, zone_scores: dict[int, dict[str, Any]], out_dir: Path) -> dict[int, dict[str, Any]]:
    log(4, "=" * 60)
    log(4, "NEAR-REPEAT CONTEXT")
    log(4, "=" * 60)
    radius_km, day_window, ratio = estimate_near_repeat(df)
    max_date = df["incident_date"].max()
    recent = df[(df["incident_date"] > max_date - pd.Timedelta(days=day_window)) & df["has_valid_geo"]].copy()
    station_ids = np.array(sorted(zone_scores), dtype=int)
    station_coords = np.radians(np.array([[zone_scores[s]["lat"], zone_scores[s]["lon"]] for s in station_ids]))
    station_tree = BallTree(station_coords, metric="haversine")
    boosts = {int(s): 0.0 for s in station_ids}
    if len(recent):
        for _, event in recent.iterrows():
            q = np.radians([[event["Latitude"], event["Longitude"]]])
            station_query_radius_km = max(2.0, radius_km * 8.0)
            inds, dists = station_tree.query_radius(q, r=station_query_radius_km / EARTH_RADIUS_KM, return_distance=True)
            age = max((max_date - event["incident_date"]).days, 0)
            time_weight = math.exp(-age / max(day_window, 1))
            severity = 1.5 if str(event["GravityOffence"]).lower() == "heinous" else 1.0
            for idx, dist in zip(inds[0], dists[0]):
                sid = int(station_ids[idx])
                spatial_weight = math.exp(-float(dist) * EARTH_RADIUS_KM / max(1.0, radius_km * 4.0))
                boosts[sid] += time_weight * spatial_weight * severity
    max_boost = max(boosts.values()) if boosts else 0.0
    for sid in zone_scores:
        score = boosts.get(sid, 0.0) / max(max_boost, 1e-9)
        zone_scores[sid]["near_repeat_score"] = round(float(score), 4)
        zone_scores[sid]["near_repeat_alert"] = bool(score >= 0.55 and ratio > 1.1)
    output = {
        "estimated_radius_km": radius_km,
        "estimated_day_window": day_window,
        "permutation_ratio": round(ratio, 3),
        "zones_with_alert": int(sum(v["near_repeat_alert"] for v in zone_scores.values())),
        "note": "Near-repeat score is contextual and is not added to the calibrated count forecast.",
    }
    save_json(out_dir, output, "near_repeat_results.json")
    log(4, f"Permutation ratio {ratio:.2f} at {radius_km:.1f}km/{day_window}d; alerts {output['zones_with_alert']}")
    return zone_scores


# ---------------------------------------------------------------------
# Phase 5: Gamma-Poisson empirical Bayes uncertainty
# ---------------------------------------------------------------------
def phase5_empirical_bayes(panel: pd.DataFrame, zone_scores: dict[int, dict[str, Any]], out_dir: Path) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    log(5, "=" * 60)
    log(5, "GAMMA-POISSON EMPIRICAL BAYES UNCERTAINTY")
    log(5, "=" * 60)
    latest_week = panel["week_start"].max()
    recent = panel[panel["week_start"] > latest_week - pd.Timedelta(weeks=52)].copy()
    district_stats = recent.groupby("DistrictID")["crime_count"].agg(["mean", "var"])
    results: dict[int, dict[str, Any]] = {}
    for sid, group in recent.groupby("PoliceStationID"):
        did = int(group["DistrictID"].iloc[0])
        mean = max(float(district_stats.loc[did, "mean"]), 1e-3)
        var = max(float(district_stats.loc[did, "var"]), mean + 1e-3)
        alpha0 = max(mean * mean / max(var - mean, 1e-3), 0.5)
        beta0 = alpha0 / mean
        exposure = len(group)
        count_sum = float(group["crime_count"].sum())
        alpha_post = alpha0 + count_sum
        beta_post = beta0 + exposure
        posterior_mean = alpha_post / beta_post
        low = float(gamma_dist.ppf(0.10, a=alpha_post, scale=1 / beta_post))
        high = float(gamma_dist.ppf(0.90, a=alpha_post, scale=1 / beta_post))
        rel_width = (high - low) / max(posterior_mean, 1e-6)
        confidence = float(np.clip(1 / (1 + rel_width), 0, 1))
        results[int(sid)] = {
            "posterior_weekly_rate": round(posterior_mean, 4),
            "interval_80_low": round(low, 4),
            "interval_80_high": round(high, 4),
            "relative_interval_width": round(rel_width, 4),
            "confidence": round(confidence, 4),
            "weeks_observed": exposure,
            "district_id": did,
        }
        if int(sid) in zone_scores:
            zone_scores[int(sid)]["confidence"] = round(confidence, 4)
            zone_scores[int(sid)]["historical_rate_eb"] = round(posterior_mean, 4)
            zone_scores[int(sid)]["historical_rate_interval_80"] = [round(low, 4), round(high, 4)]
    save_json(out_dir, {"zones": results}, "empirical_bayes.json")
    log(5, f"Median confidence: {np.median([v['confidence'] for v in results.values()]):.3f}")
    return zone_scores, results


# ---------------------------------------------------------------------
# Phase 6: prospective PAI threshold calibration
# ---------------------------------------------------------------------
def aggregate_pai(frame: pd.DataFrame, threshold: float, area_map: dict[int, float], district_stations: list[int]) -> float:
    total_caught = 0.0
    total_crime = 0.0
    flagged_area_period = 0.0
    total_area_period = 0.0
    district_area = sum(area_map.get(s, 5.0) for s in district_stations)
    for _, week in frame.groupby("week_start"):
        flagged = week.loc[week["count_prediction"] >= threshold, "PoliceStationID"].astype(int).tolist()
        total_caught += float(week.loc[week["PoliceStationID"].isin(flagged), "target_count_next_week"].sum())
        total_crime += float(week["target_count_next_week"].sum())
        flagged_area_period += sum(area_map.get(s, 5.0) for s in flagged)
        total_area_period += district_area
    crime_fraction = total_caught / max(total_crime, 1e-9)
    area_fraction = flagged_area_period / max(total_area_period, 1e-9)
    return float(crime_fraction / max(area_fraction, 1e-9)) if total_caught > 0 else 0.0


def phase6_pai(
    df: pd.DataFrame,
    prediction_frame: pd.DataFrame,
    zone_scores: dict[int, dict[str, Any]],
    out_dir: Path,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]]]:
    log(6, "=" * 60)
    log(6, "PROSPECTIVE PAI CALIBRATION")
    log(6, "=" * 60)
    area_map = station_area_lookup(df)
    thresholds: dict[int, dict[str, Any]] = {}
    validation = prediction_frame[prediction_frame["split"] == "validation"]
    test = prediction_frame[prediction_frame["split"] == "test"]

    for did in sorted(prediction_frame["DistrictID"].unique()):
        val_d = validation[validation["DistrictID"] == did]
        test_d = test[test["DistrictID"] == did]
        stations = sorted(val_d["PoliceStationID"].astype(int).unique())
        if len(stations) < 3 or val_d["target_count_next_week"].sum() < 10:
            continue
        candidates = np.unique(np.quantile(val_d["count_prediction"], np.linspace(0.45, 0.92, 12)))
        best_threshold = float(np.median(val_d["count_prediction"]))
        best_val_pai = -1.0
        for threshold in candidates:
            pai = aggregate_pai(val_d, float(threshold), area_map, stations)
            if pai > best_val_pai:
                best_val_pai = pai
                best_threshold = float(threshold)
        test_pai = aggregate_pai(test_d, best_threshold, area_map, stations) if len(test_d) else 0.0
        thresholds[int(did)] = {
            "forecast_count_threshold": round(best_threshold, 4),
            "validation_pai": round(best_val_pai, 3),
            "test_pai": round(test_pai, 3),
            "n_zones": len(stations),
            "total_area_km2": round(sum(area_map.get(s, 5.0) for s in stations), 3),
        }
        log(6, f"District {did}: threshold {best_threshold:.3f}, validation PAI {best_val_pai:.2f}, test PAI {test_pai:.2f}")

    fallback = float(np.median([v["forecast_count_threshold"] for v in thresholds.values()])) if thresholds else float(np.median([v["forecast_count_next_week"] for v in zone_scores.values()]))
    serious_threshold = float(np.median([v["serious_threshold"] for v in zone_scores.values()]))
    label_counts: dict[str, int] = {}
    for sid, score in zone_scores.items():
        did = int(score["district"])
        threshold = thresholds.get(did, {}).get("forecast_count_threshold", fallback)
        high_count = score["forecast_count_next_week"] >= threshold
        high_serious = score["serious_risk_prob"] >= serious_threshold
        if high_count:
            label = "HOTSPOT"
            color = "#FF3B30"
        elif high_serious or score.get("near_repeat_alert", False):
            label = "WATCH"
            color = "#FF9500"
        else:
            label = "SAFE"
            color = "#34C759"
        score["zone_label"] = label
        score["zone_color"] = color
        score["threshold_count"] = round(float(threshold), 4)
        score["zone_area_km2"] = round(float(area_map.get(sid, 5.0)), 3)
        score["confidence_level"] = "HIGH" if score.get("confidence", 0) >= 0.70 else "LOW"
        label_counts[label] = label_counts.get(label, 0) + 1
    save_json(out_dir, {"districts": thresholds, "global_fallback": fallback}, "pai_thresholds.json")
    save_json(out_dir, zone_scores, "zone_classification.json")
    log(6, f"Zone labels: {label_counts}")
    return zone_scores, thresholds


# ---------------------------------------------------------------------
# Phase 7: descriptive fairness diagnostics
# ---------------------------------------------------------------------
def phase7_fairness(df: pd.DataFrame, zone_scores: dict[int, dict[str, Any]], out_dir: Path) -> dict[str, Any]:
    log(7, "=" * 60)
    log(7, "DESCRIPTIVE FAIRNESS DIAGNOSTICS")
    log(7, "=" * 60)
    diagnostics: dict[str, Any] = {
        "warnings": [],
        "metrics": {},
        "limitations": [
            "These are descriptive diagnostics, not a legal disparate-impact determination.",
            "Demographic population denominators and patrol-allocation outcomes are unavailable.",
        ],
    }

    if "AccusedCaste" in df.columns and "ArrestMade" in df.columns:
        rates = df.groupby("AccusedCaste")["ArrestMade"].agg(["mean", "count"])
        rates = rates[rates["count"] >= 100]
        diagnostics["metrics"]["arrest_rates_by_accused_caste"] = {
            str(k): {"rate": round(float(v["mean"]), 4), "n": int(v["count"])} for k, v in rates.iterrows()
        }
        if len(rates) > 1:
            ratio = float(rates["mean"].min() / max(rates["mean"].max(), 1e-9))
            diagnostics["metrics"]["raw_arrest_rate_min_max_ratio"] = round(ratio, 4)
            if ratio < 0.8:
                diagnostics["warnings"].append("Large unadjusted arrest-rate difference across accused-caste groups; investigate with causal and exposure-adjusted analysis.")

    if "ComplainantCaste" in df.columns:
        labels = {sid: score.get("zone_label", "SAFE") for sid, score in zone_scores.items()}
        temp = df[["ComplainantCaste", "PoliceStationID"]].copy()
        temp["current_high_attention_zone"] = temp["PoliceStationID"].map(labels).isin(["HOTSPOT", "WATCH"])
        exposure = temp.groupby("ComplainantCaste")["current_high_attention_zone"].agg(["mean", "count"])
        exposure = exposure[exposure["count"] >= 100]
        diagnostics["metrics"]["historical_incident_share_in_current_high_attention_zones"] = {
            str(k): {"share": round(float(v["mean"]), 4), "n": int(v["count"])} for k, v in exposure.iterrows()
        }

    diagnostics["metrics"]["warning_count"] = len(diagnostics["warnings"])
    save_json(out_dir, diagnostics, "fairness_audit.json")
    log(7, f"Audit complete: {len(diagnostics['warnings'])} warning(s)")
    return diagnostics


# ---------------------------------------------------------------------
# Phase 8: cyber network using stable identifiers only
# ---------------------------------------------------------------------
def phase8_cyber(df: pd.DataFrame, out_dir: Path) -> dict[str, Any]:
    log(8, "=" * 60)
    log(8, "CYBER / FINANCIAL CRIME NETWORK")
    log(8, "=" * 60)
    cyber_mask = df["CrimeMajorHead"].astype(str).str.contains("Cyber|Economic", case=False, regex=True)
    if "CrimeMinorHead" in df.columns:
        cyber_mask |= df["CrimeMinorHead"].astype(str).str.contains("Fraud|Online|Hacking|Cheating", case=False, regex=True)
    cyber = df[cyber_mask].copy()
    monthly = cyber.groupby(cyber["incident_date"].dt.to_period("M")).size()

    warning = None
    if "AccusedMasterID" not in cyber.columns:
        warning = "AccusedMasterID missing; network omitted rather than merging people by name."
        network = {"nodes": [], "edges": [], "n_total_accused": 0, "n_repeat_accused": 0, "route_capable": False}
    else:
        cyber = cyber[cyber["AccusedMasterID"].notna()].copy()
        counts = cyber["AccusedMasterID"].value_counts()
        repeat_ids = counts[counts >= 2].index
        retained_cyber = cyber[cyber["AccusedMasterID"].isin(repeat_ids)].copy()
        retained_cyber = retained_cyber.sort_values(["AccusedMasterID", "incident_date", "CaseMasterID"])

        station_meta = (
            df.groupby("PoliceStationID", as_index=False)
            .agg(station_name=("PoliceStationName", "first"), district=("DistrictID", "first"),
                 district_name=("DistrictName", "first"), lat=("station_lat", "first"), lon=("station_lon", "first"))
        )
        station_lookup = station_meta.set_index("PoliceStationID").to_dict("index")

        nodes: list[dict[str, Any]] = []
        edges: list[dict[str, Any]] = []
        used_stations: set[int] = set()
        for accused_id, group in retained_cyber.groupby("AccusedMasterID"):
            group = group.sort_values("incident_date")
            aid = f"A_{accused_id}"
            station_sequence = []
            for sid, sg in group.groupby("PoliceStationID"):
                sid = int(sid); used_stations.add(sid)
                crime_counts = sg["CrimeMajorHead"].astype(str).value_counts().head(4)
                station_sequence.append({
                    "station_id": sid, "first_active": str(sg["incident_date"].min().date()),
                    "last_active": str(sg["incident_date"].max().date()), "case_count": int(len(sg)),
                })
                edges.append({
                    "source": aid, "target": f"PS_{sid}", "case_count": int(len(sg)),
                    "first_active": str(sg["incident_date"].min().date()),
                    "last_active": str(sg["incident_date"].max().date()),
                    "crime_heads": [{"crime": str(k), "count": int(v)} for k, v in crime_counts.items()],
                    "case_ids": [str(x) for x in sg["CaseMasterID"].head(8).tolist()],
                })
            station_sequence.sort(key=lambda x: (x["first_active"], x["station_id"]))
            nodes.append({
                "id": aid, "node_type": "accused",
                "display_name": str(group["AccusedName"].iloc[0]) if "AccusedName" in group.columns else str(accused_id),
                "case_count": int(len(group)), "station_count": int(group["PoliceStationID"].nunique()),
                "first_active": str(group["incident_date"].min().date()),
                "last_active": str(group["incident_date"].max().date()),
                "route_station_ids": [int(x["station_id"]) for x in station_sequence],
            })
        for sid in sorted(used_stations):
            meta = station_lookup.get(sid, {})
            nodes.append({
                "id": f"PS_{sid}", "node_type": "station", "station_id": sid,
                "station_name": str(meta.get("station_name", f"PS {sid}")),
                "district": int(meta.get("district", 0)), "district_name": str(meta.get("district_name", "")),
                "lat": float(meta.get("lat", np.nan)), "lon": float(meta.get("lon", np.nan)),
            })
        network = {
            "nodes": nodes, "edges": edges, "n_total_accused": int(counts.size),
            "n_repeat_accused": int((counts >= 2).sum()),
            "full_graph_nodes": int(len(nodes)), "full_graph_edges": int(len(edges)),
            "route_capable": True, "default_top_accused": 5, "default_min_link_cases": 3,
            "display_note": "Dashboard defaults to a filtered bipartite view; all repeat-accused links remain available in JSON.",
        }
    output = {
        "total_cyber_firs": int(len(cyber)),
        "monthly_trend": [{"period": str(k), "count": int(v)} for k, v in monthly.items()],
        "network": network, "warning": warning,
    }
    save_json(out_dir, output, "cyber_network.json")
    log(8, f"Cyber/financial FIRs: {len(cyber):,}; repeat accused: {network['n_repeat_accused']}; route edges: {len(network.get('edges', []))}")
    return output


# ---------------------------------------------------------------------
# Phase 9: completed-week anomaly detection with FDR control
# ---------------------------------------------------------------------
def benjamini_hochberg(p_values: np.ndarray, alpha: float = 0.05) -> np.ndarray:
    n = len(p_values)
    order = np.argsort(p_values)
    ranked = p_values[order]
    thresholds = alpha * (np.arange(1, n + 1) / n)
    passed = ranked <= thresholds
    selected = np.zeros(n, dtype=bool)
    if passed.any():
        cutoff = ranked[np.where(passed)[0].max()]
        selected = p_values <= cutoff
    return selected


def phase9_anomaly(panel: pd.DataFrame, out_dir: Path) -> list[dict[str, Any]]:
    log(9, "=" * 60)
    log(9, "COMPLETED-WEEK ANOMALY DETECTION")
    log(9, "=" * 60)
    latest_week = panel["week_start"].max()
    # Treat max week as potentially incomplete; inspect previous completed week.
    target_week = latest_week - pd.Timedelta(weeks=1)
    target = panel[panel["week_start"] == target_week].copy()
    history = panel[(panel["week_start"] < target_week) & (panel["week_start"] >= target_week - pd.Timedelta(weeks=26))]
    means = history.groupby("PoliceStationID")["crime_count"].mean()
    target["expected"] = target["PoliceStationID"].map(means).fillna(0.0)
    target["p_value"] = poisson.sf(target["crime_count"] - 1, np.clip(target["expected"], 1e-6, None))
    target["fdr_alert"] = benjamini_hochberg(target["p_value"].to_numpy(), alpha=0.05)
    alerts = []
    for _, row in target[target["fdr_alert"]].sort_values("p_value").iterrows():
        alerts.append({
            "station": int(row["PoliceStationID"]),
            "week": str(row["week_start"].date()),
            "count": int(row["crime_count"]),
            "expected": round(float(row["expected"]), 2),
            "p_value": round(float(row["p_value"]), 8),
            "method": "Poisson upper-tail with Benjamini-Hochberg FDR 0.05",
        })
    save_json(out_dir, {"alerts": alerts, "n_total": len(alerts), "target_week": str(target_week.date())}, "anomaly_alerts.json")
    log(9, f"FDR-controlled anomaly alerts: {len(alerts)}")
    return alerts


# ---------------------------------------------------------------------
# Rolling heatmap
# ---------------------------------------------------------------------
def phase_r_heatmap(df: pd.DataFrame, out_dir: Path, max_frames: int = 104) -> list[dict[str, Any]]:
    log("R", "=" * 60)
    log("R", "ROLLING HISTORICAL HEATMAP")
    log("R", "=" * 60)
    weeks = pd.date_range(df["week_start"].min(), df["week_start"].max(), freq="W-MON")
    if len(weeks) > max_frames:
        weeks = weeks[-max_frames:]
    frames = []
    for week in weeks:
        g = df[(df["week_start"] >= week) & (df["week_start"] < week + pd.Timedelta(days=7)) & df["has_valid_geo"]]
        points = (
            g.groupby("PoliceStationID")
            .agg(lat=("station_lat", "first"), lon=("station_lon", "first"), count=("CaseMasterID", "count"))
            .reset_index()
        )
        frames.append({
            "week_start": str(week.date()),
            "points": [{"station": int(r.PoliceStationID), "lat": float(r.lat), "lon": float(r.lon), "count": int(r.count)} for r in points.itertuples(index=False)],
        })
    save_json(out_dir, {"type": "historical_incidents", "frames": frames}, "rolling_heatmap.json")
    log("R", f"Generated {len(frames)} historical frames")
    return frames


# ---------------------------------------------------------------------
# Sanity checks and dashboard
# ---------------------------------------------------------------------
def phase_s_sanity(
    df: pd.DataFrame,
    station_meta: pd.DataFrame,
    zone_scores: dict[int, dict[str, Any]],
    metrics: dict[str, Any],
    thresholds: dict[int, dict[str, Any]],
    cyber: dict[str, Any],
    out_dir: Path,
) -> dict[str, Any]:
    log("S", "=" * 60)
    log("S", "PIPELINE SANITY CHECKS")
    log("S", "=" * 60)
    calibrated_districts = len(thresholds)
    total_districts = int(df["DistrictID"].nunique())
    checks = {
        "no_zero_or_missing_district_ids": bool((df["DistrictID"] > 0).all() and all(v["district"] > 0 for v in zone_scores.values())),
        "one_score_per_station": len(zone_scores) == int(station_meta["PoliceStationID"].nunique()),
        "nonnegative_forecasts": all(v["forecast_count_next_week"] >= 0 for v in zone_scores.values()),
        "finite_probabilities": all(0 <= v["serious_risk_prob"] <= 1 for v in zone_scores.values()),
        "count_model_beats_zero_baseline": metrics["count_mae"] < metrics["zero_baseline_mae"],
        "classifier_beats_prevalence_ap": metrics["serious_average_precision"] > metrics["serious_prevalence"],
        "pai_calibrated_for_most_districts": calibrated_districts >= max(1, int(0.8 * total_districts)),
        "stable_accused_identifier_used": cyber.get("warning") is None,
        "labels_present": all(v.get("zone_label") in {"SAFE", "WATCH", "HOTSPOT"} for v in zone_scores.values()),
    }
    warnings_list = []
    if metrics["count_mae"] >= metrics["seasonal_baseline_mae"]:
        warnings_list.append("Count model did not beat the seasonal baseline on the final test period.")
    median_test_pai = float(np.median([v["test_pai"] for v in thresholds.values()])) if thresholds else 0.0
    if median_test_pai <= 1.0:
        warnings_list.append("Median district test PAI is not above random area allocation.")
    report = {
        "all_critical_checks_passed": bool(all(checks.values())),
        "checks": checks,
        "warnings": warnings_list,
        "metrics": {
            "stations": len(zone_scores),
            "districts": total_districts,
            "calibrated_districts": calibrated_districts,
            "median_test_pai": round(median_test_pai, 3),
            "count_skill_vs_zero": metrics["skill_vs_zero"],
            "count_skill_vs_seasonal": metrics["skill_vs_seasonal"],
            "serious_average_precision": metrics["serious_average_precision"],
            "serious_prevalence": metrics["serious_prevalence"],
        },
    }
    save_json(out_dir, report, "pipeline_sanity_report.json")
    for name, passed in checks.items():
        log("S", f"{'PASS' if passed else 'FAIL'}: {name}")
    for warning in warnings_list:
        log("S", f"WARNING: {warning}")
    return report


def bundle_dashboard(
    zone_scores: dict[int, dict[str, Any]],
    clusters: list[dict[str, Any]],
    seasonal: dict[int, dict[str, Any]],
    cyber: dict[str, Any],
    anomalies: list[dict[str, Any]],
    fairness: dict[str, Any],
    thresholds: dict[int, dict[str, Any]],
    metrics: dict[str, Any],
    sanity: dict[str, Any],
    out_dir: Path,
) -> None:
    zones = [{"zone_id": sid, **score} for sid, score in sorted(zone_scores.items())]
    summary = {
        "zones": len(zones),
        "hotspots": sum(z["zone_label"] == "HOTSPOT" for z in zones),
        "watch": sum(z["zone_label"] == "WATCH" for z in zones),
        "safe": sum(z["zone_label"] == "SAFE" for z in zones),
        "anomaly_alerts": len(anomalies),
        "cyber_firs": cyber.get("total_cyber_firs", 0),
        "count_model_mae": metrics["count_mae"],
        "serious_average_precision": metrics["serious_average_precision"],
        "sanity_ok": sanity["all_critical_checks_passed"],
    }
    save_json(out_dir, {
        "summary": summary,
        "zones": zones,
        "clusters": clusters,
        "seasonal_forecasts": seasonal,
        "district_thresholds": thresholds,
        "anomaly_alerts": anomalies,
        "fairness": fairness,
        "cyber_monthly": cyber.get("monthly_trend", []),
        "cyber_network": cyber.get("network", {}),
        "model_metrics": metrics,
        "sanity": sanity,
    }, "dashboard_data.json")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run corrected KSP crime forecasting pipeline")
    parser.add_argument("--csv", required=True, help="Input CSV")
    parser.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    parser.add_argument("--skip-heatmap", action="store_true")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    log("MAIN", "=" * 60)
    log("MAIN", "KSP CRIME INTELLIGENCE PIPELINE V8")
    log("MAIN", "Forecast horizon: next complete week")
    log("MAIN", "Validation: chronological train / validation / untouched test")
    log("MAIN", "=" * 60)

    df, station_meta, complainants, accused = phase0_clean(args.csv, out_dir)
    clusters = phase1_dbscan(df, out_dir)
    panel = build_weekly_panel(df, station_meta)
    panel_features, features = add_model_features(panel)
    seasonal = phase2_seasonal(panel_features, out_dir)
    zone_scores, prediction_frame, metrics = phase3_models(panel_features, features, out_dir)
    zone_scores = phase4_near_repeat(df, zone_scores, out_dir)
    zone_scores, eb = phase5_empirical_bayes(panel, zone_scores, out_dir)
    zone_scores, thresholds = phase6_pai(df, prediction_frame, zone_scores, out_dir)
    fairness = phase7_fairness(df, zone_scores, out_dir)
    cyber = phase8_cyber(df, out_dir)
    anomalies = phase9_anomaly(panel, out_dir)
    if not args.skip_heatmap:
        phase_r_heatmap(df, out_dir)
    sanity = phase_s_sanity(df, station_meta, zone_scores, metrics, thresholds, cyber, out_dir)
    bundle_dashboard(zone_scores, clusters, seasonal, cyber, anomalies, fairness, thresholds, metrics, sanity, out_dir)

    log("MAIN", "Pipeline complete.")
    if not sanity["all_critical_checks_passed"]:
        failed = [k for k, v in sanity["checks"].items() if not v]
        raise SystemExit(f"Critical sanity checks failed: {failed}")


if __name__ == "__main__":
    main()

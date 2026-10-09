import pandas as pd


def rank_absolute_strength(df: pd.DataFrame, col: str = "perf_1m") -> pd.DataFrame:
    """Add a 1-99 percentile rank column based on 1-month performance.

    The ranking is cross-sectional: every stock is compared to the full
    population passed in. Higher rank = stronger momentum.
    """
    if df.empty or col not in df.columns:
        df["abs_strength"] = None
        return df

    valid = df[col].notna()
    df.loc[valid, "abs_strength"] = (
        df.loc[valid, col]
        .rank(pct=True)
        .multiply(98)
        .add(1)
        .round(0)
        .astype(int)
    )
    df.loc[~valid, "abs_strength"] = None
    return df

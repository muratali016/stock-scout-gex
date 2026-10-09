"""Relative Measured Volatility (RMV) utilities.

RMV-15 = (15-day ATR / 50-day ATR) * 100

Values below ~75 indicate the recent range is contracting relative to
the longer-term average, a common precursor to breakout moves.
"""

import pandas as pd


def flag_contraction(df: pd.DataFrame, threshold: float = 75.0) -> pd.DataFrame:
    """Add a boolean 'vol_contraction' column: True when RMV-15 < threshold."""
    if "rmv_15" not in df.columns:
        df["vol_contraction"] = False
        return df

    df["vol_contraction"] = df["rmv_15"].notna() & (df["rmv_15"] < threshold)
    return df
